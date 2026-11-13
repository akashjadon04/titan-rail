"""FastAPI application factory.

External dependencies (catalog, event store, clock) are injected through
``create_app`` so the whole test suite runs against fakes with no network
and no shared state. The module-level ``app`` uses production defaults and
is what uvicorn and the Dockerfile serve.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

from . import __version__
from .idempotency import EventStore
from .mapping import MethodMapper, ShippingMethod, load_catalog
from .models import (
    Gap,
    HealthEvidence,
    HealthResponse,
    LadderStep,
    MappedMethod,
    MappingEvidence,
    MappingRequest,
    MappingResponse,
    MethodCandidate,
    OpsAlertEvidence,
    OpsAlertResponse,
    OrderSinkEvidence,
    OrderSinkResponse,
    ReconcileEvidence,
    ReconcileRequest,
    ReconcileResponse,
    ValidationEvidence,
    ValidationResponse,
    WebhookEvidence,
    WebhookResponse,
)
from .reconcile import reconcile
from .validation import OrderValidator

# Built-in synthetic catalog for a fictional merchant (Aurora Home Goods)
# shipping through fictional carriers. Override with MF_CATALOG_PATH or by
# injecting a MethodMapper into create_app.
DEFAULT_METHODS: tuple[ShippingMethod, ...] = (
    ShippingMethod(
        "SM-STD-01",
        "Standard Ground",
        "Marlin Post",
        ("standard", "ground", "standard shipping", "std"),
    ),
    ShippingMethod(
        "SM-EXP-02",
        "Express Air",
        "Veltro Express",
        ("express", "express shipping", "air express", "veltro"),
    ),
    ShippingMethod(
        "SM-ECO-03",
        "Economy Parcel",
        "Marlin Post",
        ("economy", "eco", "economy parcel", "cheapest"),
    ),
    ShippingMethod(
        "SM-INT-04",
        "International Priority",
        "Quickstep Freight",
        ("international", "intl priority", "priority international"),
    ),
    ShippingMethod(
        "SM-PUP-05",
        "Pickup Point",
        "Cascade Lockers",
        ("pickup", "locker", "pickup point", "click and collect", "click collect"),
    ),
)


# Dedup keys longer than this are almost never real ids; they are payloads
# mapped into the wrong field, and indexing them helps nobody.
MAX_EVENT_ID_LENGTH = 512


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_mapper() -> MethodMapper:
    catalog_path = os.environ.get("MF_CATALOG_PATH")
    if catalog_path:
        return MethodMapper(load_catalog(Path(catalog_path)))
    return MethodMapper(DEFAULT_METHODS)


def create_app(
    *,
    mapper: MethodMapper | None = None,
    store: EventStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the service with injectable seams for catalog, store, and clock."""

    active_mapper = mapper if mapper is not None else _default_mapper()
    active_store = (
        store
        if store is not None
        else EventStore(os.environ.get("MF_EVENT_DB", "events.sqlite3"))
    )
    active_clock = clock if clock is not None else _default_clock
    validator = OrderValidator()

    app = FastAPI(
        title="titan-rail",
        version=__version__,
        description=(
            "Decision service for Make.com scenarios. Every response carries "
            "decision, reason, and evidence so error routes have something to act on."
        ),
    )

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(
            decision="HEALTHY",
            reason="service is up and answering",
            evidence=HealthEvidence(service="titan-rail", version=__version__),
        )

    @app.post("/map/shipping-method", response_model=MappingResponse)
    def map_shipping_method(request: MappingRequest) -> MappingResponse:
        # A null value from upstream is the same routing problem as an empty
        # one: it becomes an UNMAPPED decision, never a 422.
        value = request.value or ""
        outcome = active_mapper.map_value(value)
        return MappingResponse(
            decision=outcome.decision,
            reason=outcome.reason,
            method=(
                MappedMethod(
                    method_id=outcome.method.method_id,
                    name=outcome.method.name,
                    carrier=outcome.method.carrier,
                )
                if outcome.method
                else None
            ),
            evidence=MappingEvidence(
                input_value=value,
                normalized_value=outcome.normalized,
                ladder=[
                    LadderStep(rung=rung, matched=matched, detail=detail)  # type: ignore[arg-type]
                    for rung, matched, detail in outcome.steps
                ],
                candidates=[
                    MethodCandidate(
                        method_id=c.method.method_id,
                        name=c.method.name,
                        carrier=c.method.carrier,
                        score=round(c.score, 4),
                    )
                    for c in outcome.candidates
                ],
            ),
        )

    @app.post("/orders/validate", response_model=ValidationResponse)
    def validate_order(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> ValidationResponse:
        passed, gaps = validator.validate(payload)
        order_ref = payload.get("order_ref")
        if gaps:
            decision, reason = "INVALID", (
                f"{len(gaps)} gap(s) found, {len(passed)} check(s) passed; "
                "fix the gaps listed in evidence and resubmit"
            )
        else:
            decision, reason = "VALID", f"all {len(passed)} checks passed"
        return ValidationResponse(
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            evidence=ValidationEvidence(
                order_ref=order_ref if isinstance(order_ref, str) else None,
                passed=passed,
                gaps=gaps,
            ),
        )

    @app.post("/shipments/reconcile", response_model=ReconcileResponse)
    def reconcile_shipments(request: ReconcileRequest) -> ReconcileResponse:
        decision, reason, items = reconcile(request)
        return ReconcileResponse(
            decision=decision,
            reason=reason,
            evidence=ReconcileEvidence(
                order_ref=request.order.order_ref,
                tracking_numbers=[s.tracking_number for s in request.shipments],
                items=items,
            ),
        )

    # Demo sinks: the draft blueprints point their 3PL and ops modules here so
    # a scenario runs end to end against this one service. A production
    # scenario swaps these URLs for the real 3PL endpoint and alert channel.
    @app.post("/orders", response_model=OrderSinkResponse)
    def orders_sink(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> OrderSinkResponse:
        order_ref = body.get("order_ref")
        return OrderSinkResponse(
            decision="ACCEPTED",
            reason=(
                "demo 3PL sink accepted the order; point this module at the "
                "real 3PL endpoint in production"
            ),
            evidence=OrderSinkEvidence(
                order_ref=order_ref if isinstance(order_ref, str) else None,
                received_keys=sorted(body.keys()),
                received_utc=active_clock().isoformat(),
            ),
        )

    @app.post("/ops", response_model=OpsAlertResponse)
    def ops_sink(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> OpsAlertResponse:
        topic = body.get("topic")
        return OpsAlertResponse(
            decision="LOGGED",
            reason=(
                "demo ops sink logged the alert; point this module at the "
                "real alert channel in production"
            ),
            evidence=OpsAlertEvidence(
                topic=topic if isinstance(topic, str) else None,
                received_keys=sorted(body.keys()),
                received_utc=active_clock().isoformat(),
            ),
        )

    @app.post("/webhook/events", response_model=WebhookResponse)
    def webhook_events(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> WebhookResponse | JSONResponse:
        event_id = body.get("event_id")
        event_type = body.get("event_type")
        event_type = event_type if isinstance(event_type, str) else None

        rejection_gap: Gap | None = None
        rejection_reason = ""
        if not isinstance(event_id, str) or event_id.strip() == "":
            rejection_gap = Gap(
                field="event_id",
                problem=f"missing or not a non-empty string, got {event_id!r}",
                hint="send event_id as a string; stringify numeric ids upstream",
            )
            rejection_reason = (
                "event_id is required for deduplication; without it a retry "
                "storm becomes duplicate side effects"
            )
        elif len(event_id.strip()) > MAX_EVENT_ID_LENGTH:
            rejection_gap = Gap(
                field="event_id",
                problem=(
                    f"{len(event_id.strip())} characters exceeds the "
                    f"{MAX_EVENT_ID_LENGTH} character cap"
                ),
                hint=(
                    "an id this long usually means a whole payload was mapped "
                    "into event_id; send the provider's event id instead"
                ),
            )
            rejection_reason = (
                "event_id exceeds the length cap; refusing to use it as a "
                "dedup key"
            )

        if rejection_gap is not None:
            rejection = WebhookResponse(
                decision="REJECTED",
                reason=rejection_reason,
                idempotent=False,
                evidence=WebhookEvidence(
                    event_id=None,
                    event_type=event_type,
                    first_seen_utc=None,
                    gaps=[rejection_gap],
                ),
            )
            # 422 on purpose: a contract violation from the sender belongs on
            # Make's error route (with evaluate-all-states enabled) or on an
            # explicit REJECTED route in the scenario, as the draft tracking
            # blueprint does.
            return JSONResponse(status_code=422, content=rejection.model_dump())

        assert isinstance(event_id, str)
        inserted, first_seen = active_store.record(
            event_id.strip(), event_type, active_clock().isoformat()
        )
        if inserted:
            return WebhookResponse(
                decision="ACCEPTED",
                reason="first delivery of this event_id; safe to process side effects",
                idempotent=False,
                evidence=WebhookEvidence(
                    event_id=event_id.strip(),
                    event_type=event_type,
                    first_seen_utc=first_seen,
                ),
            )
        return WebhookResponse(
            decision="DUPLICATE",
            reason=(
                "replay of an event_id already processed; skip side effects, "
                "nothing is wrong"
            ),
            idempotent=True,
            evidence=WebhookEvidence(
                event_id=event_id.strip(),
                event_type=event_type,
                first_seen_utc=first_seen,
            ),
        )

    return app


app = create_app()
