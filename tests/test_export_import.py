from __future__ import annotations

import io
import zipfile

from letterboxd_recommender.core.export_import import import_letterboxd_export


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_import_letterboxd_zip_extracts_watched_watchlist_and_lists() -> None:
    data = _zip_bytes(
        {
            "diary.csv": (
                "Date,Name,Year,Letterboxd URI\n"
                "2025-01-01,Alien,1979,https://letterboxd.com/film/alien/\n"
                "2025-01-02,Heat,1995,https://letterboxd.com/alice/film/heat/1/\n"
            ),
            "watchlist.csv": (
                "Name,Year,Letterboxd URI\n"
                "Dune,2021,https://letterboxd.com/film/dune/\n"
                "Alien,1979,https://letterboxd.com/film/alien/\n"
            ),
            "lists.csv": (
                "Name,Tags\n"
                "Watched 2025,\n"
                "Top 100,\n"
                "Top 100,\n"
            ),
        }
    )

    imported = import_letterboxd_export("alice", "letterboxd-export.zip", data)
    assert imported.source == "zip"
    assert imported.lists.watched == ["alien", "heat"]
    assert imported.lists.watchlist == ["dune"]
    assert imported.list_count == 2


def test_import_letterboxd_single_csv() -> None:
    csv_data = (
        b"Date,Name,Year,Letterboxd URI\n"
        b"2025-01-01,Alien,1979,https://letterboxd.com/film/alien/\n"
    )

    imported = import_letterboxd_export("alice", "watched.csv", csv_data)
    assert imported.source == "csv"
    assert imported.lists.watched == ["alien"]
    assert imported.lists.watchlist == []
