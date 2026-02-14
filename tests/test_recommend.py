from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _fake_meta(slug: str) -> FilmMetadata:
    # keep simple + deterministic
    return FilmMetadata(slug=slug, title=slug.replace("-", " ").title(), year=None)


def test_recommend_endpoint_returns_5_and_excludes_watched_and_watchlist(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["alien", "heat"], watchlist=["dune"]),
        data_dir=tmp_path / "data",
    )

    # Make candidate pool small + controlled for test.
    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        [
            "alien",
            "dune",
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

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/recommend", json={"username": "alice", "k": 5})
    assert resp.status_code == 200

    body = resp.json()
    assert body["username"] == "alice"

    recs = body["recommendations"]
    assert len(recs) == 5

    # must exclude watched + watchlist
    excluded = {"alien", "heat", "dune"}
    assert not (excluded & {r["film_id"] for r in recs})
