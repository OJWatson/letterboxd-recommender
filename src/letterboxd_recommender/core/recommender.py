from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from letterboxd_recommender.core.dataframe import load_ingested_lists
from letterboxd_recommender.core.film_metadata import (
    FilmMetadata,
    FilmMetadataError,
    get_film_metadata,
)
from letterboxd_recommender.core.nlp import RefinementConstraints, parse_refinement_prompt


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


# Scoring weights for the transparent, heuristic recommender.
GENRE_WEIGHT = 0.5
DIRECTOR_WEIGHT = 0.3
DECADE_WEIGHT = 0.2
PROFILE_SAMPLE_LIMIT = 50
METADATA_FAILURE_FAST_FALLBACK_THRESHOLD = 6


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
class FeatureContribution:
    feature: str
    similarity: float
    weight: float
    contribution: float
    overlaps: list[str]


@dataclass(frozen=True)
class _UserProfile:
    genres: frozenset[str]
    decades: frozenset[str]
    directors: frozenset[str]


def _fallback_recommendation(slug: str) -> RecommendationItem:
    return RecommendationItem(
        film_id=slug,
        title=slug.replace("-", " ").title(),
        year=None,
        blurb="Fallback recommendation from curated popular pool.",
        why=(
            "Metadata was unavailable for detailed matching; "
            "this is a safe fallback pick."
        ),
        score=0.0,
        score_breakdown={
            "genres": 0.0,
            "directors": 0.0,
            "decades": 0.0,
            "genres_contribution": 0.0,
            "directors_contribution": 0.0,
            "decades_contribution": 0.0,
            "weighted_score": 0.0,
        },
        overlaps={"genres": [], "directors": [], "decades": []},
    )


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

    metadata_failures = 0
    for slug in watched_slugs[:PROFILE_SAMPLE_LIMIT]:
        try:
            meta = provider(slug)
        except FilmMetadataError:
            # Ignore unavailable metadata to keep recommendation flow alive.
            metadata_failures += 1
            if metadata_failures >= METADATA_FAILURE_FAST_FALLBACK_THRESHOLD:
                break
            continue
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
    score = (
        (GENRE_WEIGHT * genre_sim)
        + (DIRECTOR_WEIGHT * director_sim)
        + (DECADE_WEIGHT * decade_sim)
    )

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
        "genres_contribution": GENRE_WEIGHT * genre_sim,
        "directors_contribution": DIRECTOR_WEIGHT * director_sim,
        "decades_contribution": DECADE_WEIGHT * decade_sim,
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


def top_feature_contributions(
    username: str,
    film_id: str,
    *,
    data_dir: Path | None = None,
    metadata_provider: Callable[[str], FilmMetadata] | None = None,
    top_n: int = 3,
) -> tuple[float, list[FeatureContribution]]:
    """Return the weighted score + top contributing features for a candidate film.

    This is used by the evaluation endpoint (M2.4).

    Args:
        top_n: number of contributions to return (sorted by contribution desc).
    """

    if not username:
        raise RecommendationError("username is required")

    if not film_id:
        raise RecommendationError("film_id is required")

    if top_n < 1:
        raise RecommendationError("top_n must be >= 1")

    lists = load_ingested_lists(username, data_dir=data_dir)
    provider = metadata_provider or (lambda slug: get_film_metadata(slug, data_dir=data_dir))

    profile = _build_user_profile(lists.watched, provider=provider)
    candidate = provider(film_id)

    score, _, breakdown, overlaps = _similarity_score(profile, candidate)

    contributions = [
        FeatureContribution(
            feature="genres",
            similarity=breakdown["genres"],
            weight=GENRE_WEIGHT,
            contribution=breakdown["genres_contribution"],
            overlaps=overlaps.get("genres", []),
        ),
        FeatureContribution(
            feature="directors",
            similarity=breakdown["directors"],
            weight=DIRECTOR_WEIGHT,
            contribution=breakdown["directors_contribution"],
            overlaps=overlaps.get("directors", []),
        ),
        FeatureContribution(
            feature="decades",
            similarity=breakdown["decades"],
            weight=DECADE_WEIGHT,
            contribution=breakdown["decades_contribution"],
            overlaps=overlaps.get("decades", []),
        ),
    ]

    contributions.sort(key=lambda item: (-item.contribution, item.feature))
    return score, contributions[:top_n]


def _normalise_text_token(value: str) -> str:
    value = value.strip().lower()
    value = " ".join(value.split())
    return value


def _slugify_title(title: str) -> str:
    txt = _normalise_text_token(title)
    out: list[str] = []
    for ch in txt:
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-"}:
            out.append("-")
    slug = "".join(out)
    slug = "-".join([p for p in slug.split("-") if p])
    return slug


