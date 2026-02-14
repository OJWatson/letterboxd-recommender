from __future__ import annotations

from fastapi import APIRouter, HTTPException

from letterboxd_recommender.core.letterboxd_ingest import (
    LetterboxdIngestError,
    LetterboxdUserNotFound,
    ingest_user,
    persist_ingest,
)
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
    try:
        result = ingest_user(username)
        persist_ingest(result)
        return IngestResponse(
            username=username,
            watched_count=len(result.watched),
            watchlist_count=len(result.watchlist),
        )
    except LetterboxdUserNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except LetterboxdIngestError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/api/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest) -> RecommendResponse:
    # M2+ will implement recommendation logic.
    raise HTTPException(status_code=501, detail="Recommendation engine not implemented yet")
