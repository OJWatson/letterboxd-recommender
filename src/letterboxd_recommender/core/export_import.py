from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from letterboxd_recommender.core.letterboxd_ingest import IngestedLists


class LetterboxdExportImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportedExportData:
    lists: IngestedLists
    list_count: int
    source: str


def _normalise_header(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _extract_slug_from_url(value: str) -> str | None:
    txt = (value or "").strip()
    if not txt:
        return None

    # Accept full URLs and path-ish values.
    parts = [p for p in txt.split("/") if p]
    if "film" in parts:
        idx = parts.index("film")
        if idx + 1 < len(parts):
            slug = parts[idx + 1].strip()
            if slug:
                return slug
    return None


def _parse_csv_rows(csv_bytes: bytes) -> list[dict[str, str]]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    return [dict(row) for row in reader]


def _collect_slugs(rows: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for row in rows:
        norm = {_normalise_header(k): (v or "") for k, v in row.items()}
        candidates = [
            norm.get("letterboxd uri", ""),
            norm.get("url", ""),
            norm.get("link", ""),
            norm.get("letterboxd url", ""),
        ]
        slug = None
        for c in candidates:
            slug = _extract_slug_from_url(c)
            if slug:
                break

        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)

    return out


def _all_csv_from_zip(content: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.rsplit("/", 1)[-1]
            if not name.lower().endswith(".csv"):
                continue
            out[name.lower()] = zf.read(info)
    return out


def import_letterboxd_export(
    username: str, filename: str, content: bytes
) -> ImportedExportData:
    if not username.strip():
        raise LetterboxdExportImportError("username is required")
    if not content:
        raise LetterboxdExportImportError("empty file upload")

    lname = filename.lower()
    csv_files: dict[str, bytes]
    source = "csv"

    if lname.endswith(".zip"):
        csv_files = _all_csv_from_zip(content)
        source = "zip"
    elif lname.endswith(".csv"):
        csv_files = {lname.rsplit("/", 1)[-1]: content}
    else:
        raise LetterboxdExportImportError("Unsupported file type. Upload .zip or .csv")

    if not csv_files:
        raise LetterboxdExportImportError("No CSV files found in upload")

    watched_sources = ["diary.csv", "watched.csv", "ratings.csv", "reviews.csv"]
    watched: list[str] = []
    seen_watched: set[str] = set()

    for key in watched_sources:
        rows = _parse_csv_rows(csv_files[key]) if key in csv_files else []
        for slug in _collect_slugs(rows):
            if slug in seen_watched:
                continue
            seen_watched.add(slug)
            watched.append(slug)

    watchlist: list[str] = []
    if "watchlist.csv" in csv_files:
        watchlist = _collect_slugs(_parse_csv_rows(csv_files["watchlist.csv"]))

    # Remove watchlist entries already watched.
    watched_set = set(watched)
    watchlist = [s for s in watchlist if s not in watched_set]

    list_count = 0
    if "lists.csv" in csv_files:
        list_rows = _parse_csv_rows(csv_files["lists.csv"])
        # Unique list names if available, else row count.
        names = []
        for row in list_rows:
            norm = {_normalise_header(k): (v or "") for k, v in row.items()}
            name = norm.get("name", "").strip()
            if name:
                names.append(name)
        list_count = len(dict.fromkeys(names)) if names else len(list_rows)

    if not watched and not watchlist and not list_count:
        # If it's a single CSV, try parsing it as watched fallback.
        if len(csv_files) == 1:
            only = next(iter(csv_files.values()))
            watched = _collect_slugs(_parse_csv_rows(only))

    if not watched and not watchlist:
        raise LetterboxdExportImportError(
            "Could not find any film entries in export. "
            "Expected files such as watched.csv / diary.csv / watchlist.csv."
        )

    return ImportedExportData(
        lists=IngestedLists(username=username, watched=watched, watchlist=watchlist),
        list_count=list_count,
        source=source,
    )