def _resolve_similar_to_slug(
    title_or_slug: str,
    *,
    candidates: list[str],
    provider: Callable[[str], FilmMetadata],
) -> str | None:
    # Try direct slug match first.
    token = _normalise_text_token(title_or_slug)
    if token in {c.lower() for c in candidates}:
        for c in candidates:
            if c.lower() == token:
                return c

    wanted = _normalise_text_token(title_or_slug)

    # Try to find by title within our known candidate set.
    for slug in candidates:
        try:
            meta = provider(slug)
        except FilmMetadataError:
            continue
        if meta.title and _normalise_text_token(meta.title) == wanted:
            return slug

    # Last attempt: slugify the title.
    slugified = _slugify_title(title_or_slug)
    if slugified in candidates:
        return slugified

    return None


def _matches_constraints(
    meta: FilmMetadata,
    constraints: RefinementConstraints,
    *,
    similar_to: FilmMetadata | None = None,
) -> bool:
    # Genre filter: require at least one of the requested genres.
    if constraints.include_genres:
        cand = {_normalise_text_token(g) for g in (meta.genres or []) if g}
        wanted = {_normalise_text_token(g) for g in constraints.include_genres if g}
        if not (cand & wanted):
            return False

    # Year bounds: inclusive.
    if constraints.year_min is not None or constraints.year_max is not None:
        if meta.year is None:
            return False
        if constraints.year_min is not None and meta.year < constraints.year_min:
            return False
        if constraints.year_max is not None and meta.year > constraints.year_max:
            return False

    # Country filter: require at least one match.
    if constraints.include_countries:
        cand = {_normalise_text_token(c) for c in (meta.countries or []) if c}
        wanted = {_normalise_text_token(c) for c in constraints.include_countries if c}
        if not (cand & wanted):
            return False

    # Similar-to: require some overlap with the reference film.
    if similar_to is not None:
        ref_genres = {_normalise_text_token(g) for g in (similar_to.genres or []) if g}
        ref_directors = {_normalise_text_token(d) for d in (similar_to.directors or []) if d}
        ref_decades: set[str] = set()
        if similar_to.year is not None:
            ref_decades.add(_decade_label(similar_to.year))

        cand_genres = {_normalise_text_token(g) for g in (meta.genres or []) if g}
        cand_directors = {_normalise_text_token(d) for d in (meta.directors or []) if d}
        cand_decades: set[str] = set()
        if meta.year is not None:
            cand_decades.add(_decade_label(meta.year))

        has_overlap = bool(
            (ref_genres & cand_genres)
            or (ref_directors & cand_directors)
            or (ref_decades & cand_decades)
        )
        if not has_overlap:
            return False

    return True


def recommend_for_user(
    username: str,
    *,
    k: int = 5,
    prompt: str | None = None,
    exclude_slugs: set[str] | None = None,
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
        exclude_slugs: optional additional slugs to exclude (e.g. already recommended
            within the current session).
        metadata_provider: override for tests; signature (slug: str) -> FilmMetadata
    """

    if not username:
        raise RecommendationError("username is required")

    if k < 1:
        raise RecommendationError("k must be >= 1")

    parsed = parse_refinement_prompt(prompt)
    constraints = parsed.constraints
    if constraints.k is not None:
        k = constraints.k

    lists = load_ingested_lists(username, data_dir=data_dir)
    exclude = set(lists.watched) | set(lists.watchlist)
    if exclude_slugs:
        exclude |= set(exclude_slugs)

    provider = metadata_provider or (lambda slug: get_film_metadata(slug, data_dir=data_dir))

    similar_meta: FilmMetadata | None = None
    if constraints.similar_to_title:
        search_space = list(dict.fromkeys([*lists.watched, *lists.watchlist, *POPULAR_FILM_SLUGS]))
        resolved = _resolve_similar_to_slug(
            constraints.similar_to_title,
            candidates=search_space,
            provider=provider,
        )
        if resolved:
            try:
                similar_meta = provider(resolved)
                exclude.add(resolved)
            except FilmMetadataError:
                similar_meta = None

    profile = _build_user_profile(lists.watched, provider=provider)

    profile_is_empty = not (profile.genres or profile.decades or profile.directors)

    # Collect all candidates first so we can do a strict->relaxed two-pass filter
    # without losing deterministic ordering.
    candidates: list[tuple[int, float, bool, RecommendationItem]] = []
    metadata_failures = 0

    for idx, slug in enumerate(POPULAR_FILM_SLUGS):
        if slug in exclude:
            continue

        try:
            meta = provider(slug)
        except FilmMetadataError:
            # Fallback candidate when metadata endpoints are blocked.
            metadata_failures += 1
            candidates.append(
                (
                    idx,
                    0.0,
                    False,
                    _fallback_recommendation(slug),
                )
            )
            if metadata_failures >= METADATA_FAILURE_FAST_FALLBACK_THRESHOLD:
                for j in range(idx + 1, len(POPULAR_FILM_SLUGS)):
                    rem_slug = POPULAR_FILM_SLUGS[j]
                    if rem_slug in exclude:
                        continue
                    candidates.append((j, 0.0, False, _fallback_recommendation(rem_slug)))
                break
            continue
        if not _matches_constraints(meta, constraints, similar_to=similar_meta):
            continue

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
