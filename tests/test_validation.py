"""API tests for POST /orders/validate: gaps, never exceptions."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from .conftest import FIXTURES

PATH = "/orders/validate"


def valid_order() -> dict[str, Any]:
    return {
        "order_ref": "AHG-2026-0999",
        "customer": {"name": "Dana Whitfield", "email": "dana@example.com"},
        "shipping_address": {
            "line1": "18 Alder Row",
            "city": "Springfield",
            "postal_code": "04932",
            "country_code": "US",
        },
        "shipping_method": "SM-STD-01",
        "lines": [{"sku": "AHG-MUG-BLUE", "quantity": 2}],
    }


def gap_fields(body: dict[str, Any]) -> set[str]:
    return {g["field"] for g in body["evidence"]["gaps"]}


def test_valid_order_passes(client: TestClient) -> None:
    body = client.post(PATH, json=valid_order()).json()
    assert body["decision"] == "VALID"
    assert body["evidence"]["gaps"] == []


def test_empty_payload_lists_every_top_level_gap(client: TestClient) -> None:
    response = client.post(PATH, json={})
    assert response.status_code == 200, "shape problems are gaps, not HTTP errors"
    body = response.json()
    assert body["decision"] == "INVALID"
    assert {
        "order_ref",
        "customer",
        "shipping_address",
        "shipping_method",
        "lines",
    } <= gap_fields(body)


def test_missing_email_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    del order["customer"]["email"]
    body = client.post(PATH, json=order).json()
    assert body["decision"] == "INVALID"
    assert "customer.email" in gap_fields(body)


def test_implausible_email_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["customer"]["email"] = "not-an-email"
    assert "customer.email" in gap_fields(client.post(PATH, json=order).json())


def test_empty_lines_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["lines"] = []
    body = client.post(PATH, json=order).json()
    assert body["decision"] == "INVALID"
    assert "lines" in gap_fields(body)


def test_line_missing_sku_points_at_the_line(client: TestClient) -> None:
    order = valid_order()
    order["lines"] = [{"quantity": 2}]
    assert "lines[0].sku" in gap_fields(client.post(PATH, json=order).json())


def test_zero_quantity_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["lines"][0]["quantity"] = 0
    assert "lines[0].quantity" in gap_fields(client.post(PATH, json=order).json())


def test_negative_quantity_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["lines"][0]["quantity"] = -3
    assert "lines[0].quantity" in gap_fields(client.post(PATH, json=order).json())


def test_string_quantity_is_not_silently_coerced(client: TestClient) -> None:
    order = valid_order()
    order["lines"][0]["quantity"] = "2"
    body = client.post(PATH, json=order).json()
    assert "lines[0].quantity" in gap_fields(body)


def test_boolean_quantity_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["lines"][0]["quantity"] = True
    assert "lines[0].quantity" in gap_fields(client.post(PATH, json=order).json())


def test_three_letter_country_code_is_a_gap(client: TestClient) -> None:
    order = valid_order()
    order["shipping_address"]["country_code"] = "BRA"
    assert "shipping_address.country_code" in gap_fields(
        client.post(PATH, json=order).json()
    )


def test_lines_as_object_is_a_gap_not_a_crash(client: TestClient) -> None:
    order = valid_order()
    order["lines"] = {"sku": "AHG-MUG-BLUE"}
    response = client.post(PATH, json=order)
    assert response.status_code == 200
    assert "lines" in gap_fields(response.json())


def test_unknown_extra_fields_are_tolerated(client: TestClient) -> None:
    order = valid_order()
    order["erp_internal_flag"] = {"whatever": 1}
    assert client.post(PATH, json=order).json()["decision"] == "VALID"


def test_every_gap_carries_a_hint(client: TestClient) -> None:
    body = client.post(PATH, json={}).json()
    assert body["evidence"]["gaps"], "expected gaps for an empty payload"
    for gap in body["evidence"]["gaps"]:
        assert gap["hint"].strip()


def test_passed_checks_are_reported(client: TestClient) -> None:
    body = client.post(PATH, json=valid_order()).json()
    assert "order_ref" in body["evidence"]["passed"]
    assert "customer.email" in body["evidence"]["passed"]


def test_fixture_order_ok_is_valid(client: TestClient) -> None:
    payload = json.loads((FIXTURES / "orders" / "order_ok.json").read_text())
    assert client.post(PATH, json=payload).json()["decision"] == "VALID"


def test_fixture_order_missing_fields_reports_expected_gaps(client: TestClient) -> None:
    payload = json.loads(
        (FIXTURES / "orders" / "order_missing_fields.json").read_text()
    )
    body = client.post(PATH, json=payload).json()
    assert body["decision"] == "INVALID"
    assert {
        "customer.email",
        "shipping_address.postal_code",
        "shipping_address.country_code",
        "shipping_method",
        "lines[0].quantity",
        "lines[1].sku",
        "lines[1].quantity",
    } <= gap_fields(body)
