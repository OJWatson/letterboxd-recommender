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

    # M2.3: basic scoring explainability
    score: float | None = None
    score_breakdown: dict[str, float] | None = None
    overlaps: dict[str, list[str]] | None = None


class RecommendResponse(BaseModel):
    username: str
    recommendations: list[Recommendation]


class CountItem(BaseModel):
    name: str
    count: int = Field(ge=0)


class InfographicSummaryResponse(BaseModel):
    username: str
    list_kind: str
    film_count: int = Field(ge=0)
    top_genres: list[CountItem]
    top_decades: list[CountItem]
    top_directors: list[CountItem]
