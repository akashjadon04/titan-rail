from __future__ import annotations

from fastapi.testclient import TestClient

from titan_rail import __version__


def test_healthz_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["decision"] == "HEALTHY"


def test_healthz_reports_version(client: TestClient) -> None:
    evidence = client.get("/healthz").json()["evidence"]
    assert evidence["service"] == "titan-rail"
    assert evidence["version"] == __version__
