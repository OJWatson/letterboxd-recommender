from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _meta(slug: str) -> FilmMetadata:
    fixtures: dict[str, FilmMetadata] = {
        "watched-a": FilmMetadata(
            slug="watched-a",
            title="Watched A",
            year=1999,
            genres=["Sci-Fi", "Action"],
            directors=["The Wachowskis"],
        ),
        "cand-1": FilmMetadata(
            slug="cand-1",
            title="Cand 1",
            year=1999,
            genres=["Sci-Fi"],
            directors=["Someone Else"],
        ),
    }
    return fixtures[slug]


def test_evaluate_endpoint_returns_top_features_sorted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=tmp_path / "data",
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.get_film_metadata",
        lambda slug, **_: _meta(slug),
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/evaluate", json={"username": "alice", "film_id": "cand-1", "top_n": 3}
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["username"] == "alice"
    assert body["film_id"] == "cand-1"
    assert isinstance(body["score"], float)

    top = body["top_features"]
    assert len(top) == 3

    # cand-1 overlaps on genre (Sci-Fi) and decade (1990s), not director.
    assert top[0]["contribution"] >= top[1]["contribution"] >= top[2]["contribution"]
    assert {t["feature"] for t in top} == {"genres", "directors", "decades"}

    by_feature = {t["feature"]: t for t in top}
    assert by_feature["genres"]["overlaps"] == ["Sci-Fi"]
    assert by_feature["decades"]["overlaps"] == ["1990s"]
    assert by_feature["directors"]["overlaps"] == []


def test_evaluate_endpoint_404_if_user_not_ingested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.get_film_metadata",
        lambda slug, **_: _meta(slug),
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/evaluate", json={"username": "missing-user", "film_id": "cand-1"}
    )
    assert resp.status_code == 404
