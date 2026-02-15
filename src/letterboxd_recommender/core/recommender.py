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
    score: float
    score_breakdown: dict[str, float]
    overlaps: dict[str, list[str]]


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


def _similarity_score(
    profile: _UserProfile, candidate: FilmMetadata
) -> tuple[float, str, dict[str, float], dict[str, list[str]]]:
    """Compute a transparent similarity score + explanation.

    Uses a weighted Jaccard similarity over three coarse feature sets:
        - genres
        - decades (from year)
        - directors

    Returns (score, why, score_breakdown, overlaps).
    """

    cand_genres = set(candidate.genres or [])
    cand_directors = set(candidate.directors or [])
    cand_decades: set[str] = set()
    if candidate.year is not None:
        cand_decades.add(_decade_label(candidate.year))

    profile_genres = set(profile.genres)
    profile_decades = set(profile.decades)
    profile_directors = set(profile.directors)

    genre_sim = _jaccard(profile_genres, cand_genres)
    decade_sim = _jaccard(profile_decades, cand_decades)
    director_sim = _jaccard(profile_directors, cand_directors)

    # Keep weights simple + explicit.
    score = (0.5 * genre_sim) + (0.3 * director_sim) + (0.2 * decade_sim)

    overlaps: dict[str, list[str]] = {
        "genres": sorted(profile_genres & cand_genres)[:3],
        "decades": sorted(profile_decades & cand_decades),
        "directors": sorted(profile_directors & cand_directors)[:2],
    }

    overlap_parts: list[str] = []
    if overlaps["genres"]:
        overlap_parts.append("genres: " + ", ".join(overlaps["genres"]))
    if overlaps["decades"]:
        overlap_parts.append("decade: " + ", ".join(overlaps["decades"]))
    if overlaps["directors"]:
        overlap_parts.append("director: " + ", ".join(overlaps["directors"]))

    breakdown = {
        "genres": genre_sim,
        "directors": director_sim,
        "decades": decade_sim,
        "weighted_score": score,
    }

    if overlap_parts:
        why = (
            f"Score {score:.3f}. Similar to films you've watched ("
            + "; ".join(overlap_parts)
            + ")."
        )
    else:
        why = f"Score {score:.3f}. Popular pick; limited overlap with your watched profile."

    return score, why, breakdown, overlaps


def _has_any_overlap(overlaps: dict[str, list[str]]) -> bool:
    return bool(overlaps.get("genres") or overlaps.get("directors") or overlaps.get("decades"))


def recommend_for_user(
    username: str,
    *,
    k: int = 5,
    prompt: str | None = None,
    data_dir: Path | None = None,
    metadata_provider: Callable[[str], FilmMetadata] | None = None,
) -> list[RecommendationItem]:
    """Return up to k recommended films for a user.

    M2.3 heuristic:
        - Start from a small seed list of popular films
        - Exclude anything already watched or on the watchlist
        - Build a coarse "watched profile" from metadata (genres/decades/directors)
        - Score candidates by weighted Jaccard similarity
        - Apply basic candidate filtering: if the profile has any features, prefer
          candidates with *some* overlap; if we can't fill k, fall back to popular picks.

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

    profile_is_empty = not (profile.genres or profile.decades or profile.directors)

    # Collect all candidates first so we can do a strict->relaxed two-pass filter
    # without losing deterministic ordering.
    candidates: list[tuple[int, float, bool, RecommendationItem]] = []

    for idx, slug in enumerate(POPULAR_FILM_SLUGS):
        if slug in exclude:
            continue

        meta = provider(slug)
        title = meta.title or slug.replace("-", " ").title()
        score, why, breakdown, overlaps = _similarity_score(profile, meta)
        has_overlap = _has_any_overlap(overlaps)

        candidates.append(
            (
                idx,
                score,
                has_overlap,
                RecommendationItem(
                    film_id=slug,
                    title=title,
                    year=meta.year,
                    blurb=(
                        "Recommended based on overlap with your watched profile "
                        "(genres/decades/directors)."
                    ),
                    why=why,
                    score=score,
                    score_breakdown=breakdown,
                    overlaps=overlaps,
                ),
            )
        )

    # Deterministic ordering: score desc, then original popularity ordering.
    candidates.sort(key=lambda t: (-t[1], t[0]))

    if profile_is_empty:
        # No filtering possible; just return popular picks (excluding watched/watchlist).
        chosen = [it for _, _, _, it in candidates[:k]]
        return chosen

    # Prefer overlap candidates first, then fall back to fill k if needed.
    overlap_first: list[RecommendationItem] = [it for _, _, has, it in candidates if has]
    if len(overlap_first) >= k:
        return overlap_first[:k]

    fallback: list[RecommendationItem] = overlap_first + [
        it for _, _, has, it in candidates if not has
    ]
    return fallback[:k]
