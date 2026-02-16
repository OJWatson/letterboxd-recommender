from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from uuid import uuid4


@dataclass
class SessionState:
    recommended_slugs: set[str] = field(default_factory=set)


def _default_data_dir() -> Path:
    # Keep consistent with core.persist_ingest default.
    return Path(os.environ.get("LETTERBOXD_RECOMMENDER_DATA_DIR", "data")).resolve()


class SessionStore:
    """SQLite-backed session store.

    M3.4 used an in-memory store; M4.1 persists session state to disk so sessions
    survive process restarts.

    Stores a single piece of state per session:
      - recommended_slugs: set[str]

    The schema is intentionally tiny and uses standard library sqlite3.
    """

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        max_sessions: int = 4096,
        max_age_s: float = 60 * 60 * 24 * 30,  # 30 days
    ) -> None:
        self._max_sessions = max_sessions
        self._max_age_s = max_age_s
        base = _default_data_dir()
        default_db = db_path or (base / "sessions.sqlite3")
        self._db_path = Path(
            os.environ.get("LETTERBOXD_RECOMMENDER_SESSION_DB", str(default_db))
        ).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = Lock()
        # check_same_thread=False because TestClient may access across threads.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              recommended_slugs_json TEXT NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState]:
        with self._lock:
            if not session_id:
                session_id = uuid4().hex

            now = time.time()
            cur = self._conn.execute(
                "SELECT recommended_slugs_json FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                state = SessionState()
                self._conn.execute(
                    "INSERT OR REPLACE INTO sessions(" 
                    "session_id, recommended_slugs_json, updated_at) "
                    "VALUES (?, ?, ?)",
                    (session_id, json.dumps([]), now),
                )
                self._conn.commit()
                self._evict_if_needed(now)
                return session_id, state

            try:
                slugs = set(json.loads(row[0]))
            except Exception:
                slugs = set()
            state = SessionState(recommended_slugs=slugs)

            # Touch updated_at for LRU-ish eviction.
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            self._conn.commit()
            return session_id, state

    def save(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(" 
                "session_id, recommended_slugs_json, updated_at) "
                "VALUES (?, ?, ?)",
                (session_id, json.dumps(sorted(state.recommended_slugs)), now),
            )
            self._conn.commit()
            self._evict_if_needed(now)

    def _evict_if_needed(self, now: float) -> None:
        # Remove old sessions.
        cutoff = now - self._max_age_s
        self._conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))

        # Cap number of sessions. Remove least-recently-updated first.
        cur = self._conn.execute("SELECT COUNT(*) FROM sessions")
        (count,) = cur.fetchone() or (0,)
        if count <= self._max_sessions:
            self._conn.commit()
            return

        to_delete = count - self._max_sessions
        self._conn.execute(
            "DELETE FROM sessions WHERE session_id IN ("
            "SELECT session_id FROM sessions ORDER BY updated_at ASC LIMIT ?"
            ")",
            (to_delete,),
        )
        self._conn.commit()


def create_session_store() -> SessionStore:
    return SessionStore()
