from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app


def test_ingest_placeholder() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/users/alice/ingest")
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice", "watched_count": 0, "watchlist_count": 0}
