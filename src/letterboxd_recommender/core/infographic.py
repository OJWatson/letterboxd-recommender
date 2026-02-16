from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from letterboxd_recommender.core.dataframe import load_ingested_lists
from letterboxd_recommender.core.film_metadata import FilmMetadata, get_film_metadata

ListKind = Literal["watched", "watchlist", "all"]


@dataclass(frozen=True)
class InfographicSummary:
    username: str
    list_kind: ListKind
    film_count: int
    top_genres: list[tuple[str, int]]
    top_decades: list[tuple[str, int]]
    top_directors: list[tuple[str, int]]
    runtime_distribution: list[tuple[str, int]]
    average_runtime_minutes: float | None
    average_user_rating: float | None
    average_global_rating: float | None


def _decade_label(year: int) -> str:
    decade = (year // 10) * 10
    return f"{decade}s"


def _runtime_bucket_label(runtime_minutes: int) -> str:
    if runtime_minutes < 90:
        return "<90m"
    if runtime_minutes < 110:
        return "90-109m"
    if runtime_minutes < 130:
        return "110-129m"
    if runtime_minutes < 150:
        return "130-149m"
    return "150m+"


def build_infographic_summary(
    username: str,
    *,
    list_kind: ListKind = "watched",
    top_n: int = 10,
    data_dir: Path | None = None,
    metadata_provider: Callable[[str], FilmMetadata] | None = None,
) -> InfographicSummary:
    """Build a simple 'infographic' summary (genres, decades, directors).

    By default this summarizes watched films only.

    Args:
        metadata_provider: Optional dependency injection to make testing easy.
            Signature: (slug) -> FilmMetadata
    """

    lists = load_ingested_lists(username, data_dir=data_dir)

    if list_kind == "watched":
        slugs = lists.watched
    elif list_kind == "watchlist":
        slugs = lists.watchlist
    elif list_kind == "all":
        slugs = list(dict.fromkeys([*lists.watched, *lists.watchlist]))
    else:
        raise ValueError(f"Unknown list_kind: {list_kind}")

    provider = metadata_provider or (lambda slug: get_film_metadata(slug, data_dir=data_dir))

    genre_counts: Counter[str] = Counter()
    decade_counts: Counter[str] = Counter()
    director_counts: Counter[str] = Counter()
    runtime_counts: Counter[str] = Counter()
    runtimes: list[int] = []
    global_ratings: list[float] = []

    for slug in slugs:
        meta = provider(slug)

        for g in meta.genres or []:
            genre_counts[g] += 1

        if meta.year is not None:
            decade_counts[_decade_label(meta.year)] += 1

        for d in meta.directors or []:
            director_counts[d] += 1

        if meta.runtime_minutes is not None:
            runtimes.append(meta.runtime_minutes)
            runtime_counts[_runtime_bucket_label(meta.runtime_minutes)] += 1

        if meta.average_rating is not None:
            global_ratings.append(meta.average_rating)

    runtime_bucket_order = ["<90m", "90-109m", "110-129m", "130-149m", "150m+"]
    runtime_distribution = [
        (label, runtime_counts.get(label, 0))
        for label in runtime_bucket_order
        if runtime_counts.get(label, 0) > 0
    ]

    avg_runtime = (
        (sum(runtimes) / float(len(runtimes)))
        if runtimes
        else None
    )
    avg_global = (
        (sum(global_ratings) / float(len(global_ratings)))
        if global_ratings
        else None
    )

    return InfographicSummary(
        username=username,
        list_kind=list_kind,
        film_count=len(slugs),
        top_genres=genre_counts.most_common(top_n),
        top_decades=decade_counts.most_common(top_n),
        top_directors=director_counts.most_common(top_n),
        runtime_distribution=runtime_distribution,
        average_runtime_minutes=avg_runtime,
        # User-assigned ratings are not available from RSS ingest v1.
        average_user_rating=None,
        average_global_rating=avg_global,
    )
