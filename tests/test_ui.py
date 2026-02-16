from __future__ import annotations

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app


def test_index_page_renders_minimal_ui() -> None:
    app = create_app()
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

    body = resp.text
    assert "<title>Letterboxd Recommender</title>" in body
    assert "id=\"username\"" in body
    assert "id=\"prompt\"" in body
    assert "id=\"infographic\"" in body
