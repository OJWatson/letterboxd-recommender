from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, _default_data_dir


class DataframeBuildError(RuntimeError):
    pass


EXPECTED_USER_FILMS_COLUMNS: Final[set[str]] = {
    "username",
    "film_slug",
    "in_watched",
    "in_watchlist",
    "watched_position",
    "watchlist_position",
}

SPEC_MIN_COLUMNS: Final[set[str]] = {
    "film_id",
    "title",
    "year",
    "director",
    "genres",
    "runtime",
    "country",
    "user_rating",
    "popularity_score",
    "average_rating",
    "keywords_tags",
}

# Bump this when the user-film dataframe schema or feature engineering changes.
USER_FILMS_CACHE_VERSION: Final[str] = "v1"


@dataclass(frozen=True)
class UserDataPaths:
    user_dir: Path
    watched_path: Path
    watchlist_path: Path


@dataclass(frozen=True)
class UserDerivedDataPaths:
    """Paths for derived/engineered features cached on disk."""

    user_dir: Path
    cache_dir: Path
    user_films_df_path: Path
    manifest_path: Path


def user_data_paths(username: str, *, data_dir: Path | None = None) -> UserDataPaths:
    base = data_dir or _default_data_dir()
    user_dir = base / "users" / username
    return UserDataPaths(
        user_dir=user_dir,
        watched_path=user_dir / "watched.txt",
        watchlist_path=user_dir / "watchlist.txt",
    )


