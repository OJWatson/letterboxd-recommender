# TRACE

This file records task-by-task execution notes for the portfolio automation.

- M0.1: Bootstrap FastAPI backend + project structure
- M0.2: Implemented ingestion of watched + watchlist via Letterboxd RSS feeds.
  - Core: `core/letterboxd_ingest.py` (RSS fetch + parse + persist)
  - API: `POST /api/users/{username}/ingest`
  - Tests cover RSS parsing and persistence via API route.
- M2.4: Added evaluation endpoint returning top feature contributions to similarity score.
  - API: `POST /api/evaluate` (username, film_id, top_n)
  - Core: `core/recommender.py::top_feature_contributions` (genres/directors/decades contributions)
  - Tests cover endpoint output + 404 when user not ingested.
- CI.FIX.M2: Confirmed milestone M2 CI acceptance gates are green.
  - `uv run ruff check .`
  - `uv run pytest -q`
- M3.2: Added a deterministic, LLM-light refinement prompt parser.
  - Core: `core/nlp.py::parse_refinement_prompt` returns a small schema (k, genres, year bounds, countries, similar-to title).
  - Tests: `tests/test_nlp_parser.py` covers the spec examples.
- CI.FIX.M3: Confirmed milestone M3 CI acceptance gates are green across the CI Python matrix.
  - `uv run ruff check .`
  - `uv run pytest -q`
  - `uv run --python 3.10/3.11/3.12 pytest -q`
- M4.0: Added a minimal single-page UI.
  - Route: `GET /` renders a no-build HTML+CSS+JS UI.
  - Features: username input, chat-style refinement prompt, infographic side panel, and session_id persistence via localStorage.
  - Tests: `tests/test_ui.py` covers basic HTML rendering.
- M4.1: Persisted backend session state + added basic rate limiting and safer error handling.
  - Sessions: SQLite-backed store (recommended slugs) under `LETTERBOXD_RECOMMENDER_DATA_DIR`.
  - Rate limiting: lightweight sliding-window middleware (429 on exceed).
  - App: default exception handler returns 500 without leaking internals.
  - Tests: `tests/test_session_persistence.py`, `tests/test_rate_limit.py`.
