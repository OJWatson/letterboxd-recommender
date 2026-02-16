from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from letterboxd_recommender.api.rate_limit import RateLimitMiddleware
from letterboxd_recommender.api.routes import router
from letterboxd_recommender.api.session import create_session_store


def create_app() -> FastAPI:
    app = FastAPI(title="Letterboxd Habit Recommender", version="0.1.0")

    # Attach shared components.
    app.state.session_store = create_session_store()

    # Basic rate limiting to protect upstream calls.
    app.add_middleware(RateLimitMiddleware)

    # Ensure unexpected errors don't leak internals.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request, _exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(router)
    return app


app = create_app()