def _slug_digest(slugs: list[str]) -> str:
    h = hashlib.sha256()
    for slug in slugs:
        h.update(slug.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def user_features_cache_key(lists: IngestedLists) -> str:
    """Compute a versioned cache key for derived user features.

    The key changes when either:
      - the ingested lists change (watched/watchlist slugs)
      - USER_FILMS_CACHE_VERSION is bumped

    This keeps cached derived features safe to reuse across runs.
    """

    watched_digest = _slug_digest(lists.watched)
    watchlist_digest = _slug_digest(lists.watchlist)

    h = hashlib.sha256()
    h.update(USER_FILMS_CACHE_VERSION.encode("utf-8"))
    h.update(b"\0")
    h.update(watched_digest.encode("utf-8"))
    h.update(b"\0")
    h.update(watchlist_digest.encode("utf-8"))

    return f"user-films-df-{USER_FILMS_CACHE_VERSION}-{h.hexdigest()[:16]}"


def user_derived_data_paths(
    username: str,
    *,
    cache_key: str,
    data_dir: Path | None = None,
) -> UserDerivedDataPaths:
    paths = user_data_paths(username, data_dir=data_dir)
    cache_dir = paths.user_dir / "cache" / cache_key
    return UserDerivedDataPaths(
        user_dir=paths.user_dir,
        cache_dir=cache_dir,
        user_films_df_path=cache_dir / "user_films_df.json",
        manifest_path=cache_dir / "manifest.json",
    )


def load_ingested_lists(username: str, *, data_dir: Path | None = None) -> IngestedLists:
    """Load previously persisted watched/watchlist slugs for a user."""

    paths = user_data_paths(username, data_dir=data_dir)
    if not paths.user_dir.exists():
        raise FileNotFoundError(f"No data found for user '{username}' in {paths.user_dir}")

    watched = (
        paths.watched_path.read_text().splitlines() if paths.watched_path.exists() else []
    )
    watchlist = (
        paths.watchlist_path.read_text().splitlines() if paths.watchlist_path.exists() else []
    )

    # Remove empties while preserving order.
    watched = [s for s in watched if s]
    watchlist = [s for s in watchlist if s]

    return IngestedLists(username=username, watched=watched, watchlist=watchlist)


def build_user_films_df(lists: IngestedLists) -> pd.DataFrame:
    """Construct the internal user-film dataframe.

    This dataframe is the stable interface between ingestion and recommendation.

    Rows are film slugs with membership in watched and watchlist.

    Notes:
        - `film_slug` is the Letterboxd slug (e.g., "parasite").
        - Positions reflect feed ordering (0-indexed; 0 is most-recent).
    """

    if not lists.username:
        raise DataframeBuildError("username is required")

    watched_pos = {slug: i for i, slug in enumerate(lists.watched)}
    watchlist_pos = {slug: i for i, slug in enumerate(lists.watchlist)}

    all_slugs = list(dict.fromkeys([*lists.watched, *lists.watchlist]))

    rows: list[dict[str, object]] = []
    for slug in all_slugs:
        wpos = watched_pos.get(slug)
        wlpos = watchlist_pos.get(slug)

        rows.append(
            {
                "username": lists.username,
                "film_slug": slug,
                # Spec-aligned base columns (filled from cached metadata later when available).
                "film_id": slug,
                "title": None,
                "year": None,
                "director": None,
                "genres": [],
                "runtime": None,
                "country": None,
                "user_rating": None,
                "popularity_score": None,
                "average_rating": None,
                "keywords_tags": [],
                "in_watched": wpos is not None,
                "in_watchlist": wlpos is not None,
                "watched_position": wpos,
                "watchlist_position": wlpos,
            }
        )

    df = pd.DataFrame.from_records(rows)
    validate_user_films_df(df)
    return add_basic_features(df)


def validate_user_films_df(df: pd.DataFrame) -> None:
    missing = EXPECTED_USER_FILMS_COLUMNS - set(df.columns)
    if missing:
        raise DataframeBuildError(f"Missing columns: {sorted(missing)}")


def _ensure_spec_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults: dict[str, object] = {
        "film_id": out["film_slug"] if "film_slug" in out.columns else None,
        "title": None,
        "year": None,
        "director": None,
        "genres": [[] for _ in range(len(out))],
        "runtime": None,
        "country": None,
        "user_rating": None,
        "popularity_score": None,
        "average_rating": None,
        "keywords_tags": [[] for _ in range(len(out))],
    }

    for col in SPEC_MIN_COLUMNS:
        if col not in out.columns:
            out[col] = defaults[col]

    return out


@dataclass(frozen=True)
class FeatureEngineeringConfig:
    """Configuration for simple feature engineering.

    This is intentionally lightweight; later milestones can add richer metadata
    (genres, cast, directors, etc.) and more advanced encoders.
    """

    # Fill value for missing positions when normalizing; if None, uses (max_pos + 1).
    missing_position_fill: float | None = None


def add_basic_features(
    df: pd.DataFrame, *, config: FeatureEngineeringConfig | None = None
) -> pd.DataFrame:
    """Feature engineering scaffold.

    Adds a few deterministic features that will remain stable over time:

    - Normalized positional features for watched/watchlist ordering
    - A coarse interaction label
    - A simple candidate flag for recommendation filtering
    """

    cfg = config or FeatureEngineeringConfig()

    out = df.copy()
    validate_user_films_df(out)
    out = _ensure_spec_columns(out)

    # Positions are 0-indexed; normalize to ~[0, 1]. Missing positions are filled
    # slightly beyond the max position.
    for col in ["watched_position", "watchlist_position"]:
        max_pos = out[col].max(skipna=True)
        if pd.isna(max_pos) or max_pos == 0:
            out[f"{col}_norm"] = 0.0
            continue

        fill = cfg.missing_position_fill
        if fill is None:
            fill = float(max_pos) + 1.0

        out[f"{col}_norm"] = out[col].fillna(fill) / float(max_pos)

    out["is_candidate"] = out["in_watchlist"] & (~out["in_watched"])

    def _label(row: pd.Series) -> str:
        if bool(row.get("in_watched")):
            return "watched"
        if bool(row.get("in_watchlist")):
            return "watchlist"
        return "unknown"

    out["interaction"] = out.apply(_label, axis=1)
    return out


def load_cached_user_films_df(
    username: str,
    *,
    data_dir: Path | None = None,
) -> tuple[str, pd.DataFrame] | None:
    """Load the cached user-film dataframe if present.

    Returns:
        (cache_key, df) if a cache exists for the current ingested lists,
        otherwise None.
    """

    lists = load_ingested_lists(username, data_dir=data_dir)
    cache_key = user_features_cache_key(lists)
    derived = user_derived_data_paths(username, cache_key=cache_key, data_dir=data_dir)

    if not derived.user_films_df_path.exists():
        return None

    df = pd.read_json(derived.user_films_df_path, orient="records")
    validate_user_films_df(df)
    df = _ensure_spec_columns(df)
    return cache_key, df


def persist_user_films_df(
    df: pd.DataFrame,
    *,
    username: str,
    cache_key: str,
    data_dir: Path | None = None,
) -> UserDerivedDataPaths:
    derived = user_derived_data_paths(username, cache_key=cache_key, data_dir=data_dir)
    derived.cache_dir.mkdir(parents=True, exist_ok=True)

    # JSON is used to preserve basic dtypes (bool/int/float) without requiring
    # optional parquet backends.
    df.to_json(derived.user_films_df_path, orient="records", indent=2)

    manifest = {
        "username": username,
        "cache_key": cache_key,
        "cache_version": USER_FILMS_CACHE_VERSION,
        "row_count": int(df.shape[0]),
        "columns": list(df.columns),
    }
    derived.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return derived


def build_or_load_user_films_df(
    username: str,
    *,
    data_dir: Path | None = None,
    force_rebuild: bool = False,
) -> tuple[str, pd.DataFrame]:
    """Load the derived user-film dataframe, building and caching if needed."""

    lists = load_ingested_lists(username, data_dir=data_dir)
    cache_key = user_features_cache_key(lists)

    if not force_rebuild:
        cached = load_cached_user_films_df(username, data_dir=data_dir)
        if cached is not None:
            return cached

    df = build_user_films_df(lists)
    persist_user_films_df(df, username=username, cache_key=cache_key, data_dir=data_dir)
    return cache_key, df


def build_user_films_df_for_username(
    username: str, *, data_dir: Path | None = None
) -> pd.DataFrame:
    """Convenience helper: load persisted lists and build the internal dataframe.

    Uses a versioned on-disk cache to avoid recomputing derived features.
    """

    _, df = build_or_load_user_films_df(username, data_dir=data_dir)
    return df
