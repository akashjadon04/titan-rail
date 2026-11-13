"""API tests for POST /webhook/events: idempotency under replay."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from titan_rail.app import create_app
from titan_rail.idempotency import EventStore

from .conftest import FIXTURES, FakeClock

PATH = "/webhook/events"


def test_first_delivery_is_accepted(client: TestClient) -> None:
    response = client.post(PATH, json={"event_id": "evt-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ACCEPTED"
    assert body["idempotent"] is False


def test_replay_is_duplicate_and_idempotent(client: TestClient) -> None:
    client.post(PATH, json={"event_id": "evt-2"})
    body = client.post(PATH, json={"event_id": "evt-2"}).json()
    assert body["decision"] == "DUPLICATE"
    assert body["idempotent"] is True


def test_replay_keeps_the_first_seen_timestamp(client: TestClient) -> None:
    first = client.post(PATH, json={"event_id": "evt-3"}).json()
    replay = client.post(PATH, json={"event_id": "evt-3"}).json()
    assert replay["evidence"]["first_seen_utc"] == first["evidence"]["first_seen_utc"]


def test_injected_clock_stamps_first_seen(client: TestClient) -> None:
    body = client.post(PATH, json={"event_id": "evt-clock"}).json()
    assert body["evidence"]["first_seen_utc"] == "2026-01-15T12:00:00+00:00"


def test_distinct_event_ids_are_independent(client: TestClient) -> None:
    a = client.post(PATH, json={"event_id": "evt-a"}).json()
    b = client.post(PATH, json={"event_id": "evt-b"}).json()
    assert a["decision"] == b["decision"] == "ACCEPTED"


def test_many_replays_stay_idempotent(client: TestClient) -> None:
    client.post(PATH, json={"event_id": "evt-storm"})
    for _ in range(5):
        body = client.post(PATH, json={"event_id": "evt-storm"}).json()
        assert body["idempotent"] is True


def test_missing_event_id_is_rejected_with_evidence(client: TestClient) -> None:
    response = client.post(PATH, json={"event_type": "shipment.dispatched"})
    assert response.status_code == 422
    body = response.json()
    assert body["decision"] == "REJECTED"
    assert body["evidence"]["gaps"][0]["field"] == "event_id"


def test_empty_event_id_is_rejected(client: TestClient) -> None:
    assert client.post(PATH, json={"event_id": "   "}).status_code == 422


def test_numeric_event_id_is_rejected_with_a_hint(client: TestClient) -> None:
    response = client.post(PATH, json={"event_id": 12345})
    assert response.status_code == 422
    hint = response.json()["evidence"]["gaps"][0]["hint"]
    assert "string" in hint


def test_overlong_event_id_is_rejected(client: TestClient) -> None:
    response = client.post(PATH, json={"event_id": "x" * 600})
    assert response.status_code == 422
    body = response.json()
    assert body["decision"] == "REJECTED"
    assert "512" in body["evidence"]["gaps"][0]["problem"]


def test_event_id_at_the_cap_is_accepted(client: TestClient) -> None:
    response = client.post(PATH, json={"event_id": "x" * 512})
    assert response.status_code == 200
    assert response.json()["decision"] == "ACCEPTED"


def test_event_type_is_echoed_in_evidence(client: TestClient) -> None:
    body = client.post(
        PATH, json={"event_id": "evt-4", "event_type": "shipment.dispatched"}
    ).json()
    assert body["evidence"]["event_type"] == "shipment.dispatched"


def test_dedup_survives_an_app_restart(db_path: Path) -> None:
    clock = FakeClock()
    first_app = TestClient(create_app(store=EventStore(db_path), clock=clock))
    assert (
        first_app.post(PATH, json={"event_id": "evt-restart"}).json()["decision"]
        == "ACCEPTED"
    )

    restarted = TestClient(create_app(store=EventStore(db_path), clock=clock))
    body = restarted.post(PATH, json={"event_id": "evt-restart"}).json()
    assert body["decision"] == "DUPLICATE"
    assert body["idempotent"] is True


def test_fixture_tracking_event_roundtrip(client: TestClient) -> None:
    payload = json.loads(
        (FIXTURES / "webhooks" / "tracking_event.json").read_text()
    )
    first = client.post(PATH, json=payload).json()
    replay = client.post(PATH, json=payload).json()
    assert first["decision"] == "ACCEPTED"
    assert replay["decision"] == "DUPLICATE"
