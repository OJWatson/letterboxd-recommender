from __future__ import annotations

from fastapi import APIRouter, HTTPException

from letterboxd_recommender.core.schemas import (
    IngestResponse,
    RecommendRequest,
    RecommendResponse,
)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/users/{username}/ingest", response_model=IngestResponse)
def ingest(username: str) -> IngestResponse:
    # M0.2 will implement real Letterboxd ingestion.
    return IngestResponse(username=username, watched_count=0, watchlist_count=0)


@router.post("/api/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest) -> RecommendResponse:
    # M2+ will implement recommendation logic.
    raise HTTPException(status_code=501, detail="Recommendation engine not implemented yet")
