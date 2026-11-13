"""API tests for POST /map/shipping-method against the default catalog."""

from __future__ import annotations

from fastapi.testclient import TestClient

PATH = "/map/shipping-method"


def test_exact_id_maps(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "SM-STD-01"}).json()
    assert body["decision"] == "MAPPED_EXACT"
    assert body["method"]["method_id"] == "SM-STD-01"


def test_exact_id_is_case_insensitive(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "sm-exp-02"}).json()
    assert body["decision"] == "MAPPED_EXACT"
    assert body["method"]["method_id"] == "SM-EXP-02"


def test_alias_maps(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "express"}).json()
    assert body["decision"] == "MAPPED_ALIAS"
    assert body["method"]["method_id"] == "SM-EXP-02"


def test_alias_survives_case_and_punctuation_noise(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "  Click & Collect! "}).json()
    assert body["decision"] == "MAPPED_ALIAS"
    assert body["method"]["method_id"] == "SM-PUP-05"


def test_typo_maps_via_fuzzy_with_score(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "Standrd Ground"}).json()
    assert body["decision"] == "MAPPED_FUZZY"
    assert body["method"]["method_id"] == "SM-STD-01"
    fuzzy_steps = [s for s in body["evidence"]["ladder"] if s["rung"] == "fuzzy"]
    assert fuzzy_steps and fuzzy_steps[0]["matched"] is True


def test_gibberish_is_unmapped_never_guessed(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "zzqx teleport overnight"}).json()
    assert body["decision"] == "UNMAPPED"
    assert body["method"] is None


def test_empty_value_is_a_decision_not_a_500(client: TestClient) -> None:
    response = client.post(PATH, json={"value": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "UNMAPPED"
    assert "empty" in body["reason"]


def test_punctuation_only_value_is_unmapped(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "  --- !!! "}).json()
    assert body["decision"] == "UNMAPPED"
    assert body["evidence"]["normalized_value"] == ""


def test_missing_value_field_is_tolerated(client: TestClient) -> None:
    response = client.post(PATH, json={})
    assert response.status_code == 200
    assert response.json()["decision"] == "UNMAPPED"


def test_null_value_is_a_decision_not_a_422(client: TestClient) -> None:
    response = client.post(PATH, json={"value": None})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "UNMAPPED"
    assert "empty" in body["reason"]


def test_near_miss_returns_ranked_candidates(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "parcel"}).json()
    assert body["decision"] == "UNMAPPED"
    candidates = body["evidence"]["candidates"]
    assert candidates, "a near-miss should surface candidates for human review"
    assert candidates[0]["method_id"] == "SM-ECO-03"


def test_unmapped_evidence_shows_all_three_rungs(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "zzqx teleport overnight"}).json()
    rungs = [s["rung"] for s in body["evidence"]["ladder"]]
    assert rungs == ["exact_id", "alias", "fuzzy"]
    assert all(s["matched"] is False for s in body["evidence"]["ladder"])


def test_mapped_response_carries_carrier(client: TestClient) -> None:
    body = client.post(PATH, json={"value": "economy"}).json()
    assert body["method"]["carrier"] == "Marlin Post"
    assert body["method"]["name"] == "Economy Parcel"
