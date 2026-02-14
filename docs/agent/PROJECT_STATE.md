# PROJECT_STATE

Status: ACTIVE

- Default branch: main
- Workflow: direct commits to main

## Milestones

- M0.2: DONE — Letterboxd data ingestion (watched + watchlist) via RSS feeds; persisted to `data/users/{username}/`.

## Acceptance gates

- uv run ruff check .
- uv run pytest -q
