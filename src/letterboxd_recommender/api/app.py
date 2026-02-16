from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from letterboxd_recommender.api.rate_limit import RateLimitMiddleware
from letterboxd_recommender.api.routes import router
from letterboxd_recommender.api.session import create_session_store


def _parse_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []

    # Support both comma-separated values and newline-separated values (common in PaaS).
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def create_app() -> FastAPI:
    app = FastAPI(title="Letterboxd Habit Recommender", version="0.1.0")

    # Attach shared components.
    app.state.session_store = create_session_store()

    # CORS is intentionally opt-in for production safety.
    # Configure allowed origins via env var, e.g.
    #   LETTERBOXD_RECOMMENDER_CORS_ORIGINS=https://your.site,https://admin.your.site
    cors_origins = _parse_csv_env("LETTERBOXD_RECOMMENDER_CORS_ORIGINS")
    if cors_origins:
        # Allow '*' for quick demos; do not allow credentials with wildcard.
        allow_all = "*" in cors_origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"] if allow_all else cors_origins,
            allow_credentials=False,
            allow_methods=["*"] if allow_all else ["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    # Basic rate limiting to protect upstream calls.
    app.add_middleware(RateLimitMiddleware)

    # Ensure unexpected errors don't leak internals.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request, _exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(router)
    return app


app = create_app()
