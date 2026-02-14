from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api import routes
from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists


def test_ingest_persists_and_returns_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    def fake_ingest_user(username: str):
        assert username == "alice"
        return IngestedLists(username="alice", watched=["alien", "heat"], watchlist=["dune"])

    monkeypatch.setattr(routes, "ingest_user", fake_ingest_user)

    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/users/alice/ingest")
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice", "watched_count": 2, "watchlist_count": 1}

    user_dir = tmp_path / "data" / "users" / "alice"
    assert (user_dir / "watched.txt").read_text() == "alien\nheat\n"
    assert (user_dir / "watchlist.txt").read_text() == "dune\n"
