from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _fake_meta(slug: str) -> FilmMetadata:
    return FilmMetadata(slug=slug, title=slug.replace("-", " ").title(), year=None)


def test_session_is_persisted_to_sqlite_across_app_instances(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["alien"], watchlist=[]),
        data_dir=tmp_path / "data",
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        [
            "alien",
            "the-matrix",
            "parasite",
            "inception",
            "spirited-away",
            "the-godfather",
            "heat",
            "whiplash",
        ],
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.get_film_metadata",
        lambda slug, **_: _fake_meta(slug),
    )

    # App instance #1: create a session and get recs.
    from letterboxd_recommender.api.app import create_app

    client1 = TestClient(create_app())
    r1 = client1.post("/api/recommend", json={"username": "alice", "k": 3})
    assert r1.status_code == 200
    body1 = r1.json()
    session_id = body1["session_id"]
    recs1 = {r["film_id"] for r in body1["recommendations"]}

    # Simulate a restart by forcing a new app + reloading the session module.
    if "letterboxd_recommender.api.session" in sys.modules:
        importlib.reload(sys.modules["letterboxd_recommender.api.session"])

    client2 = TestClient(create_app())
    r2 = client2.post(
        "/api/recommend",
        json={"username": "alice", "k": 3, "session_id": session_id},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["session_id"] == session_id

    recs2 = {r["film_id"] for r in body2["recommendations"]}

    # Should not repeat, even across app instances.
    assert not (recs1 & recs2)
