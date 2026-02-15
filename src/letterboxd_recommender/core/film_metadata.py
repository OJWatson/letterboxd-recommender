from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from letterboxd_recommender.core.letterboxd_ingest import LETTERBOXD_BASE, _default_data_dir


class FilmMetadataError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilmMetadata:
    slug: str
    title: str | None = None
    year: int | None = None
    directors: list[str] | None = None
    genres: list[str] | None = None
    countries: list[str] | None = None


_LD_JSON_RE = re.compile(
    r"<script[^>]+type=\"application/ld\+json\"[^>]*>(?P<json>.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)


def _film_cache_path(slug: str, *, data_dir: Path | None = None) -> Path:
    base = data_dir or _default_data_dir()
    return base / "films" / f"{slug}.json"


def load_cached_film_metadata(slug: str, *, data_dir: Path | None = None) -> FilmMetadata | None:
    path = _film_cache_path(slug, data_dir=data_dir)
    if not path.exists():
        return None

    raw = json.loads(path.read_text())
    return FilmMetadata(
        slug=raw.get("slug") or slug,
        title=raw.get("title"),
        year=raw.get("year"),
        directors=raw.get("directors"),
        genres=raw.get("genres"),
        countries=raw.get("countries"),
    )


def persist_film_metadata(meta: FilmMetadata, *, data_dir: Path | None = None) -> Path:
    path = _film_cache_path(meta.slug, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), indent=2, sort_keys=True) + "\n")
    return path


def fetch_film_page(
    slug: str, *, client: httpx.Client | None = None, timeout_s: float = 20.0
) -> str:
    close_client = False
    if client is None:
        client = httpx.Client(
            headers={
                "User-Agent": "letterboxd-recommender/0.1 (+https://github.com/)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout_s,
            follow_redirects=True,
        )
        close_client = True

    try:
        url = f"{LETTERBOXD_BASE}/film/{slug}/"
        resp = client.get(url)
        if resp.status_code >= 400:
            raise FilmMetadataError(f"Failed to fetch film page ({resp.status_code})")
        return resp.text
    finally:
        if close_client:
            client.close()


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_film_metadata_from_html(slug: str, html: str) -> FilmMetadata:
    """Extract basic metadata from a Letterboxd film HTML page.

    Strategy:
        - Prefer JSON-LD blocks of type Movie.

    This stays dependency-light (no BeautifulSoup).
    """

    candidates: list[dict[str, Any]] = []
    for m in _LD_JSON_RE.finditer(html):
        txt = m.group("json").strip()
        if not txt:
            continue
        try:
            payload = json.loads(txt)
        except json.JSONDecodeError:
            continue

        for item in _coerce_list(payload):
            if isinstance(item, dict):
                candidates.append(item)

    movie: dict[str, Any] | None = None
    for c in candidates:
        t = c.get("@type")
        if t == "Movie" or (isinstance(t, list) and "Movie" in t):
            movie = c
            break

    if movie is None:
        raise FilmMetadataError("No JSON-LD Movie metadata found")

    title = movie.get("name")

    year: int | None = None
    date_published = movie.get("datePublished")
    if isinstance(date_published, str) and len(date_published) >= 4:
        try:
            year = int(date_published[:4])
        except ValueError:
            year = None

    directors: list[str] = []
    for d in _coerce_list(movie.get("director")):
        if isinstance(d, dict) and isinstance(d.get("name"), str):
            directors.append(d["name"].strip())
        elif isinstance(d, str):
            directors.append(d.strip())

    genres: list[str] = []
    for g in _coerce_list(movie.get("genre")):
        if isinstance(g, str):
            genres.append(g.strip())

    countries: list[str] = []
    for c in _coerce_list(movie.get("countryOfOrigin")):
        if isinstance(c, dict) and isinstance(c.get("name"), str):
            countries.append(c["name"].strip())
        elif isinstance(c, str):
            countries.append(c.strip())

    # Normalise + de-dupe while preserving order.
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            if not it or it in seen:
                continue
            seen.add(it)
            out.append(it)
        return out

    return FilmMetadata(
        slug=slug,
        title=title.strip() if isinstance(title, str) else None,
        year=year,
        directors=_dedupe(directors) or None,
        genres=_dedupe(genres) or None,
        countries=_dedupe(countries) or None,
    )


def get_film_metadata(
    slug: str,
    *,
    client: httpx.Client | None = None,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> FilmMetadata:
    cached = None if refresh else load_cached_film_metadata(slug, data_dir=data_dir)
    if cached is not None:
        return cached

    html = fetch_film_page(slug, client=client)
    meta = parse_film_metadata_from_html(slug, html)
    persist_film_metadata(meta, data_dir=data_dir)
    return meta
