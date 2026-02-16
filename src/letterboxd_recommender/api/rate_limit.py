from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


@dataclass
class _Window:
    hits: deque[float]


class SlidingWindowRateLimiter:
    """Very small in-process rate limiter.

    This is not intended to be perfect. It provides basic protection against
    accidental abuse (esp. ingesting / scraping Letterboxd too aggressively).

    Keys are derived from client IP + a logical bucket.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: dict[str, _Window] = {}

    def allow(self, *, key: str, limit: int, window_s: float) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - window_s
        with self._lock:
            w = self._windows.get(key)
            if w is None:
                w = _Window(hits=deque())
                self._windows[key] = w

            while w.hits and w.hits[0] < cutoff:
                w.hits.popleft()

            if len(w.hits) >= limit:
                remaining = 0
                return False, remaining

            w.hits.append(now)
            remaining = max(0, limit - len(w.hits))
            return True, remaining


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limiter: SlidingWindowRateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or SlidingWindowRateLimiter()

        # Defaults can be tuned via env vars (useful for tests/deploy).
        self._global_limit = int(os.environ.get("LETTERBOXD_RECOMMENDER_RL_GLOBAL", "60"))
        self._global_window_s = float(
            os.environ.get("LETTERBOXD_RECOMMENDER_RL_GLOBAL_WINDOW_S", "60")
        )

        self._ingest_limit = int(os.environ.get("LETTERBOXD_RECOMMENDER_RL_INGEST", "5"))
        self._ingest_window_s = float(
            os.environ.get("LETTERBOXD_RECOMMENDER_RL_INGEST_WINDOW_S", "60")
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = request.client.host if request.client else "unknown"

        ok, _remaining = self._limiter.allow(
            key=f"{client_ip}:global", limit=self._global_limit, window_s=self._global_window_s
        )
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        if request.url.path.endswith("/ingest"):
            ok, _remaining = self._limiter.allow(
                key=f"{client_ip}:ingest", limit=self._ingest_limit, window_s=self._ingest_window_s
            )
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                )

        return await call_next(request)
