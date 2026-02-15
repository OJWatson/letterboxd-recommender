from __future__ import annotations

from pathlib import Path

import pytest

from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest
from letterboxd_recommender.core.recommender import recommend_for_user


def _meta(slug: str) -> FilmMetadata:
    fixtures: dict[str, FilmMetadata] = {
        # watched
        "watched-a": FilmMetadata(
            slug="watched-a",
            title="Watched A",
            year=1999,
            genres=["Sci-Fi", "Action"],
            directors=["Dir A"],
            countries=["United States"],
        ),
        # reference film for similar-to
        "ref-film": FilmMetadata(
            slug="ref-film",
            title="Parasite",
            year=2019,
            genres=["Thriller", "Drama"],
            directors=["Bong Joon-ho"],
            countries=["South Korea"],
        ),
        # candidates
        "cand-action-1985": FilmMetadata(
            slug="cand-action-1985",
            title="Action 1985",
            year=1985,
            genres=["Action"],
            directors=["Dir X"],
            countries=["United States"],
        ),
        "cand-action-1995": FilmMetadata(
            slug="cand-action-1995",
            title="Action 1995",
            year=1995,
            genres=["Action"],
            directors=["Dir Y"],
            countries=["United Kingdom"],
        ),
        "cand-drama-korea": FilmMetadata(
            slug="cand-drama-korea",
            title="K-Drama",
            year=2018,
            genres=["Drama"],
            directors=["Someone"],
            countries=["South Korea"],
        ),
        "cand-comedy": FilmMetadata(
            slug="cand-comedy",
            title="Comedy",
            year=2000,
            genres=["Comedy"],
            directors=["Funny"],
            countries=["France"],
        ),
    }
    return fixtures.get(slug) or FilmMetadata(slug=slug, title=slug, year=None)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(d))
    return d


def test_genre_constraint_filters_candidates(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-comedy", "cand-action-1995", "cand-action-1985"],
    )

    recs = recommend_for_user(
        "alice",
        k=5,
        prompt="2 more but from action genre",
        data_dir=data_dir,
        metadata_provider=_meta,
    )

    assert [r.film_id for r in recs] == ["cand-action-1995", "cand-action-1985"]


def test_year_bounds_constraint(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-action-1995", "cand-action-1985", "cand-comedy"],
    )

    recs = recommend_for_user(
        "alice",
        k=10,
        prompt="more between 1980 and 1990",
        data_dir=data_dir,
        metadata_provider=_meta,
    )

    assert [r.film_id for r in recs] == ["cand-action-1985"]


def test_country_constraint(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-action-1995", "cand-drama-korea", "cand-comedy"],
    )

    recs = recommend_for_user(
        "alice",
        k=10,
        prompt="5 more from South Korea cinema",
        data_dir=data_dir,
        metadata_provider=_meta,
    )

    assert [r.film_id for r in recs] == ["cand-drama-korea"]


def test_similar_to_constraint_filters_by_overlap(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=data_dir,
    )

    # Include the reference film in the search space for title resolution.
    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["ref-film", "cand-drama-korea", "cand-comedy"],
    )

    recs = recommend_for_user(
        "alice",
        k=10,
        prompt="5 more like Parasite",
        data_dir=data_dir,
        metadata_provider=_meta,
    )

    assert [r.film_id for r in recs] == ["cand-drama-korea"]
