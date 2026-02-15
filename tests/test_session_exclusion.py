from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _fake_meta(slug: str) -> FilmMetadata:
    return FilmMetadata(slug=slug, title=slug.replace("-", " ").title(), year=None)


def test_session_tracks_previously_recommended_and_excludes_on_next_call(
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

    client = TestClient(create_app())

    r1 = client.post("/api/recommend", json={"username": "alice", "k": 3})
    assert r1.status_code == 200
    body1 = r1.json()
    session_id = body1["session_id"]

    recs1 = {r["film_id"] for r in body1["recommendations"]}
    assert len(recs1) == 3
    assert "alien" not in recs1

    r2 = client.post(
        "/api/recommend",
        json={"username": "alice", "k": 3, "session_id": session_id},
    )
    assert r2.status_code == 200

    body2 = r2.json()
    assert body2["session_id"] == session_id

    recs2 = {r["film_id"] for r in body2["recommendations"]}
    assert len(recs2) == 3

    # Session exclusion: second response should not repeat the first.
    assert not (recs1 & recs2)
