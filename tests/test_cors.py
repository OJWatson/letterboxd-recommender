from __future__ import annotations

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app


def test_cors_is_opt_in(monkeypatch):
    monkeypatch.delenv("LETTERBOXD_RECOMMENDER_CORS_ORIGINS", raising=False)
    app = create_app()
    client = TestClient(app)

    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    # No CORS headers when not configured.
    assert "access-control-allow-origin" not in resp.headers


def test_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv(
        "LETTERBOXD_RECOMMENDER_CORS_ORIGINS",
        "https://example.com,https://other.example.com",
    )
    app = create_app()
    client = TestClient(app)

    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.com"
