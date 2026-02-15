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
