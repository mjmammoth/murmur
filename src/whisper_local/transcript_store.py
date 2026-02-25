from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class TranscriptRecord:
    id: int
    text: str
    timestamp: str
    created_at: str

    def to_message(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "text": self.text,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
        }


class TranscriptStore:
    def __init__(self, path: Path, *, max_entries: int = 5000) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max(1, int(max_entries))
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcripts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_transcripts_created_at ON transcripts(created_at)"
                )
                conn.commit()

    def append(self, text: str, *, timestamp: str | None = None) -> TranscriptRecord:
        timestamp_value = timestamp or datetime.now().strftime("%H:%M:%S")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO transcripts(text, timestamp, created_at) VALUES (?, ?, ?)",
                    (text, timestamp_value, created_at),
                )
                raw_row_id = cursor.lastrowid
                if raw_row_id is None:
                    raise RuntimeError("Failed to persist transcript row id")
                record_id = int(raw_row_id)
                self._prune_locked(conn)
                conn.commit()
        return TranscriptRecord(
            id=record_id,
            text=text,
            timestamp=timestamp_value,
            created_at=created_at,
        )

    def history(self, *, limit: int | None = None) -> list[TranscriptRecord]:
        query = "SELECT id, text, timestamp, created_at FROM transcripts ORDER BY id ASC"
        params: tuple[int, ...] = ()
        if limit is not None:
            capped = max(1, int(limit))
            query = (
                "SELECT id, text, timestamp, created_at "
                "FROM transcripts ORDER BY id DESC LIMIT ?"
            )
            params = (capped,)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        return [
            TranscriptRecord(
                id=int(row[0]),
                text=str(row[1]),
                timestamp=str(row[2]),
                created_at=str(row[3]),
            )
            for row in rows
        ]

    def _prune_locked(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM transcripts
            WHERE id IN (
                SELECT id
                FROM transcripts
                ORDER BY id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self.max_entries,),
        )

    def prune(self) -> None:
        with self._lock:
            with self._connect() as conn:
                self._prune_locked(conn)
                conn.commit()
