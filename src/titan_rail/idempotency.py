"""SQLite-backed idempotency store for webhook deliveries.

Make retries webhook deliveries, and so do most 3PL platforms. Deduplication
has to be atomic: two concurrent deliveries of the same event_id must resolve
to exactly one ACCEPTED. The primary key constraint does the arbitration, so
this works across processes as well as threads. A connection is opened per
operation; at webhook rates the simplicity is worth far more than pooling.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    first_seen_utc TEXT NOT NULL
)
"""


class EventStore:
    """Records webhook event ids exactly once, keyed on event_id."""

    def __init__(self, db_path: str | Path) -> None:
        # Schema creation is lazy (first record call), so building the app
        # never touches disk. Matters for tests and for import-time safety.
        self._db_path = str(db_path)

    def record(self, event_id: str, event_type: str | None, seen_at_utc: str) -> tuple[bool, str]:
        """Insert the event if unseen.

        Returns ``(inserted, first_seen_utc)``. ``inserted`` is False on a
        replay, and ``first_seen_utc`` is always the timestamp of the FIRST
        delivery, which is the evidence a replay response carries.
        """

        with self._connect() as conn:
            conn.execute(_SCHEMA)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO events (event_id, event_type, first_seen_utc) "
                "VALUES (?, ?, ?)",
                (event_id, event_type, seen_at_utc),
            )
            inserted = cursor.rowcount == 1
            row = conn.execute(
                "SELECT first_seen_utc FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return inserted, str(row[0])

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)
