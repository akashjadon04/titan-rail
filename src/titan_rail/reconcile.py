"""Shipment reconciliation: tracking data versus what the order asked for.

3PLs ship partially, promise backorders, and occasionally ship the wrong
thing. Instead of letting the scenario mark an order as done because a
tracking number exists, this module does per-sku accounting and returns one
of four decisions with per-item evidence:

  FULFILLED  every ordered quantity shipped in full
  BACKORDER  every missing quantity is covered by an explicit backorder notice
  PARTIAL    something is missing and no notice covers it
  MISMATCH   over-shipment or an sku that was never ordered; needs a human

MISMATCH always wins over the others: a wrong shipment updating the ERP as
"partially delivered" is exactly the silent failure this service exists to stop.
"""

from __future__ import annotations

from collections import defaultdict

from .models import (
    ItemEvidence,
    ReconcileDecision,
    ReconcileRequest,
)


def reconcile(request: ReconcileRequest) -> tuple[ReconcileDecision, str, list[ItemEvidence]]:
    """Return (decision, reason, per-item evidence) for an order vs its shipments."""

    # Skus named on the order are tracked separately from their quantities:
    # a line ordered with quantity 0 is still a known sku, not an unknown one.
    order_skus: set[str] = {line.sku for line in request.order.lines}
    ordered: dict[str, int] = defaultdict(int)
    for line in request.order.lines:
        ordered[line.sku] += line.quantity

    shipped: dict[str, int] = defaultdict(int)
    for shipment in request.shipments:
        for line in shipment.lines:
            shipped[line.sku] += line.quantity

    backordered: dict[str, int] = defaultdict(int)
    for notice in request.backorders:
        backordered[notice.sku] += notice.quantity

    items: list[ItemEvidence] = []
    counts = {"ok": 0, "short": 0, "over": 0, "unknown_sku": 0, "backordered": 0}

    all_skus = sorted(set(ordered) | set(shipped) | set(backordered))
    for sku in all_skus:
        o, s, b = ordered.get(sku, 0), shipped.get(sku, 0), backordered.get(sku, 0)

        if sku not in order_skus:
            status, note = "unknown_sku", (
                f"{s} unit(s) shipped or {b} backordered for an sku the order never had"
            )
        elif o == 0 and s == 0:
            status, note = "ok", "zero ordered, zero shipped"
        elif s > o:
            status, note = "over", f"shipped {s} against {o} ordered; {s - o} unit(s) too many"
        elif s == o:
            status, note = "ok", f"shipped {s} of {o}"
        else:
            remaining = o - s
            if b >= remaining:
                status, note = "backordered", (
                    f"shipped {s} of {o}; remaining {remaining} covered by backorder notice"
                )
            else:
                status, note = "short", (
                    f"shipped {s} of {o}; {remaining} missing, backorder covers only {b}"
                )

        counts[status] += 1
        items.append(
            ItemEvidence(
                sku=sku,
                ordered=o,
                shipped=s,
                backordered=b,
                status=status,  # type: ignore[arg-type]
                note=note,
            )
        )

    n_shipments = len(request.shipments)

    if counts["unknown_sku"] or counts["over"]:
        decision: ReconcileDecision = "MISMATCH"
        reason = (
            f"{counts['over']} item(s) over-shipped, {counts['unknown_sku']} unknown "
            "sku(s); hold the ERP update and route to a human"
        )
    elif counts["short"]:
        decision = "PARTIAL"
        if n_shipments == 0:
            reason = (
                f"no shipment lines received; all {counts['short']} item(s) remain open"
            )
        else:
            reason = (
                f"{counts['short']} of {len(items)} item(s) short with no backorder "
                "notice covering them"
            )
    elif counts["backordered"]:
        decision = "BACKORDER"
        reason = (
            f"{counts['backordered']} item(s) pending, every missing quantity covered "
            "by an explicit backorder notice"
        )
    else:
        decision = "FULFILLED"
        if not items:
            reason = "order has no lines and no shipment lines; nothing to reconcile"
        else:
            reason = (
                f"all {len(items)} item(s) shipped in full across "
                f"{n_shipments} shipment(s)"
            )

    return decision, reason, items
