from __future__ import annotations

from pathlib import Path

from letterboxd_recommender.core.dataframe import (
    build_or_load_user_films_df,
    user_derived_data_paths,
    user_features_cache_key,
)
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, persist_ingest


def test_build_or_load_user_films_df_persists_versioned_cache(tmp_path: Path) -> None:
    lists = IngestedLists(username="alice", watched=["a", "b"], watchlist=["c"])
    persist_ingest(lists, data_dir=tmp_path)

    cache_key, df1 = build_or_load_user_films_df("alice", data_dir=tmp_path)

    expected_key = user_features_cache_key(lists)
    assert cache_key == expected_key

    derived = user_derived_data_paths("alice", cache_key=cache_key, data_dir=tmp_path)
    assert derived.user_films_df_path.exists()
    assert derived.manifest_path.exists()

    cache_key2, df2 = build_or_load_user_films_df("alice", data_dir=tmp_path)
    assert cache_key2 == cache_key

    # Round-tripping through JSON can change some dtypes (e.g. ints -> floats);
    # compare the logical content we care about.
    assert list(df2["film_slug"]) == list(df1["film_slug"])
    assert list(df2["interaction"]) == list(df1["interaction"])


def test_user_features_cache_key_changes_when_lists_change(tmp_path: Path) -> None:
    lists1 = IngestedLists(username="bob", watched=["x"], watchlist=[])
    lists2 = IngestedLists(username="bob", watched=["x", "y"], watchlist=[])

    persist_ingest(lists1, data_dir=tmp_path)
    key1, _ = build_or_load_user_films_df("bob", data_dir=tmp_path)

    persist_ingest(lists2, data_dir=tmp_path)
    key2, _ = build_or_load_user_films_df("bob", data_dir=tmp_path, force_rebuild=True)

    assert key2 != key1
