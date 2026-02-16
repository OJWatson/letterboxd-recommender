# Deployment

This project is a small FastAPI app. It can run locally, on a VM, or on a simple PaaS.

## Render (recommended quick path)

This repo includes a Render Blueprint file at `render.yaml`.

### One-time setup

1. Push this repository to GitHub.
2. In Render, choose **New +** -> **Blueprint**.
3. Select your repo and confirm the blueprint.
4. Render will create:
   - one web service
   - one persistent disk mounted at `/var/data`
5. Once deployed, open:
   - app UI: `https://<your-service>.onrender.com/`
   - health endpoint: `https://<your-service>.onrender.com/health`

### Notes

- The blueprint sets `LETTERBOXD_RECOMMENDER_DATA_DIR=/var/data` so session/data caches persist across restarts.
- If you later host frontend separately, set `LETTERBOXD_RECOMMENDER_CORS_ORIGINS` to your frontend origin.

## GitHub Actions auto-deploy to Render

This repo includes `.github/workflows/deploy.yml`, which deploys to Render after `CI` succeeds on `main`.

### One-time setup in Render

1. Open your Render web service.
2. Go to **Settings** -> **Deploy Hook**.
3. Create/copy a deploy hook URL.

### One-time setup in GitHub

1. Open your GitHub repo -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Add a new repository secret:
   - `RENDER_DEPLOY_HOOK_URL` = your Render deploy hook URL

After this, each successful CI run on `main` will automatically trigger a Render deploy.

## Production run command

```bash
# Create the venv / sync deps
uv sync

# Run in production mode
uv run uvicorn letterboxd_recommender.api.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers
```

Notes:
- Many PaaS providers inject `PORT`; the command above respects it.
- For a reverse-proxy setup (nginx / Caddy), keep `--proxy-headers`.

## Environment variables

### CORS

CORS is **opt-in**. If you are hosting the frontend on a different origin than the API, set:

- `LETTERBOXD_RECOMMENDER_CORS_ORIGINS`
  - Comma-separated or newline-separated list of allowed origins.
  - Example:

```bash
export LETTERBOXD_RECOMMENDER_CORS_ORIGINS="https://your-site.example,https://admin.your-site.example"
```

For quick demos you may use `*`:

```bash
export LETTERBOXD_RECOMMENDER_CORS_ORIGINS="*"
```

(When using `*`, the app does not allow credentials.)

### Data storage

The app writes small caches (ingested user data, derived dataframes, session DB):

- `LETTERBOXD_RECOMMENDER_DATA_DIR` (default: `data/`)
  - Base directory for persisted artifacts.

- `LETTERBOXD_RECOMMENDER_SESSION_DB` (default: `${LETTERBOXD_RECOMMENDER_DATA_DIR}/sessions.sqlite3`)
  - Override the session SQLite path.

### Rate limiting

All values are per-client-IP sliding window limits.

- `LETTERBOXD_RECOMMENDER_RL_GLOBAL` (default: `60`)
- `LETTERBOXD_RECOMMENDER_RL_GLOBAL_WINDOW_S` (default: `60`)
- `LETTERBOXD_RECOMMENDER_RL_INGEST` (default: `5`)
- `LETTERBOXD_RECOMMENDER_RL_INGEST_WINDOW_S` (default: `60`)

## Minimal reverse proxy (nginx)

If you want HTTPS and a custom domain, terminate TLS at a reverse proxy and forward to uvicorn.

Example nginx location:

```nginx
location / {
  proxy_pass http://127.0.0.1:8000;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Smoke check

```bash
curl -s http://localhost:8000/health
```
