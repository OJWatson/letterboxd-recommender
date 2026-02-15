from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def _meta(slug: str) -> FilmMetadata:
    fixtures: dict[str, FilmMetadata] = {
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
        "cand-1": FilmMetadata(
            slug="cand-1",
            title="Cand 1",
            year=1999,
            directors=["Someone Else"],
            genres=["Sci-Fi"],
        ),
        "cand-2": FilmMetadata(
            slug="cand-2",
            title="Cand 2",
            year=2001,
            directors=["Another Person"],
            genres=["Action"],
        ),
    }
    return fixtures[slug]


def test_report_page_renders_infographic_and_recommendations(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    persist_ingest(
        IngestedLists(username="alice", watched=["alien", "heat"], watchlist=[]),
        data_dir=tmp_path / "data",
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.infographic.get_film_metadata",
        lambda slug, **_: _meta(slug),
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-1", "cand-2"],
    )
    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.get_film_metadata",
        lambda slug, **_: _meta(slug),
    )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/users/alice/report?list_kind=watched&top_n=5&k=2")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

    body = resp.text
    assert "<title>Letterboxd report — alice</title>" in body
    assert "Top genres" in body
    assert "Recommendations" in body

    # Should include our deterministic candidate titles.
    assert "Cand 1" in body
    assert "Cand 2" in body
