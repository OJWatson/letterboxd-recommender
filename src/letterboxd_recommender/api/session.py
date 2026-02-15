from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4


@dataclass
class SessionState:
    recommended_slugs: set[str] = field(default_factory=set)


class SessionStore:
    """In-memory session store.

    This intentionally keeps things simple for M3.4: session state is held in-process
    and is not persisted across restarts.
    """

    def __init__(self, *, max_sessions: int = 1024) -> None:
        self._max_sessions = max_sessions
        self._lock = Lock()
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState]:
        with self._lock:
            if not session_id:
                session_id = uuid4().hex

            state = self._sessions.get(session_id)
            if state is None:
                if len(self._sessions) >= self._max_sessions:
                    # Best-effort eviction: drop an arbitrary session to cap memory.
                    self._sessions.pop(next(iter(self._sessions)))
                state = SessionState()
                self._sessions[session_id] = state

            return session_id, state


# Module-level store shared by API routes.
SESSION_STORE = SessionStore()
