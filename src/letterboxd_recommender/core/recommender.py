from __future__ import annotations

from collections.abc import Callable
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


@dataclass(frozen=True)
class _UserProfile:
    genres: frozenset[str]
    decades: frozenset[str]
    directors: frozenset[str]


def _decade_label(year: int) -> str:
    decade = (year // 10) * 10
    return f"{decade}s"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / float(len(union))


def _build_user_profile(
    watched_slugs: list[str],
    *,
    provider: Callable[[str], FilmMetadata],
) -> _UserProfile:
    genres: set[str] = set()
    decades: set[str] = set()
    directors: set[str] = set()

    for slug in watched_slugs:
        meta = provider(slug)
        genres.update(meta.genres or [])
        directors.update(meta.directors or [])
        if meta.year is not None:
            decades.add(_decade_label(meta.year))

    return _UserProfile(
        genres=frozenset(genres),
        decades=frozenset(decades),
        directors=frozenset(directors),
    )


def _similarity_score(profile: _UserProfile, candidate: FilmMetadata) -> tuple[float, str]:
    """Compute a transparent similarity score + an explanation string.

    Uses a weighted Jaccard similarity over three coarse feature sets:
        - genres
        - decades (from year)
        - directors

    Returns (score, why).
    """

    cand_genres = set(candidate.genres or [])
    cand_directors = set(candidate.directors or [])
    cand_decades: set[str] = set()
    if candidate.year is not None:
        cand_decades.add(_decade_label(candidate.year))

    genre_sim = _jaccard(set(profile.genres), cand_genres)
    decade_sim = _jaccard(set(profile.decades), cand_decades)
    director_sim = _jaccard(set(profile.directors), cand_directors)

    # Keep weights simple + explicit.
    score = (0.5 * genre_sim) + (0.3 * director_sim) + (0.2 * decade_sim)

    overlaps: list[str] = []
    if profile.genres and cand_genres:
        g = sorted(set(profile.genres) & cand_genres)
        if g:
            overlaps.append(f"genres: {', '.join(g[:3])}")
    if profile.decades and cand_decades:
        d = sorted(set(profile.decades) & cand_decades)
        if d:
            overlaps.append(f"decade: {', '.join(d)}")
    if profile.directors and cand_directors:
        dr = sorted(set(profile.directors) & cand_directors)
        if dr:
            overlaps.append(f"director: {', '.join(dr[:2])}")

    if overlaps:
        why = "Similar to films you've watched (" + "; ".join(overlaps) + ")."
    else:
        why = "Popular pick; limited overlap with your watched profile."  # deterministic fallback

    return score, why


def recommend_for_user(
    username: str,
    *,
    k: int = 5,
    prompt: str | None = None,
    data_dir: Path | None = None,
    metadata_provider: Callable[[str], FilmMetadata] | None = None,
) -> list[RecommendationItem]:
    """Return up to k recommended films for a user.

    M2.2 heuristic:
        - Start from a small seed list of popular films
        - Exclude anything already watched or on the watchlist
        - Build a coarse "watched profile" from metadata (genres/decades/directors)
        - Rank remaining candidates by a simple similarity score

    Args:
        prompt: currently ignored (reserved for later milestones)
        metadata_provider: override for tests; signature (slug: str) -> FilmMetadata
    """

    if not username:
        raise RecommendationError("username is required")

    if k < 1:
        raise RecommendationError("k must be >= 1")

    _ = prompt  # reserved

    lists = load_ingested_lists(username, data_dir=data_dir)
    exclude = set(lists.watched) | set(lists.watchlist)

    provider = metadata_provider or (lambda slug: get_film_metadata(slug, data_dir=data_dir))
    profile = _build_user_profile(lists.watched, provider=provider)

    candidates: list[tuple[int, float, RecommendationItem]] = []

    for idx, slug in enumerate(POPULAR_FILM_SLUGS):
        if slug in exclude:
            continue

        meta = provider(slug)
        title = meta.title or slug.replace("-", " ").title()
        score, why = _similarity_score(profile, meta)

        candidates.append(
            (
                idx,
                score,
                RecommendationItem(
                    film_id=slug,
                    title=title,
                    year=meta.year,
                    blurb=(
                        "Recommended based on overlap with your watched profile "
                        "(genres/decades/directors)."
                    ),
                    why=why,
                ),
            )
        )

    # Deterministic ordering: score desc, then original popularity ordering.
    candidates.sort(key=lambda t: (-t[1], t[0]))

    out = [it for _, _, it in candidates[:k]]

    # If we don't have k results, return what we have rather than erroring.
    # Later milestones can expand the candidate pool.
    return out
