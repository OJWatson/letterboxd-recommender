# ruff: noqa: E501

from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse

from letterboxd_recommender.core.export_import import (
    LetterboxdExportImportError,
    import_letterboxd_export,
)
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
    ImportExportResponse,
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


@router.post("/api/users/{username}/import-export", response_model=ImportExportResponse)
async def import_export(
    username: str, file: Annotated[UploadFile, File(...)]
) -> ImportExportResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file is missing a filename")

    try:
        content = await file.read()
        imported = import_letterboxd_export(username, file.filename, content)
        persist_ingest(imported.lists)

        from letterboxd_recommender.core.dataframe import build_or_load_user_films_df

        build_or_load_user_films_df(username, force_rebuild=True)

        return ImportExportResponse(
            username=username,
            watched_count=len(imported.lists.watched),
            watchlist_count=len(imported.lists.watchlist),
            list_count=imported.list_count,
            source=imported.source,
        )
    except LetterboxdExportImportError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
            runtime_distribution=[{"name": k, "count": v} for k, v in summary.runtime_distribution],
            average_runtime_minutes=summary.average_runtime_minutes,
            average_user_rating=summary.average_user_rating,
            average_global_rating=summary.average_global_rating,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FilmMetadataError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/api/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, request: Request) -> RecommendResponse:
    from letterboxd_recommender.core.recommender import recommend_for_user

    try:
        store = request.app.state.session_store
        session_id, state = store.get_or_create(req.session_id)

        recs = recommend_for_user(
            req.username,
            k=req.k,
            prompt=req.prompt,
            exclude_slugs=set(state.recommended_slugs),
        )

        # Update per-session exclusion set.
        state.recommended_slugs |= {r.film_id for r in recs}
        store.save(session_id, state)

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


