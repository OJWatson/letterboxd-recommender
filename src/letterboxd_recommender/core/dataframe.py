from __future__ import annotations

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


@dataclass(frozen=True)
class UserDataPaths:
    user_dir: Path
    watched_path: Path
    watchlist_path: Path


def user_data_paths(username: str, *, data_dir: Path | None = None) -> UserDataPaths:
    base = data_dir or _default_data_dir()
    user_dir = base / "users" / username
    return UserDataPaths(
        user_dir=user_dir,
        watched_path=user_dir / "watched.txt",
        watchlist_path=user_dir / "watchlist.txt",
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


def build_user_films_df_for_username(
    username: str, *, data_dir: Path | None = None
) -> pd.DataFrame:
    """Convenience helper: load persisted lists and build the internal dataframe."""

    lists = load_ingested_lists(username, data_dir=data_dir)
    return build_user_films_df(lists)
