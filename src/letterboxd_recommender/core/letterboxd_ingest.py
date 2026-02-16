from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

LETTERBOXD_BASE = "https://letterboxd.com"


class LetterboxdIngestError(RuntimeError):
    pass


class LetterboxdUserNotFound(LetterboxdIngestError):
    pass


@dataclass(frozen=True)
class IngestedLists:
    username: str
    watched: list[str]
    watchlist: list[str]


_FILM_PATH_RE = re.compile(r"^/film/(?P<slug>[^/]+)/?$")


def _rss_url(username: str, kind: str) -> str:
    if kind == "watched":
        # "Films" RSS is the canonical watched list feed.
        return f"{LETTERBOXD_BASE}/{username}/films/rss/"
    if kind == "watchlist":
        return f"{LETTERBOXD_BASE}/{username}/watchlist/rss/"
    if kind == "profile":
        return f"{LETTERBOXD_BASE}/{username}/rss/"
    raise ValueError(f"Unknown kind: {kind}")


def _extract_film_slug_from_link(link: str) -> str | None:
    try:
        path = httpx.URL(link).path
    except Exception:
        return None

    m = _FILM_PATH_RE.match(path)
    if m:
        return m.group("slug")

    # Also support user-scoped film log URLs:
    #   /<username>/film/<slug>/
    #   /<username>/film/<slug>/1/
    parts = [p for p in path.split("/") if p]
    if "film" in parts:
        idx = parts.index("film")
        if idx + 1 < len(parts):
            slug = parts[idx + 1].strip()
            if slug:
                return slug
    return None


def parse_letterboxd_rss(xml_text: str) -> list[str]:
    """Parse a Letterboxd RSS feed and return film slugs.

    Keeps order but removes duplicates.
    """

    root = ET.fromstring(xml_text)

    # RSS 2.0: <rss><channel><item> ... <link>https://letterboxd.com/film/slug/</link>
    slugs: list[str] = []
    seen: set[str] = set()

    for item in root.findall("./channel/item"):
        link_el = item.find("link")
        if link_el is None or not link_el.text:
            continue
        slug = _extract_film_slug_from_link(link_el.text.strip())
        if not slug or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)

    return slugs


def _default_data_dir() -> Path:
    return Path(os.environ.get("LETTERBOXD_RECOMMENDER_DATA_DIR", "data")).resolve()


def persist_ingest(result: IngestedLists, *, data_dir: Path | None = None) -> Path:
    """Persist ingested lists to disk as newline-delimited files.

    This keeps M0.2 lightweight without introducing a DB.
    """

    base = data_dir or _default_data_dir()
    user_dir = base / "users" / result.username
    user_dir.mkdir(parents=True, exist_ok=True)

    watched_path = user_dir / "watched.txt"
    watchlist_path = user_dir / "watchlist.txt"

    watched_path.write_text("\n".join(result.watched) + ("\n" if result.watched else ""))
    watchlist_path.write_text(
        "\n".join(result.watchlist) + ("\n" if result.watchlist else "")
    )

    return user_dir


def ingest_user(
    username: str,
    *,
    client: httpx.Client | None = None,
    timeout_s: float = 20.0,
) -> IngestedLists:
    """Fetch watched + watchlist film slugs for a Letterboxd user."""

    close_client = False
    if client is None:
        client = httpx.Client(
            headers={
                "User-Agent": "letterboxd-recommender/0.1 (+https://github.com/)",
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            },
            timeout=timeout_s,
            follow_redirects=True,
        )
        close_client = True

    try:
        try:
            watched_xml = _fetch_rss(client, _rss_url(username, "watched"))
            watchlist_xml = _fetch_rss(client, _rss_url(username, "watchlist"))
            watched = parse_letterboxd_rss(watched_xml)
            watchlist = parse_letterboxd_rss(watchlist_xml)
            return IngestedLists(username=username, watched=watched, watchlist=watchlist)
        except LetterboxdIngestError as e:
            # Cloudflare can block list-specific RSS endpoints from server-side clients.
            # Fall back to profile activity feed for watched titles.
            if "403" not in str(e):
                raise

            profile_xml = _fetch_rss(client, _rss_url(username, "profile"))
            watched = parse_letterboxd_rss(profile_xml)
            return IngestedLists(username=username, watched=watched, watchlist=[])
    finally:
        if close_client:
            client.close()


def _fetch_rss(client: httpx.Client, url: str) -> str:
    resp = client.get(url)

    if resp.status_code == 404:
        raise LetterboxdUserNotFound("User not found")
    if resp.status_code >= 400:
        raise LetterboxdIngestError(f"Letterboxd responded with {resp.status_code}")

    return resp.text
