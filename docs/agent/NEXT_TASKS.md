# NEXT_TASKS

Now:
- CI.FIX.M4 — CI fix: make GitHub Actions green for M4 boundary

Next:

Done:
- M4.END — Milestone end: M4 complete (gate on CI)
- M4.2 — Deploy: add deployment docs + production config (CORS, env vars)
- M4.1 — Backend: session persistence (lightweight store) + rate limiting / error handling
- M4.0 — Frontend: add minimal UI (username input + chat-style refinement + infographic panel)
- M3.END — Milestone end: M3 complete (gate on CI)
- M3.4 — Session: track previously recommended films per session and enforce exclusion
- M3.3 — Recommender: apply constraint filtering layer (genre/year/country/similar-to) + tests
- M3.2 — NLP: implement intent/constraint parser for refinement prompts (LLM-light + deterministic schema)
- M3.1 — Add smoke E2E test for ingest -> recommend flow
- M3.0 — Expose simple HTML report page for infographic + recommendations
- M2.END — Milestone end: M2 complete (gate on CI)
- M2.5 — Persist user ingest + derived features with versioned cache key
- M2.4 — Add evaluation endpoint: return top features contributing to score
- M2.3 — Recommender v2: add basic candidate filtering + scoring explainability
- M2.2 — Improve recommender: add simple similarity scoring and ranking tests
- M2.1 — Base recommender: return 5 recommendations excluding watched/watchlist
- M1.END — Milestone end: M1 complete (gate on CI)
- M1.2 — Generate infographic summary (genres/decades/directors) and expose endpoint
- M1.1 — Construct internal dataframe + feature engineering scaffold
- M0.END — Milestone end: M0 complete (gate on CI)
- M0.2 — Implement Letterboxd data ingestion (watched + watchlist)
