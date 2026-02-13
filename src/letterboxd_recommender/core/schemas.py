from __future__ import annotations

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    username: str
    watched_count: int = Field(ge=0)
    watchlist_count: int = Field(ge=0)


class RecommendRequest(BaseModel):
    username: str
    prompt: str | None = None
    k: int = Field(default=5, ge=1, le=20)


class Recommendation(BaseModel):
    film_id: str
    title: str
    year: int | None = None
    blurb: str
    why: str


class RecommendResponse(BaseModel):
    username: str
    recommendations: list[Recommendation]
