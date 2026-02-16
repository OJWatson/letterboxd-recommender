from __future__ import annotations

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app


def test_rate_limit_returns_429(monkeypatch) -> None:
    # Keep the window long to avoid flakes; use a tiny limit.
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_RL_GLOBAL", "2")
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_RL_GLOBAL_WINDOW_S", "60")

    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200

    r3 = client.get("/health")
    assert r3.status_code == 429
    assert r3.json()["detail"] == "Rate limit exceeded"
