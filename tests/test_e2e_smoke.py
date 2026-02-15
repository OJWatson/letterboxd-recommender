from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from letterboxd_recommender.api.app import create_app
from letterboxd_recommender.core.film_metadata import FilmMetadata
from letterboxd_recommender.core.letterboxd_ingest import IngestedLists


def test_smoke_ingest_then_recommend(tmp_path: Path, monkeypatch) -> None:
    """Smoke-test the main user flow end-to-end (no external network).

    Covers:
      - /api/users/{username}/ingest persists watched + watchlist
      - /api/recommend returns recommendations excluding watched/watchlist

    We stub network-heavy functions (Letterboxd RSS fetch + film metadata fetch).
    """

    data_dir = tmp_path / "data"
    monkeypatch.setenv("LETTERBOXD_RECOMMENDER_DATA_DIR", str(data_dir))

    username = "alice"

    # 1) Stub ingest so we don't hit Letterboxd.
    monkeypatch.setattr(
        "letterboxd_recommender.api.routes.ingest_user",
        lambda u: IngestedLists(username=u, watched=["alien"], watchlist=["dune"]),
    )

    # 2) Keep candidate pool tiny and stub metadata so we don't hit Letterboxd.
    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.POPULAR_FILM_SLUGS",
        ["alien", "dune", "heat"],
    )

    by_slug: dict[str, FilmMetadata] = {
        "alien": FilmMetadata(
            slug="alien",
            title="Alien",
            year=1979,
            directors=["Ridley Scott"],
            genres=["Science Fiction", "Horror"],
        ),
        "dune": FilmMetadata(
            slug="dune",
            title="Dune",
            year=2021,
            directors=["Denis Villeneuve"],
            genres=["Science Fiction"],
        ),
        "heat": FilmMetadata(
            slug="heat",
            title="Heat",
            year=1995,
            directors=["Michael Mann"],
            genres=["Crime", "Thriller"],
        ),
    }

    monkeypatch.setattr(
        "letterboxd_recommender.core.recommender.get_film_metadata",
        lambda slug, **_: by_slug[slug],
    )

    app = create_app()
    client = TestClient(app)

    # Ingest
    resp = client.post(f"/api/users/{username}/ingest")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "username": username,
        "watched_count": 1,
        "watchlist_count": 1,
    }

    # Recommend
    resp2 = client.post("/api/recommend", json={"username": username, "k": 5})
    assert resp2.status_code == 200

    body2 = resp2.json()
    assert body2["username"] == username
    assert body2["session_id"]

    rec_slugs = [r["film_id"] for r in body2["recommendations"]]
    assert "alien" not in rec_slugs
    assert "dune" not in rec_slugs
    assert "heat" in rec_slugs
