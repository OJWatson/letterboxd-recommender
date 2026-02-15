from __future__ import annotations

from pathlib import Path

import pytest

from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest
from letterboxd_recommender.core.recommender import recommend_for_user


def _meta_fixture(slug: str) -> FilmMetadata:
    # Deterministic, in-memory metadata fixture.
    fixtures: dict[str, FilmMetadata] = {
        # watched profile
        "watched-a": FilmMetadata(
            slug="watched-a",
            title="Watched A",
            year=1999,
            genres=["Sci-Fi", "Action"],
            directors=["The Wachowskis"],
        ),
        "watched-b": FilmMetadata(
            slug="watched-b",
            title="Watched B",
            year=2003,
            genres=["Crime"],
            directors=["Michael Mann"],
        ),
        # candidates
        "cand-1": FilmMetadata(
            slug="cand-1",
            title="Cand 1",
            year=1999,
            genres=["Sci-Fi"],
            directors=["Someone Else"],
        ),
        "cand-2": FilmMetadata(
            slug="cand-2",
            title="Cand 2",
            year=1972,
            genres=["Drama"],
            directors=["Another Person"],
        ),
    }
    return fixtures.get(slug) or FilmMetadata(slug=slug, title=slug, year=None)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(d))
    return d


def test_recommend_for_user_excludes_watched_and_watchlist(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=["cand-1"]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["watched-a", "cand-1", "cand-2"],
    )

    recs = recommend_for_user("alice", k=10, data_dir=data_dir, metadata_provider=_meta_fixture)
    assert [r.film_id for r in recs] == ["cand-2"]


def test_recommend_for_user_is_deterministic(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a", "watched-b"], watchlist=[]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-2", "cand-1"],
    )

    recs1 = recommend_for_user("alice", k=2, data_dir=data_dir, metadata_provider=_meta_fixture)
    recs2 = recommend_for_user("alice", k=2, data_dir=data_dir, metadata_provider=_meta_fixture)

    assert [r.film_id for r in recs1] == [r.film_id for r in recs2]


def test_ranking_changes_when_features_change(monkeypatch, data_dir: Path) -> None:
    persist_ingest(
        IngestedLists(username="alice", watched=["watched-a"], watchlist=[]),
        data_dir=data_dir,
    )

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["cand-2", "cand-1"],
    )

    # cand-1 overlaps on Sci-Fi + decade(1990s) => should rank above cand-2.
    recs = recommend_for_user("alice", k=2, data_dir=data_dir, metadata_provider=_meta_fixture)
    assert [r.film_id for r in recs] == ["cand-1", "cand-2"]

    def meta_changed(slug: str) -> FilmMetadata:
        if slug == "cand-1":
            # remove overlap
            return FilmMetadata(
                slug="cand-1",
                title="Cand 1",
                year=1950,
                genres=["Western"],
                directors=["Someone Else"],
            )
        return _meta_fixture(slug)

    recs_changed = recommend_for_user(
        "alice", k=2, data_dir=data_dir, metadata_provider=meta_changed
    )
    assert [r.film_id for r in recs_changed] == ["cand-2", "cand-1"]
