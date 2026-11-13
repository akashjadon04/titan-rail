"""Every endpoint answers with the same decision/reason/evidence envelope."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

CASES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("get", "/healthz", None),
    ("post", "/map/shipping-method", {"value": "standard"}),
    ("post", "/orders/validate", {}),
    ("post", "/shipments/reconcile", {"order": {"order_ref": "X-1", "lines": []}}),
    ("post", "/webhook/events", {"event_id": "evt-envelope-1"}),
]


@pytest.mark.parametrize("method,path,payload", CASES, ids=[c[1] for c in CASES])
def test_envelope_present(
    client: TestClient, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    response = (
        client.get(path) if method == "get" else client.post(path, json=payload)
    )
    assert response.status_code == 200
    body = response.json()
    for key in ("decision", "reason", "evidence"):
        assert key in body, f"{path} response is missing '{key}'"
    assert isinstance(body["reason"], str) and body["reason"]
