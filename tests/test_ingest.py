from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from letterboxd_recommender.api import routes
from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists, ingest_user


def test_ingest_persists_and_returns_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    def fake_ingest_user(username: str):
        assert username == "alice"
        return IngestedLists(username="alice", watched=["alien", "heat"], watchlist=["dune"])

    monkeypatch.setattr(routes, "ingest_user", fake_ingest_user)

    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/users/alice/ingest")
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice", "watched_count": 2, "watchlist_count": 1}

    user_dir = tmp_path / "data" / "users" / "alice"
    assert (user_dir / "watched.txt").read_text() == "alien\nheat\n"
    assert (user_dir / "watchlist.txt").read_text() == "dune\n"


def test_ingest_user_falls_back_to_profile_rss_on_403() -> None:
    class FakeClient:
        def get(self, url: str):
            if url.endswith("/films/rss/") or url.endswith("/watchlist/rss/"):
                return httpx.Response(403, request=httpx.Request("GET", url))
            if url.endswith("/rss/"):
                xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item><link>https://letterboxd.com/alice/film/alien/</link></item>
    <item><link>https://letterboxd.com/alice/film/heat/1/</link></item>
  </channel>
</rss>
"""
                return httpx.Response(200, text=xml, request=httpx.Request("GET", url))
            return httpx.Response(500, request=httpx.Request("GET", url))

    result = ingest_user("alice", client=FakeClient())  # type: ignore[arg-type]
    assert result.username == "alice"
    assert result.watched == ["alien", "heat"]
    assert result.watchlist == []


def test_import_export_endpoint_persists_lists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(tmp_path / "data"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "diary.csv",
            (
                "Date,Name,Year,Letterboxd URI\n"
                "2025-01-01,Alien,1979,https://letterboxd.com/film/alien/\n"
                "2025-01-02,Heat,1995,https://letterboxd.com/alice/film/heat/1/\n"
            ),
        )
        zf.writestr(
            "watchlist.csv",
            "Name,Year,Letterboxd URI\nDune,2021,https://letterboxd.com/film/dune/\n",
        )
        zf.writestr("lists.csv", "Name\nWatched 2025\nTop 100\n")

    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/users/alice/import-export",
        files={"file": ("letterboxd-export.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["watched_count"] == 2
    assert body["watchlist_count"] == 1
    assert body["list_count"] == 2

    user_dir = tmp_path / "data" / "users" / "alice"
    assert (user_dir / "watched.txt").read_text() == "alien\nheat\n"
    assert (user_dir / "watchlist.txt").read_text() == "dune\n"
