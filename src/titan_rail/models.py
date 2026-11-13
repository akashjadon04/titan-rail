"""Typed request and response models for the decision service.

Every response shares the same envelope: ``decision``, ``reason``,
``evidence``. The decision is machine-routable (Make filters branch on it),
the reason is human-readable, and the evidence is built while the decision
is made, not reconstructed after the fact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MappingDecision = Literal["MAPPED_EXACT", "MAPPED_ALIAS", "MAPPED_FUZZY", "UNMAPPED"]
ValidationDecision = Literal["VALID", "INVALID"]
ReconcileDecision = Literal["FULFILLED", "PARTIAL", "BACKORDER", "MISMATCH"]
WebhookDecision = Literal["ACCEPTED", "DUPLICATE", "REJECTED"]
ItemStatus = Literal["ok", "short", "over", "unknown_sku", "backordered"]
LadderRung = Literal["exact_id", "alias", "fuzzy"]


# ---------------------------------------------------------------------------
# /map/shipping-method
# ---------------------------------------------------------------------------


class MappingRequest(BaseModel):
    """Raw shipping method value as it left the source system.

    ``value`` accepts null and defaults to an empty string on purpose: a
    missing or null field in the upstream payload should produce an UNMAPPED
    decision the scenario can route, not a 422 that kills the run.
    """

    value: str | None = ""


class LadderStep(BaseModel):
    """One rung of the mapping ladder and what happened on it."""

    rung: LadderRung
    matched: bool
    detail: str


class MethodCandidate(BaseModel):
    """A near-miss returned for human review instead of being guessed."""

    method_id: str
    name: str
    carrier: str
    score: float


class MappedMethod(BaseModel):
    method_id: str
    name: str
    carrier: str


class MappingEvidence(BaseModel):
    input_value: str
    normalized_value: str
    ladder: list[LadderStep]
    candidates: list[MethodCandidate]


class MappingResponse(BaseModel):
    decision: MappingDecision
    reason: str
    evidence: MappingEvidence
    method: MappedMethod | None = None


# ---------------------------------------------------------------------------
# /orders/validate
# ---------------------------------------------------------------------------


class Gap(BaseModel):
    """One actionable problem in an order payload."""

    field: str
    problem: str
    hint: str


class ValidationEvidence(BaseModel):
    order_ref: str | None
    passed: list[str]
    gaps: list[Gap]


class ValidationResponse(BaseModel):
    decision: ValidationDecision
    reason: str
    evidence: ValidationEvidence


# ---------------------------------------------------------------------------
# /shipments/reconcile
# ---------------------------------------------------------------------------


class OrderLine(BaseModel):
    sku: str
    quantity: int = Field(ge=0)


class OrderPayload(BaseModel):
    order_ref: str
    lines: list[OrderLine] = Field(default_factory=list)


class ShipmentLine(BaseModel):
    sku: str
    quantity: int = Field(ge=0)


class ShipmentPayload(BaseModel):
    tracking_number: str
    carrier: str | None = None
    lines: list[ShipmentLine] = Field(default_factory=list)


class BackorderNotice(BaseModel):
    sku: str
    quantity: int = Field(ge=0)
    eta: str | None = None


class ReconcileRequest(BaseModel):
    order: OrderPayload
    shipments: list[ShipmentPayload] = Field(default_factory=list)
    backorders: list[BackorderNotice] = Field(default_factory=list)


class ItemEvidence(BaseModel):
    """Per-sku accounting: what was ordered, shipped, promised, and the verdict."""

    sku: str
    ordered: int
    shipped: int
    backordered: int
    status: ItemStatus
    note: str


class ReconcileEvidence(BaseModel):
    order_ref: str
    tracking_numbers: list[str]
    items: list[ItemEvidence]


class ReconcileResponse(BaseModel):
    decision: ReconcileDecision
    reason: str
    evidence: ReconcileEvidence


# ---------------------------------------------------------------------------
# /webhook/events
# ---------------------------------------------------------------------------


class WebhookEvidence(BaseModel):
    event_id: str | None
    event_type: str | None
    first_seen_utc: str | None
    gaps: list[Gap] = Field(default_factory=list)


class WebhookResponse(BaseModel):
    decision: WebhookDecision
    reason: str
    evidence: WebhookEvidence
    idempotent: bool


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


class HealthEvidence(BaseModel):
    service: str
    version: str


class HealthResponse(BaseModel):
    decision: Literal["HEALTHY"]
    reason: str
    evidence: HealthEvidence


# ---------------------------------------------------------------------------
# Demo sinks: /orders and /ops
# ---------------------------------------------------------------------------


class OrderSinkEvidence(BaseModel):
    order_ref: str | None
    received_keys: list[str]
    received_utc: str


class OrderSinkResponse(BaseModel):
    decision: Literal["ACCEPTED"]
    reason: str
    evidence: OrderSinkEvidence


class OpsAlertEvidence(BaseModel):
    topic: str | None
    received_keys: list[str]
    received_utc: str


class OpsAlertResponse(BaseModel):
    decision: Literal["LOGGED"]
    reason: str
    evidence: OpsAlertEvidence
