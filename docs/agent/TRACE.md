# TRACE

This file records task-by-task execution notes for the portfolio automation.

- M0.1: Bootstrap FastAPI backend + project structure
- M0.2: Implemented ingestion of watched + watchlist via Letterboxd RSS feeds.
  - Core: `core/letterboxd_ingest.py` (RSS fetch + parse + persist)
  - API: `POST /api/users/{username}/ingest`
  - Tests cover RSS parsing and persistence via API route.
