from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from letterboxd_recommender.core.dataframe import load_ingested_lists
from letterboxd_recommender.core.film_metadata import FilmMetadata, get_film_metadata


class RecommendationError(RuntimeError):
    pass


# A lightweight seed set of popular / canonical films.
#
# This is intentionally simple for M2.1 and avoids requiring a DB or
# a background job to build a candidate pool.
POPULAR_FILM_SLUGS: list[str] = [
    "the-godfather",
    "the-godfather-part-ii",
    "the-dark-knight",
    "pulp-fiction",
    "fight-club",
    "the-shawshank-redemption",
    "goodfellas",
    "the-lord-of-the-rings-the-fellowship-of-the-ring",
    "the-lord-of-the-rings-the-two-towers",
    "the-lord-of-the-rings-the-return-of-the-king",
    "spirited-away",
    "parasite",
    "inception",
    "interstellar",
    "the-matrix",
    "blade-runner",
    "blade-runner-2049",
    "alien",
    "aliens",
    "taxi-driver",
    "apocalypse-now",
    "seven",
    "whiplash",
    "la-la-land",
    "moonlight",
    "the-grand-budapest-hotel",
    "mad-max-fury-road",
    "no-country-for-old-men",
    "get-out",
    "the-social-network",
    "there-will-be-blood",
    "the-silence-of-the-lambs",
    "back-to-the-future",
    "the-thing",
    "the-prestige",
    "amelie",
    "city-of-god",
    "oldboy",
    "pan-s-labyrinth",
]


@dataclass(frozen=True)
class RecommendationItem:
    film_id: str
    title: str
    year: int | None
    blurb: str
    why: str


def recommend_for_user(
    username: str,
    *,
    k: int = 5,
    prompt: str | None = None,
    data_dir: Path | None = None,
    metadata_provider: callable | None = None,
) -> list[RecommendationItem]:
    """Return up to k recommended films for a user.

    M2.1 heuristic:
        - Start from a small seed list of popular films
        - Exclude anything already watched or on the watchlist
        - Return the first k remaining items

    Args:
        prompt: currently ignored (reserved for later milestones)
        metadata_provider: override for tests; signature (slug: str) -> FilmMetadata
    """

    if not username:
        raise RecommendationError("username is required")

    if k < 1:
        raise RecommendationError("k must be >= 1")

    lists = load_ingested_lists(username, data_dir=data_dir)
    exclude = set(lists.watched) | set(lists.watchlist)

    provider = metadata_provider or (lambda slug: get_film_metadata(slug, data_dir=data_dir))

    out: list[RecommendationItem] = []
    for slug in POPULAR_FILM_SLUGS:
        if slug in exclude:
            continue

        meta: FilmMetadata = provider(slug)
        title = meta.title or slug.replace("-", " ").title()

        out.append(
            RecommendationItem(
                film_id=slug,
                title=title,
                year=meta.year,
                blurb="A widely-loved film that's a good baseline pick.",
                why="It's popular on Letterboxd and not in your watched/watchlist.",
            )
        )

        if len(out) >= k:
            break

    # If we don't have k results, return what we have rather than erroring.
    # Later milestones can expand the candidate pool.
    return out
