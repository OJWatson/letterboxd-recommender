from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RefinementIntent = Literal[
    "more",  # ask for more recommendations
    "refine",  # adjust constraints without explicit "more"
]


@dataclass(frozen=True)
class RefinementConstraints:
    """Parsed constraints from a natural-language refinement prompt.

    This milestone intentionally keeps the schema small and deterministic.
    M3.3 applies these constraints; M3.2 only parses.
    """

    k: int | None = None

    include_genres: tuple[str, ...] = ()

    year_min: int | None = None
    year_max: int | None = None

    include_countries: tuple[str, ...] = ()

    similar_to_title: str | None = None


@dataclass(frozen=True)
class RefinementParseResult:
    intent: RefinementIntent
    constraints: RefinementConstraints
    raw_prompt: str


_GENRE_SPLIT_RE = re.compile(r"\s*(?:,|/|\band\b|\bor\b)\s*", flags=re.IGNORECASE)


def _normalise_token(token: str) -> str:
    token = token.strip().lower()
    token = re.sub(r"\s+", " ", token)
    return token


def _parse_k(prompt: str) -> int | None:
    match = re.match(r"^\s*(\d{1,2})\b", prompt)
    if not match:
        return None

    k = int(match.group(1))
    if 1 <= k <= 20:
        return k
    return None


def _parse_year_bounds(prompt: str) -> tuple[int | None, int | None]:
    p = prompt.lower()

    between = re.search(r"\b(?:between|from)\s+(\d{4})\s+(?:and|to)\s+(\d{4})\b", p)
    if between:
        y1 = int(between.group(1))
        y2 = int(between.group(2))
        lo, hi = sorted((y1, y2))
        return lo, hi

    in_year = re.search(r"\bin\s+(\d{4})\b", p)
    if in_year:
        y = int(in_year.group(1))
        return y, y

    before = re.search(r"\b(?:before|earlier\s+than|prior\s+to)\s+(\d{4})\b", p)
    if before:
        y = int(before.group(1))
        return None, y - 1

    after = re.search(r"\bafter\s+(\d{4})\b", p)
    if after:
        y = int(after.group(1))
        return y + 1, None

    since = re.search(r"\b(?:since|from)\s+(\d{4})\b", p)
    if since:
        y = int(since.group(1))
        return y, None

    return None, None


def _parse_similar_to_title(raw_prompt: str) -> str | None:
    # Use the raw prompt to preserve capitalization of titles.
    lowered = raw_prompt.lower()
    idx = lowered.find(" like ")
    if idx == -1:
        # Also support prompts starting with "like ..."
        if lowered.startswith("like "):
            idx = 0
        else:
            return None

    title = raw_prompt[idx + len(" like ") :].strip() if idx else raw_prompt[len("like ") :].strip()

    # Stop at common clause boundaries.
    for boundary in (" but ", " with ", " from ", " in "):
        bidx = title.lower().find(boundary)
        if bidx != -1:
            title = title[:bidx].strip()
            break

    title = title.strip(" \"'“”‘’.,;:!?")
    return title or None


def _parse_include_genres(prompt: str) -> tuple[str, ...]:
    p = prompt.lower()

    # e.g. "action genre", "sci-fi genre"
    match = re.search(r"\b([a-z][a-z\-\s/,&]+?)\s+genre\b", p)
    if not match:
        # e.g. "from action" or "in action" (heuristic: only if "genre" appears anywhere)
        if "genre" not in p:
            return ()

        match = re.search(r"\b(?:from|in)\s+([a-z][a-z\-\s/,&]+)\b", p)
        if not match:
            return ()

    chunk = match.group(1)
    chunk = _normalise_token(chunk)

    # If we matched a whole clause (e.g. "more but from action"), keep only
    # the tail after common prompt glue words.
    glue_words = {"more", "but", "from", "only", "just", "please"}
    words = [w for w in chunk.split(" ") if w]
    while words and words[0] in glue_words:
        words.pop(0)
    chunk = " ".join(words)

    parts = [_normalise_token(tok) for tok in _GENRE_SPLIT_RE.split(chunk) if tok.strip()]
    # Drop generic words.
    parts = [p for p in parts if p not in {"a", "an", "the", "movies", "films"}]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for item in parts:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)

    return tuple(out)


def _parse_include_countries(prompt: str) -> tuple[str, ...]:
    p = prompt.lower()

    # Only parse countries when explicitly hinted; avoids clashes with "from action genre".
    if "country" not in p and "cinema" not in p:
        return ()

    # e.g. "from South Korea", "korean cinema"
    match = re.search(r"\bfrom\s+([a-z][a-z\s]+?)\b(?:\s+(?:films|movies|cinema|country)\b|$)", p)
    if match:
        country = _normalise_token(match.group(1))
        return (country,) if country else ()

    match = re.search(r"\b([a-z][a-z\s]+?)\s+cinema\b", p)
    if match:
        country = _normalise_token(match.group(1))
        return (country,) if country else ()

    return ()


def parse_refinement_prompt(prompt: str | None) -> RefinementParseResult:
    """Parse a natural-language refinement prompt into a deterministic schema.

    This is deliberately "LLM-light": a small rule-based parser that extracts
    common constraints (genre/year/country/similar-to) and the desired number of
    results.
    """

    raw = (prompt or "").strip()
    if not raw:
        return RefinementParseResult(
            intent="refine",
            constraints=RefinementConstraints(),
            raw_prompt=raw,
        )

    lowered = raw.lower()

    intent: RefinementIntent = "more" if "more" in lowered else "refine"

    k = _parse_k(raw)
    year_min, year_max = _parse_year_bounds(raw)
    include_genres = _parse_include_genres(raw)
    include_countries = _parse_include_countries(raw)
    similar_to_title = _parse_similar_to_title(raw)

    return RefinementParseResult(
        intent=intent,
        constraints=RefinementConstraints(
            k=k,
            include_genres=include_genres,
            year_min=year_min,
            year_max=year_max,
            include_countries=include_countries,
            similar_to_title=similar_to_title,
        ),
        raw_prompt=raw,
    )
