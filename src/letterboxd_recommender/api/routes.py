from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

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

        # Cache derived user features (internal dataframe) with a versioned cache key.
        from letterboxd_recommender.core.dataframe import build_or_load_user_films_df

        build_or_load_user_films_df(username)

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
    from letterboxd_recommender.api.session import SESSION_STORE
    from letterboxd_recommender.core.recommender import recommend_for_user

    try:
        session_id, state = SESSION_STORE.get_or_create(req.session_id)

        recs = recommend_for_user(
            req.username,
            k=req.k,
            prompt=req.prompt,
            exclude_slugs=set(state.recommended_slugs),
        )

        # Update per-session exclusion set.
        state.recommended_slugs |= {r.film_id for r in recs}

        return RecommendResponse(
            username=req.username,
            session_id=session_id,
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


@router.get("/users/{username}/report", response_class=HTMLResponse)
def user_report(
    username: str,
    list_kind: str = Query(default="watched", pattern="^(watched|watchlist|all)$"),
    top_n: int = Query(default=10, ge=1, le=50),
    k: int = Query(default=5, ge=1, le=20),
) -> HTMLResponse:
    """Human-friendly HTML page showing a user's infographic + recommendations."""

    from letterboxd_recommender.core.recommender import recommend_for_user

    try:
        summary = build_infographic_summary(username, list_kind=list_kind, top_n=top_n)
        recs = recommend_for_user(username, k=k)

        def _render_top(items: list[tuple[str, int]]) -> str:
            if not items:
                return "<p><em>No data.</em></p>"
            lis = "\n".join(
                f"<li><strong>{html.escape(name)}</strong> — {count}</li>" for name, count in items
            )
            return f"<ol>{lis}</ol>"

        rec_items: list[str] = []
        for r in recs:
            year_html = f" <span class=\"year\">({r.year})</span>" if r.year else ""
            why_html = (
                f"<div class=\"rec-why\">{html.escape(r.why)}</div>" if r.why else ""
            )
            rec_items.append(
                "\n".join(
                    [
                        "<li>",
                        f"<div class=\"rec-title\">{html.escape(r.title)}{year_html}</div>",
                        (
                            f"<div class=\"rec-meta\"><code>{html.escape(r.film_id)}</code>"
                            f" · score {r.score:.3f}</div>"
                        ),
                        why_html,
                        "</li>",
                    ]
                )
            )
        rec_lis = "\n".join(rec_items)

        meta_line = (
            "Infographic list: "
            f"<code>{html.escape(summary.list_kind)}</code>"
            f" · films: {summary.film_count}"
            f" · recs: {len(recs)}"
        )

        infographic_url = (
            f"/api/users/{html.escape(username)}/infographic"
            f"?list_kind={html.escape(summary.list_kind)}"
            f"&top_n={top_n}"
        )

        html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Letterboxd report — {html.escape(username)}</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      margin: 2rem;
      max-width: 60rem;
    }}
    header {{ margin-bottom: 1.5rem; }}
    h1 {{ margin: 0 0 .25rem 0; }}
    .muted {{ color: #666; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
      gap: 1rem;
    }}
    section {{ border: 1px solid #eee; border-radius: .5rem; padding: 1rem; }}
    .rec-title {{ font-weight: 700; }}
    .rec-meta {{ font-size: .9rem; color: #444; margin-top: .15rem; }}
    .rec-why {{ margin-top: .4rem; }}
    code {{ background: #f6f6f6; padding: .1rem .25rem; border-radius: .25rem; }}
  </style>
</head>
<body>
  <header>
    <h1>Report: {html.escape(username)}</h1>
    <div class=\"muted\">{meta_line}</div>
  </header>

  <div class=\"grid\">
    <section>
      <h2>Top genres</h2>
      {_render_top(summary.top_genres)}
    </section>
    <section>
      <h2>Top decades</h2>
      {_render_top(summary.top_decades)}
    </section>
    <section>
      <h2>Top directors</h2>
      {_render_top(summary.top_directors)}
    </section>
  </div>

  <section style=\"margin-top: 1rem;\">
    <h2>Recommendations</h2>
    <ol>
      {rec_lis or '<li><em>No recommendations.</em></li>'}
    </ol>
  </section>

  <section style=\"margin-top: 1rem;\">
    <h2>API links</h2>
    <ul>
      <li>
        <a href=\"{infographic_url}\">
          infographic JSON
        </a>
      </li>
    </ul>
  </section>
</body>
</html>"""

        return HTMLResponse(content=html_doc)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FilmMetadataError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
