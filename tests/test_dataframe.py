from __future__ import annotations

from pathlib import Path

import pandas as pd

from letterboxd_recommender.core.dataframe import build_user_films_df, load_ingested_lists
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def test_build_user_films_df_union_and_features() -> None:
    lists = IngestedLists(
        username="alice",
        watched=["a", "b"],
        watchlist=["b", "c"],
    )

    df = build_user_films_df(lists)

    assert set(df.columns) >= {
        "username",
        "film_slug",
        "in_watched",
        "in_watchlist",
        "watched_position",
        "watchlist_position",
        "watched_position_norm",
        "watchlist_position_norm",
        "interaction",
    }

    assert list(df["film_slug"]) == ["a", "b", "c"]

    b = df.set_index("film_slug").loc["b"]
    assert bool(b["in_watched"]) is True
    assert bool(b["in_watchlist"]) is True

    assert df["watched_position_norm"].dtype == float
    assert df["watchlist_position_norm"].dtype == float


def test_load_ingested_lists_roundtrip(tmp_path: Path) -> None:
    lists = IngestedLists(
        username="bob",
        watched=["x", "y"],
        watchlist=["z"],
    )

    persist_ingest(lists, data_dir=tmp_path)
    loaded = load_ingested_lists("bob", data_dir=tmp_path)

    assert loaded == lists

    df = build_user_films_df(loaded)
    assert isinstance(df, pd.DataFrame)
    assert set(df["film_slug"]) == {"x", "y", "z"}
