"""Shared fixtures: every test runs against an app built with injected seams.

No network, no shared sqlite file, no wall clock. The event store lives in
tmp_path and the clock is a deterministic fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from titan_rail.app import create_app
from titan_rail.idempotency import EventStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeClock:
    """Deterministic clock; each call advances by one second."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.now
        self.now = self.now + timedelta(seconds=1)
        return current


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "events.sqlite3"


@pytest.fixture
def client(db_path: Path, fake_clock: FakeClock) -> TestClient:
    app = create_app(store=EventStore(db_path), clock=fake_clock)
    return TestClient(app)
