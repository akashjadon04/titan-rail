"""API tests for POST /shipments/reconcile: per-item accounting."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from .conftest import FIXTURES

PATH = "/shipments/reconcile"


def request_body(
    order_lines: list[dict[str, Any]],
    shipments: list[dict[str, Any]],
    backorders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "order": {"order_ref": "AHG-2026-0500", "lines": order_lines},
        "shipments": shipments,
        "backorders": backorders or [],
    }


def shipment(lines: list[dict[str, Any]], tracking: str = "MP-0001") -> dict[str, Any]:
    return {"tracking_number": tracking, "lines": lines}


def items_by_sku(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["sku"]: item for item in body["evidence"]["items"]}


def test_full_shipment_is_fulfilled(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 2}],
            [shipment([{"sku": "A", "quantity": 2}])],
        ),
    ).json()
    assert body["decision"] == "FULFILLED"
    assert items_by_sku(body)["A"]["status"] == "ok"


def test_split_across_shipments_sums_to_fulfilled(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 5}],
            [
                shipment([{"sku": "A", "quantity": 2}], "MP-0001"),
                shipment([{"sku": "A", "quantity": 3}], "MP-0002"),
            ],
        ),
    ).json()
    assert body["decision"] == "FULFILLED"
    assert body["evidence"]["tracking_numbers"] == ["MP-0001", "MP-0002"]


def test_short_item_makes_it_partial(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 4}, {"sku": "B", "quantity": 1}],
            [shipment([{"sku": "A", "quantity": 4}])],
        ),
    ).json()
    assert body["decision"] == "PARTIAL"
    items = items_by_sku(body)
    assert items["A"]["status"] == "ok"
    assert items["B"]["status"] == "short"


def test_no_shipments_at_all_is_partial_not_a_crash(client: TestClient) -> None:
    response = client.post(
        PATH, json=request_body([{"sku": "A", "quantity": 2}], [])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "PARTIAL"
    assert "no shipment lines received" in body["reason"]


def test_backorder_covering_remainder_is_backorder(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 3}],
            [shipment([{"sku": "A", "quantity": 1}])],
            [{"sku": "A", "quantity": 2, "eta": "2026-08-15"}],
        ),
    ).json()
    assert body["decision"] == "BACKORDER"
    assert items_by_sku(body)["A"]["status"] == "backordered"


def test_backorder_not_covering_everything_stays_partial(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 5}],
            [shipment([{"sku": "A", "quantity": 1}])],
            [{"sku": "A", "quantity": 2}],
        ),
    ).json()
    assert body["decision"] == "PARTIAL"
    assert items_by_sku(body)["A"]["status"] == "short"


def test_overshipment_is_mismatch(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 2}],
            [shipment([{"sku": "A", "quantity": 5}])],
        ),
    ).json()
    assert body["decision"] == "MISMATCH"
    item = items_by_sku(body)["A"]
    assert item["status"] == "over"
    assert "3 unit(s) too many" in item["note"]


def test_unknown_sku_is_mismatch(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 1}],
            [
                shipment(
                    [{"sku": "A", "quantity": 1}, {"sku": "GHOST", "quantity": 1}]
                )
            ],
        ),
    ).json()
    assert body["decision"] == "MISMATCH"
    assert items_by_sku(body)["GHOST"]["status"] == "unknown_sku"


def test_mismatch_wins_over_backorder(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 3}, {"sku": "B", "quantity": 1}],
            [shipment([{"sku": "B", "quantity": 4}])],
            [{"sku": "A", "quantity": 3}],
        ),
    ).json()
    assert body["decision"] == "MISMATCH"


def test_duplicate_order_lines_are_aggregated(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 1}, {"sku": "A", "quantity": 2}],
            [shipment([{"sku": "A", "quantity": 3}])],
        ),
    ).json()
    assert body["decision"] == "FULFILLED"
    assert items_by_sku(body)["A"]["ordered"] == 3


def test_item_evidence_carries_the_numbers(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 4}],
            [shipment([{"sku": "A", "quantity": 1}])],
            [{"sku": "A", "quantity": 3}],
        ),
    ).json()
    item = items_by_sku(body)["A"]
    assert (item["ordered"], item["shipped"], item["backordered"]) == (4, 1, 3)


def test_zero_quantity_order_line_is_known_not_unknown(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 0}, {"sku": "B", "quantity": 2}],
            [shipment([{"sku": "B", "quantity": 2}])],
        ),
    ).json()
    assert body["decision"] == "FULFILLED"
    item = items_by_sku(body)["A"]
    assert item["status"] == "ok"
    assert "zero ordered, zero shipped" in item["note"]


def test_zero_quantity_line_shipped_anyway_is_mismatch(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 0}],
            [shipment([{"sku": "A", "quantity": 3}])],
        ),
    ).json()
    assert body["decision"] == "MISMATCH"
    item = items_by_sku(body)["A"]
    assert item["status"] == "over"
    assert "3 unit(s) too many" in item["note"]


def test_unknown_sku_only_when_absent_from_order_lines(client: TestClient) -> None:
    body = client.post(
        PATH,
        json=request_body(
            [{"sku": "A", "quantity": 0}],
            [shipment([{"sku": "GHOST", "quantity": 1}])],
        ),
    ).json()
    items = items_by_sku(body)
    assert items["GHOST"]["status"] == "unknown_sku"
    assert items["A"]["status"] == "ok"


def test_empty_order_and_no_shipments_is_trivially_fulfilled(client: TestClient) -> None:
    body = client.post(PATH, json=request_body([], [])).json()
    assert body["decision"] == "FULFILLED"
    assert "nothing to reconcile" in body["reason"]


def test_fixture_partial(client: TestClient) -> None:
    payload = json.loads(
        (FIXTURES / "shipments" / "reconcile_partial.json").read_text()
    )
    body = client.post(PATH, json=payload).json()
    assert body["decision"] == "PARTIAL"
    assert items_by_sku(body)["AHG-THROW-GRY"]["status"] == "short"


def test_fixture_backorder(client: TestClient) -> None:
    payload = json.loads(
        (FIXTURES / "shipments" / "reconcile_backorder.json").read_text()
    )
    assert client.post(PATH, json=payload).json()["decision"] == "BACKORDER"


def test_fixture_mismatch(client: TestClient) -> None:
    payload = json.loads(
        (FIXTURES / "shipments" / "reconcile_mismatch.json").read_text()
    )
    body = client.post(PATH, json=payload).json()
    assert body["decision"] == "MISMATCH"
    statuses = {item["status"] for item in body["evidence"]["items"]}
    assert {"over", "unknown_sku"} <= statuses
