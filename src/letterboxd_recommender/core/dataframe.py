from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, _default_data_dir


class DataframeBuildError(RuntimeError):
    pass


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
    return add_basic_features(df)


def add_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature engineering scaffold.

    Adds simple normalized positional features and a coarse interaction label.
    """

    out = df.copy()

    # Positions are 0-indexed; normalize to [0, 1] where possible.
    for col in ["watched_position", "watchlist_position"]:
        if col not in out.columns:
            raise DataframeBuildError(f"Missing column: {col}")

        max_pos = out[col].max(skipna=True)
        if pd.isna(max_pos) or max_pos == 0:
            out[f"{col}_norm"] = 0.0
        else:
            out[f"{col}_norm"] = out[col].fillna(max_pos + 1) / float(max_pos)

    def _label(row: pd.Series) -> str:
        if bool(row.get("in_watched")):
            return "watched"
        if bool(row.get("in_watchlist")):
            return "watchlist"
        return "unknown"

    out["interaction"] = out.apply(_label, axis=1)
    return out