def _fmt_nullable(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


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

        def _render_rows(items: list[tuple[str, int]]) -> str:
            if not items:
                return '<div class="muted"><em>No data.</em></div>'

            max_count = max(c for _, c in items) or 1
            rows: list[str] = []
            for name, count in items:
                width = int((count / max_count) * 100)
                rows.append(
                    f"""
                    <div class="bar-row">
                      <div class="bar-label">{html.escape(name)}</div>
                      <div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>
                      <div class="bar-val">{count}</div>
                    </div>
                    """
                )
            return "\n".join(rows)

        rec_items: list[str] = []
        for r in recs:
            year_html = f" <span class=\"year\">({r.year})</span>" if r.year else ""
            why_html = f"<div class=\"rec-why\">{html.escape(r.why)}</div>" if r.why else ""
            rec_items.append(
                "\n".join(
                    [
                        '<article class="rec-card">',
                        f"<h3>{html.escape(r.title)}{year_html}</h3>",
                        (
                            f"<div class=\"rec-meta\"><code>{html.escape(r.film_id)}</code>"
                            f" · score {r.score:.3f}</div>"
                        ),
                        f"<p>{html.escape(r.blurb)}</p>",
                        why_html,
                        "</article>",
                    ]
                )
            )

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
    :root {{
      --bg: #f5f2ea;
      --paper: #fffaf0;
      --ink: #1f1a12;
      --muted: #6f6253;
      --line: #dbc8ad;
      --accent: #a44f2f;
      --bar: #cf9a66;
      --bar-soft: #f0dfcc;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, #fff3de, #f5f2ea 36rem);
    }}
    main {{ max-width: 72rem; margin: 0 auto; padding: 1.2rem; }}
    header {{ margin-bottom: 1rem; }}
    h1 {{ margin: 0 0 .25rem 0; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 1rem; }}
    .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 1rem; padding: 1rem; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: .6rem; margin-top: .8rem; }}
    .stat {{ border: 1px solid var(--line); border-radius: .6rem; padding: .55rem .6rem; background: #fff; }}
    .stat .label {{ font-size: .8rem; color: var(--muted); }}
    .stat .val {{ font-weight: 700; margin-top: .1rem; }}
    .bar-row {{ display: grid; grid-template-columns: 8.5rem 1fr 2rem; gap: .5rem; align-items: center; margin: .35rem 0; }}
    .bar-label {{ font-size: .86rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .bar-track {{ height: .58rem; background: var(--bar-soft); border-radius: 999px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--bar); }}
    .bar-val {{ text-align: right; font-size: .82rem; color: var(--muted); }}
    .recs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: .8rem; }}
    .rec-card {{ background: #fff; border: 1px solid var(--line); border-radius: .8rem; padding: .8rem; margin: 0; }}
    .rec-card h3 {{ margin: 0; font-size: 1rem; }}
    .rec-meta {{ font-size: .84rem; color: var(--muted); margin-top: .2rem; }}
    .rec-card p {{ margin: .55rem 0 .3rem 0; }}
    .rec-why {{ color: #3a332a; font-size: .92rem; }}
    code {{ background: #f7ecdd; padding: .08rem .3rem; border-radius: .32rem; }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Report: {html.escape(username)}</h1>
      <div class=\"muted\">{meta_line}</div>
    </header>

    <section class=\"card\" style=\"margin-bottom: 1rem;\">
      <h2 style=\"margin:0 0 .25rem 0;\">Ratings and Runtime</h2>
      <div class=\"stats\">
        <div class=\"stat\"><div class=\"label\">Average runtime</div><div class=\"val\">{_fmt_nullable(summary.average_runtime_minutes, digits=1, suffix='m')}</div></div>
        <div class=\"stat\"><div class=\"label\">Your average rating</div><div class=\"val\">{_fmt_nullable(summary.average_user_rating)}</div></div>
        <div class=\"stat\"><div class=\"label\">Global average rating</div><div class=\"val\">{_fmt_nullable(summary.average_global_rating)}</div></div>
      </div>
      <div style=\"margin-top:.85rem\">
        <h3 style=\"margin:.2rem 0\">Runtime distribution</h3>
        {_render_rows(summary.runtime_distribution)}
      </div>
    </section>

    <div class=\"grid\">
      <section class=\"card\">
        <h2 style=\"margin-top:0\">Top genres</h2>
        {_render_rows(summary.top_genres)}
      </section>
      <section class=\"card\">
        <h2 style=\"margin-top:0\">Top decades</h2>
        {_render_rows(summary.top_decades)}
      </section>
      <section class=\"card\">
        <h2 style=\"margin-top:0\">Top directors</h2>
        {_render_rows(summary.top_directors)}
      </section>
    </div>

    <section class=\"card\" style=\"margin-top: 1rem;\">
      <h2 style=\"margin-top:0\">Recommendations</h2>
      <div class=\"recs\">{''.join(rec_items) or '<div class="muted"><em>No recommendations.</em></div>'}</div>
    </section>

    <section class=\"card\" style=\"margin-top: 1rem;\">
      <h2 style=\"margin-top:0\">API links</h2>
      <ul>
        <li><a href=\"{infographic_url}\">infographic JSON</a></li>
      </ul>
    </section>
  </main>
</body>
</html>"""

        return HTMLResponse(content=html_doc)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FilmMetadataError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Single-page UI for ingestion, infographic, and iterative recommendations."""

    html_doc = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Letterboxd Recommender</title>
  <style>
    :root {
      --bg: #10171d;
      --bg-alt: #0b1116;
      --panel: #17222b;
      --panel-soft: #1f2f3b;
      --text: #ecf3f8;
      --muted: #9eb3c4;
      --line: #2b3f4e;
      --accent: #f5a24a;
      --accent-2: #6ccadf;
      --chip: #22394a;
      --bar-bg: #223544;
      --bar-fill: linear-gradient(90deg, #6ccadf, #f5a24a);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(80rem 40rem at -10% -20%, #294458 0%, rgba(41, 68, 88, 0) 45%),
        radial-gradient(70rem 35rem at 110% -10%, #583b2c 0%, rgba(88, 59, 44, 0) 38%),
        linear-gradient(160deg, var(--bg), var(--bg-alt));
      font-family: ui-sans-serif, system-ui, sans-serif;
      min-height: 100vh;
    }
    .container { max-width: 80rem; margin: 0 auto; padding: 1rem; }
    header {
      border: 1px solid var(--line);
      border-radius: 1rem;
      padding: 1rem;
      background: rgba(23, 34, 43, 0.9);
      backdrop-filter: blur(6px);
    }
    h1 { margin: 0; font-size: 1.4rem; }
    .muted { color: var(--muted); }
    .layout {
      display: grid;
      grid-template-columns: 1.3fr .7fr;
      gap: 1rem;
      margin-top: 1rem;
    }
    @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } }
    .card {
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: rgba(23, 34, 43, 0.92);
      padding: 1rem;
    }
    label { display: block; font-size: .88rem; margin-bottom: .25rem; color: var(--muted); }
    input, button { font: inherit; color: inherit; }
    input[type=text] {
      width: 100%;
      padding: .62rem .72rem;
      border-radius: .65rem;
      border: 1px solid var(--line);
      background: var(--panel-soft);
    }
    button {
      padding: .6rem .9rem;
      border-radius: .65rem;
      border: 1px solid #476173;
      background: linear-gradient(135deg, #375266, #273947);
      cursor: pointer;
      transition: transform .14s ease, border-color .14s ease;
    }
    button:hover { transform: translateY(-1px); border-color: #6f8ca1; }
    button:disabled { opacity: .5; cursor: not-allowed; transform: none; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: .55rem; align-items: end; }
    .pill {
      display: inline-block;
      padding: .16rem .48rem;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--chip);
      font-size: .8rem;
    }
    .chat {
      margin-top: .8rem;
      max-height: 22rem;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: .5rem;
      padding-right: .2rem;
    }
    .msg {
      max-width: 38rem;
      border: 1px solid var(--line);
      border-radius: .78rem;
      padding: .56rem .68rem;
      white-space: pre-wrap;
      animation: rise .22s ease;
    }
    .msg.user { margin-left: auto; background: #324c61; }
    .msg.bot { background: #1f303c; }
    .rec-grid {
      margin-top: .85rem;
      display: grid;
      gap: .65rem;
      grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
    }
    .rec {
      border: 1px solid var(--line);
      border-radius: .75rem;
      background: #1e2d37;
      padding: .6rem;
    }
    .rec h4 { margin: 0 0 .2rem 0; font-size: .98rem; }
    .rec-meta { font-size: .8rem; color: var(--muted); }
    .rec p { margin: .38rem 0 0 0; font-size: .9rem; }
    .stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: .55rem;
      margin: .8rem 0;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: .7rem;
      padding: .5rem .55rem;
      background: #1a2832;
    }
    .stat .k { color: var(--muted); font-size: .78rem; }
    .stat .v { font-weight: 700; margin-top: .12rem; }
    .chart { margin-top: .55rem; }
    .bar-row {
      display: grid;
      grid-template-columns: 7.5rem 1fr 2rem;
      gap: .45rem;
      align-items: center;
      margin: .3rem 0;
    }
    .bar-label { font-size: .82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-track { height: .54rem; background: var(--bar-bg); border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; background: var(--bar-fill); }
    .bar-count { font-size: .78rem; color: var(--muted); text-align: right; }
    hr { border: none; border-top: 1px solid var(--line); margin: .8rem 0; }
    .help {
      margin-top: .65rem;
      padding: .6rem .7rem;
      border: 1px solid var(--line);
      border-radius: .7rem;
      background: #1b2a34;
      font-size: .86rem;
    }
    .help ol { margin: .35rem 0 .1rem 1.1rem; padding: 0; }
    .help a { color: var(--accent-2); }
    .inline-upload { margin-top: .6rem; }
    .inline-upload input[type=file] {
      width: 100%;
      padding: .45rem;
      border: 1px dashed var(--line);
      border-radius: .6rem;
      background: #1a2832;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(3px); }
      to { opacity: 1; transform: translateY(0); }
    }
    code { background: #283d4d; border-radius: .3rem; padding: .05rem .28rem; }
  </style>
</head>
<body>
  <div class=\"container\">
    <header>
      <h1>Letterboxd Recommender</h1>
      <div class=\"muted\">Load a user, review their viewing snapshot, then iterate with natural-language prompts.</div>
    </header>

    <div class=\"layout\">
      <section class=\"card\">
        <h2 style=\"margin-top:0\">1) User</h2>
        <div class=\"row\">
          <div>
            <label for=\"username\">Letterboxd username</label>
            <input id=\"username\" type=\"text\" placeholder=\"e.g. jack\" autocomplete=\"username\" />
          </div>
          <button id=\"load\">Load</button>
        </div>
        <div class=\"inline-upload\">
          <label for=\"export_file\">Or upload Letterboxd export (.zip/.csv)</label>
          <input id=\"export_file\" type=\"file\" accept=\".zip,.csv\" />
          <div style=\"margin-top:.45rem\">
            <button id=\"import_btn\">Import Export</button>
          </div>
        </div>
        <div style=\"margin-top:.55rem\" class=\"muted\">Session: <span id=\"session\" class=\"pill\">(none)</span></div>
        <div class=\"help\">
          <strong>How to export from Letterboxd</strong>
          <ol>
            <li>Open Letterboxd and go to <code>Settings</code> -&gt; <code>Data</code>.</li>
            <li>Request/download your data export (ZIP).</li>
            <li>Upload the ZIP here, then click <code>Import Export</code>.</li>
          </ol>
          <div class=\"muted\">Official data page: <a href=\"https://letterboxd.com/settings/data/\" target=\"_blank\" rel=\"noopener\">letterboxd.com/settings/data/</a></div>
        </div>

        <h2 style=\"margin:1rem 0 0 0\">2) Refine</h2>
        <div class=\"chat\" id=\"chat\"></div>

        <div style=\"margin-top:.75rem\" class=\"row\">
          <div>
            <label for=\"prompt\">Refinement prompt</label>
            <input id=\"prompt\" type=\"text\" placeholder=\"e.g. 5 more like Parasite but before 2010\" />
          </div>
          <button id=\"send\" disabled>Send</button>
        </div>

        <div class=\"muted\" style=\"margin-top:.65rem\">Uses <code>POST /api/recommend</code> with <code>session_id</code> to avoid repeats.</div>

        <hr />
        <h3 style=\"margin:.3rem 0\">Recommendations</h3>
        <div id=\"recommendations\" class=\"rec-grid\"></div>
      </section>

      <aside class=\"card\">
        <h2 style=\"margin-top:0\">Infographic</h2>
        <div id=\"infographic\" class=\"muted\">No user loaded.</div>
      </aside>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);

    function appendMsg(kind, text) {
      const el = document.createElement('div');
      el.className = `msg ${kind}`;
      el.textContent = text;
      $('chat').appendChild(el);
      el.scrollIntoView({block: 'end'});
    }

    function setBusy(busy) {
      $('load').disabled = busy;
      $('import_btn').disabled = busy;
      $('send').disabled = busy || !$('username').value.trim();
    }

    function getSessionKey(username) {
      return `lbrec.session.${username}`;
    }

    async function apiJSON(url, opts) {
      const resp = await fetch(url, opts);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
      }
      return await resp.json();
    }

    function fmt(value, digits=2, suffix='') {
      if (value === null || value === undefined) return 'n/a';
      return `${Number(value).toFixed(digits)}${suffix}`;
    }

    function renderBars(items) {
      if (!items || items.length === 0) return '<div class="muted"><em>No data</em></div>';
      const max = Math.max(...items.map((x) => x.count), 1);
      return items.map((it) => {
        const width = Math.round((it.count / max) * 100);
        return `
          <div class="bar-row">
            <div class="bar-label">${it.name}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
            <div class="bar-count">${it.count}</div>
          </div>
        `;
      }).join('');
    }

    function renderInfographic(summary) {
      const box = $('infographic');
      box.className = '';
      box.innerHTML = `
        <div class="pill">${summary.list_kind}</div>
        <div class="stats">
          <div class="stat"><div class="k">Films</div><div class="v">${summary.film_count}</div></div>
          <div class="stat"><div class="k">Avg runtime</div><div class="v">${fmt(summary.average_runtime_minutes, 1, 'm')}</div></div>
          <div class="stat"><div class="k">Your avg rating</div><div class="v">${fmt(summary.average_user_rating)}</div></div>
          <div class="stat"><div class="k">Global avg rating</div><div class="v">${fmt(summary.average_global_rating)}</div></div>
        </div>
        <div class="chart"><strong>Top genres</strong>${renderBars(summary.top_genres)}</div>
        <div class="chart"><strong>Top decades</strong>${renderBars(summary.top_decades)}</div>
        <div class="chart"><strong>Top directors</strong>${renderBars(summary.top_directors)}</div>
        <div class="chart"><strong>Runtime distribution</strong>${renderBars(summary.runtime_distribution)}</div>
      `;
    }

    function renderRecommendations(items) {
      const el = $('recommendations');
      if (!items || items.length === 0) {
        el.innerHTML = '<div class="muted"><em>No recommendations.</em></div>';
        return;
      }

      el.innerHTML = items.map((r) => {
        const year = r.year ? ` (${r.year})` : '';
        const score = (r.score === null || r.score === undefined) ? 'n/a' : Number(r.score).toFixed(3);
        return `
          <article class="rec">
            <h4>${r.title}${year}</h4>
            <div class="rec-meta"><code>${r.film_id}</code> · score ${score}</div>
            <p>${r.blurb || ''}</p>
            <p><strong>Why:</strong> ${r.why || 'n/a'}</p>
          </article>
        `;
      }).join('');
    }

    async function loadUser(username) {
      setBusy(true);
      $('chat').innerHTML = '';
      appendMsg('bot', `Loading data for ${username}...`);

      await apiJSON(`/api/users/${encodeURIComponent(username)}/ingest`, { method: 'POST' });
      const summary = await apiJSON(`/api/users/${encodeURIComponent(username)}/infographic?list_kind=watched&top_n=10`);
      renderInfographic(summary);

      const existingSession = localStorage.getItem(getSessionKey(username)) || '';
      $('session').textContent = existingSession || '(new)';

      await sendPrompt(username, '', existingSession);
      setBusy(false);
    }

    async function importExport(username) {
      const fileInput = $('export_file');
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        appendMsg('bot', 'Choose a .zip or .csv export file first.');
        return;
      }

      setBusy(true);
      $('chat').innerHTML = '';
      appendMsg('bot', `Importing export for ${username}...`);

      try {
        const form = new FormData();
        form.append('file', file);

        const resp = await fetch(`/api/users/${encodeURIComponent(username)}/import-export`, {
          method: 'POST',
          body: form,
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
        }
        const body = await resp.json();
        appendMsg('bot', `Imported watched=${body.watched_count}, watchlist=${body.watchlist_count}, lists=${body.list_count}.`);

        const summary = await apiJSON(`/api/users/${encodeURIComponent(username)}/infographic?list_kind=watched&top_n=10`);
        renderInfographic(summary);

        const existingSession = localStorage.getItem(getSessionKey(username)) || '';
        $('session').textContent = existingSession || '(new)';
        await sendPrompt(username, '', existingSession);
      } catch (err) {
        appendMsg('bot', `Import failed: ${err.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function sendPrompt(username, prompt, sessionId) {
      if (prompt) appendMsg('user', prompt);
      appendMsg('bot', 'Thinking...');

      try {
        const payload = { username, k: 5, prompt: prompt || null, session_id: sessionId || null };
        const rec = await apiJSON('/api/recommend', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        localStorage.setItem(getSessionKey(username), rec.session_id);
        $('session').textContent = rec.session_id;

        const chat = $('chat');
        if (chat.lastChild) chat.removeChild(chat.lastChild);

        if (!rec.recommendations || rec.recommendations.length === 0) {
          renderRecommendations([]);
          appendMsg('bot', 'No recommendations found. Try changing your refinement prompt.');
          return;
        }

        renderRecommendations(rec.recommendations);

        const titles = rec.recommendations.map((r, i) => `${i + 1}. ${r.title}`).join('\n');
        appendMsg('bot', `Returned ${rec.recommendations.length} recommendations:\n${titles}`);
      } catch (err) {
        const chat = $('chat');
        if (chat.lastChild) chat.removeChild(chat.lastChild);
        appendMsg('bot', `Error: ${err.message}`);
      }
    }

    $('load').addEventListener('click', async () => {
      const username = $('username').value.trim();
      if (!username) return;
      await loadUser(username);
    });

    $('import_btn').addEventListener('click', async () => {
      const username = $('username').value.trim();
      if (!username) return;
      await importExport(username);
    });

    $('send').addEventListener('click', async () => {
      const username = $('username').value.trim();
      if (!username) return;
      const prompt = $('prompt').value.trim();
      $('prompt').value = '';
      const sessionId = localStorage.getItem(getSessionKey(username)) || '';
      await sendPrompt(username, prompt, sessionId);
    });

    $('prompt').addEventListener('keydown', async (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      if ($('send').disabled) return;
      $('send').click();
    });

    $('username').addEventListener('input', () => {
      $('send').disabled = !$('username').value.trim();
    });
  </script>
</body>
</html>"""

    return HTMLResponse(content=html_doc)
