from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from letterboxd_recommender.core.film_metadata import FilmMetadataError
from letterboxd_recommender.core.infographic import build_infographic_summary
from letterboxd_recommender.core.letterboxd_ingest import (
    LetterboxdIngestError,
    LetterboxdUserNotFound,
    ingest_user,
    persist_ingest,
)
from letterboxd_recommender.core.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    InfographicSummaryResponse,
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


@router.get("/api/users/{username}/infographic", response_model=InfographicSummaryResponse)
def infographic_summary(
    username: str,
    list_kind: str = Query(default="watched", pattern="^(watched|watchlist|all)$"),
    top_n: int = Query(default=10, ge=1, le=50),
) -> InfographicSummaryResponse:
    try:
        summary = build_infographic_summary(username, list_kind=list_kind, top_n=top_n)
        return InfographicSummaryResponse(
            username=username,
            list_kind=summary.list_kind,
            film_count=summary.film_count,
            top_genres=[{"name": k, "count": v} for k, v in summary.top_genres],
            top_decades=[{"name": k, "count": v} for k, v in summary.top_decades],
            top_directors=[{"name": k, "count": v} for k, v in summary.top_directors],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FilmMetadataError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/api/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest) -> RecommendResponse:
    from letterboxd_recommender.core.recommender import recommend_for_user

    try:
        recs = recommend_for_user(req.username, k=req.k, prompt=req.prompt)
        return RecommendResponse(
            username=req.username,
            recommendations=[
                {
                    "film_id": r.film_id,
                    "title": r.title,
                    "year": r.year,
                    "blurb": r.blurb,
                    "why": r.why,
                    "score": r.score,
                    "score_breakdown": r.score_breakdown,
                    "overlaps": r.overlaps,
                }
                for r in recs
            ],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest) -> EvaluateResponse:
    from letterboxd_recommender.core.recommender import top_feature_contributions

    try:
        score, top_features = top_feature_contributions(
            req.username,
            req.film_id,
            top_n=req.top_n,
        )
        return EvaluateResponse(
            username=req.username,
            film_id=req.film_id,
            score=score,
            top_features=[
                {
                    "feature": f.feature,
                    "similarity": f.similarity,
                    "weight": f.weight,
                    "contribution": f.contribution,
                    "overlaps": f.overlaps,
                }
                for f in top_features
            ],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FilmMetadataError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
