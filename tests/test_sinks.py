from __future__ import annotations

from fastapi.testclient import TestClient


def test_orders_sink_accepts_and_echoes_the_ref(client: TestClient) -> None:
    response = client.post(
        "/orders",
        json={"order_ref": "AH-2031", "shipping_method_id": "SM-STD-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ACCEPTED"
    assert body["evidence"]["order_ref"] == "AH-2031"
    assert body["evidence"]["received_keys"] == ["order_ref", "shipping_method_id"]


def test_orders_sink_tolerates_an_empty_body(client: TestClient) -> None:
    body = client.post("/orders", json={}).json()
    assert body["decision"] == "ACCEPTED"
    assert body["evidence"]["order_ref"] is None
    assert body["evidence"]["received_keys"] == []


def test_ops_sink_logs_the_alert(client: TestClient) -> None:
    response = client.post(
        "/ops",
        json={"topic": "order-invalid", "order_ref": "AH-2031"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "LOGGED"
    assert body["evidence"]["topic"] == "order-invalid"


def test_sinks_carry_the_envelope(client: TestClient) -> None:
    for path in ("/orders", "/ops"):
        body = client.post(path, json={}).json()
        assert set(body) >= {"decision", "reason", "evidence"}
        assert "received_utc" in body["evidence"]
