# Letterboxd Habit Recommender

Backend (FastAPI) for a small web app that ingests a Letterboxd user's watched films + watchlist and generates habit summaries and recommendations.

## API

### Ingest a user

```bash
curl -X POST http://localhost:8000/api/users/<username>/ingest
```

### Infographic summary (genres / decades / directors)

```bash
curl "http://localhost:8000/api/users/<username>/infographic?list_kind=watched&top_n=10"
```

Query params:
- `list_kind`: `watched` (default), `watchlist`, or `all`
- `top_n`: 1–50 (default 10)

### HTML report page (infographic + recommendations)

```bash
open "http://localhost:8000/users/<username>/report?list_kind=watched&top_n=10&k=5"
```

### Recommendations

```bash
curl -X POST http://localhost:8000/api/recommend \
  -H 'content-type: application/json' \
  -d '{"username":"<username>","k":5}'
```

### Evaluate a candidate film (feature contributions)

Returns a weighted score plus the top contributing feature groups (genres / directors / decades).

```bash
curl -X POST http://localhost:8000/api/evaluate \
  -H 'content-type: application/json' \
  -d '{"username":"<username>","film_id":"the-matrix","top_n":3}'
```

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
