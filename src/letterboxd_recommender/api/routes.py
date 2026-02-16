# ruff: noqa: E501

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


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Minimal single-page UI for the recommender.

    Milestone M4 focuses on a lightweight frontend without bundlers or frameworks.
    """

    html_doc = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Letterboxd Recommender</title>
  <style>
    :root { --border: #eaeaea; --muted: #666; --bg: #fafafa; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: var(--bg); }
    header { padding: 1rem 1.25rem; border-bottom: 1px solid var(--border); background: white; }
    h1 { margin: 0; font-size: 1.1rem; }
    .muted { color: var(--muted); }
    .layout { display: grid; grid-template-columns: 1.2fr .8fr; gap: 1rem; padding: 1rem; max-width: 72rem; margin: 0 auto; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    .card { background: white; border: 1px solid var(--border); border-radius: .75rem; padding: 1rem; }
    label { display: block; font-size: .9rem; margin-bottom: .25rem; }
    input, button { font: inherit; }
    input[type=text] { width: 100%; padding: .55rem .6rem; border: 1px solid var(--border); border-radius: .5rem; }
    button { padding: .55rem .75rem; border: 1px solid var(--border); border-radius: .5rem; background: #111; color: white; cursor: pointer; }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: .5rem; align-items: end; }
    .chat { display: flex; flex-direction: column; gap: .5rem; margin-top: 1rem; }
    .msg { padding: .6rem .7rem; border-radius: .65rem; max-width: 44rem; white-space: pre-wrap; }
    .msg.user { align-self: flex-end; background: #111; color: white; }
    .msg.bot { align-self: flex-start; background: #f4f4f4; border: 1px solid var(--border); }
    .pill { display: inline-block; padding: .15rem .4rem; border: 1px solid var(--border); border-radius: 999px; font-size: .8rem; background: #fff; }
    .kv { display: grid; grid-template-columns: 1fr auto; gap: .5rem; }
    ul { margin: .5rem 0 0 1.1rem; }
    code { background: #f6f6f6; padding: .1rem .25rem; border-radius: .25rem; }
  </style>
</head>
<body>
  <header>
    <h1>Letterboxd Recommender</h1>
    <div class=\"muted\">Enter a Letterboxd username, then refine recommendations via a chat-style prompt.</div>
  </header>

  <div class=\"layout\">
    <section class=\"card\">
      <h2 style=\"margin-top:0\">1) Choose a user</h2>
      <div class=\"row\">
        <div>
          <label for=\"username\">Letterboxd username</label>
          <input id=\"username\" type=\"text\" placeholder=\"e.g. jack\" autocomplete=\"username\" />
        </div>
        <button id=\"load\">Load</button>
      </div>
      <div style=\"margin-top:.5rem\" class=\"muted\">
        Session: <span id=\"session\" class=\"pill\">(none)</span>
      </div>

      <h2 style=\"margin:1rem 0 0 0\">2) Refine (chat)</h2>
      <div class=\"chat\" id=\"chat\"></div>

      <div style=\"margin-top: .75rem\" class=\"row\">
        <div>
          <label for=\"prompt\">Refinement prompt</label>
          <input id=\"prompt\" type=\"text\" placeholder=\"e.g. something like Heat, but newer, no horror\" />
        </div>
        <button id=\"send\" disabled>Send</button>
      </div>
      <div style=\"margin-top: .75rem\" class=\"muted\">
        Uses <code>POST /api/recommend</code> with <code>session_id</code> to avoid repeating films.
      </div>
    </section>

    <aside class=\"card\">
      <h2 style=\"margin-top:0\">Infographic</h2>
      <div id=\"infographic\" class=\"muted\">No user loaded.</div>
    </aside>
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

    function renderInfographic(summary) {
      const box = $('infographic');
      const top = (items) => {
        if (!items || items.length === 0) return '<div class="muted"><em>No data</em></div>';
        const lis = items.map((it) => `<li><strong>${it.name}</strong> — ${it.count}</li>`).join('');
        return `<ul>${lis}</ul>`;
      };

      box.className = '';
      box.innerHTML = `
        <div class="kv"><div><strong>User</strong></div><div><code>${summary.username}</code></div></div>
        <div class="kv"><div><strong>List</strong></div><div><span class="pill">${summary.list_kind}</span></div></div>
        <div class="kv"><div><strong>Films</strong></div><div>${summary.film_count}</div></div>
        <hr style="border:none;border-top:1px solid var(--border);margin:.75rem 0" />
        <div><strong>Top genres</strong>${top(summary.top_genres)}</div>
        <div style="margin-top:.75rem"><strong>Top decades</strong>${top(summary.top_decades)}</div>
        <div style="margin-top:.75rem"><strong>Top directors</strong>${top(summary.top_directors)}</div>
      `;
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
        chat.removeChild(chat.lastChild);

        if (!rec.recommendations || rec.recommendations.length === 0) {
          appendMsg('bot', 'No recommendations found. Try changing your refinement prompt.');
          return;
        }

        const lines = rec.recommendations.map((r, i) => {
          const yr = r.year ? ` (${r.year})` : '';
          const why = r.why ? `\n  - why: ${r.why}` : '';
          return `${i + 1}. ${r.title}${yr} [${r.film_id}]${why}`;
        });
        appendMsg('bot', `Recommendations:\n${lines.join('\n')}`);
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

    $('send').addEventListener('click', async () => {
      const username = $('username').value.trim();
      if (!username) return;
      const prompt = $('prompt').value.trim();
      $('prompt').value = '';
      const sessionId = localStorage.getItem(getSessionKey(username)) || '';
      await sendPrompt(username, prompt, sessionId);
    });

    $('username').addEventListener('input', () => {
      $('send').disabled = !$('username').value.trim();
    });
  </script>
</body>
</html>"""

    return HTMLResponse(content=html_doc)
