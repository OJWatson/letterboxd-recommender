# Letterboxd Habit Recommender

Backend (FastAPI) for a small web app that ingests a Letterboxd user's watched films + watchlist and generates habit summaries and recommendations.

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
