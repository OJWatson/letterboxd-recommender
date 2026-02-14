# Letterboxd Habit Recommender

Backend (FastAPI) for a small web app that ingests a Letterboxd user's watched films + watchlist and generates habit summaries and recommendations.

## Ingestion

- Endpoint: `POST /api/users/{username}/ingest`
- Source: Letterboxd RSS feeds (`/{username}/films/rss/` and `/{username}/watchlist/rss/`)
- Storage: newline-delimited film slugs at `data/users/{username}/watched.txt` and `data/users/{username}/watchlist.txt`

## Dev

```bash
uv sync --dev
uv run uvicorn letterboxd_recommender.api.app:app --reload
```

## Tests & lint

```bash
uv run ruff check .
uv run pytest -q
```
