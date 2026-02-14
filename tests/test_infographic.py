from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.infographic import build_infographic_summary
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _fake_meta(slug: str) -> FilmMetadata:
    by_slug: dict[str, FilmMetadata] = {
        "alien": FilmMetadata(
            slug="alien",
            title="Alien",
            year=1979,
            directors=["Ridley Scott"],
            genres=["Science Fiction", "Horror"],
        ),
        "heat": FilmMetadata(
            slug="heat",
            title="Heat",
            year=1995,
            directors=["Michael Mann"],
            genres=["Crime", "Thriller"],
        ),
        "dune": FilmMetadata(
            slug="dune",
            title="Dune",
            year=2021,
            directors=["Denis Villeneuve"],
            genres=["Science Fiction"],
        ),
    }
    return by_slug[slug]


def test_build_infographic_summary_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["alien", "heat"], watchlist=["dune"]),
        data_dir=tmp_path / "data",
    )

    summary = build_infographic_summary(
        "alice",
        list_kind="watched",
        top_n=10,
        data_dir=tmp_path / "data",
        metadata_provider=_fake_meta,
    )

    assert summary.film_count == 2
    assert dict(summary.top_decades) == {"1970s": 1, "1990s": 1}
    assert dict(summary.top_directors) == {"Ridley Scott": 1, "Michael Mann": 1}

    genres = dict(summary.top_genres)
    assert genres["Science Fiction"] == 1
    assert genres["Horror"] == 1
    assert genres["Crime"] == 1
    assert genres["Thriller"] == 1


def test_infographic_endpoint_uses_persisted_lists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["alien", "heat"], watchlist=[]),
        data_dir=tmp_path / "data",
    )

    # Endpoint uses build_infographic_summary -> core.infographic.get_film_metadata.
    monkeypatch.setattr(
        "letterboxd_recommender.core.infographic.get_film_metadata",
        lambda slug, **_: _fake_meta(slug),
    )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/users/alice/infographic?list_kind=watched&top_n=5")
    assert resp.status_code == 200

    body = resp.json()
    assert body["username"] == "alice"
    assert body["film_count"] == 2
    assert body["list_kind"] == "watched"

    assert {x["name"] for x in body["top_directors"]} == {"Ridley Scott", "Michael Mann"}
