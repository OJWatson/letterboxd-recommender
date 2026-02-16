from __future__ import annotations

from letterboxd_recommender.core.film_metadata import parse_film_metadata_from_html


def test_parse_film_metadata_extracts_runtime_and_average_rating() -> None:
    html = """<!doctype html>
<html>
  <head>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Movie",
        "name": "Heat",
        "datePublished": "1995-12-15",
        "duration": "PT2H50M",
        "aggregateRating": {
          "@type": "AggregateRating",
          "ratingValue": 4.2
        },
        "genre": ["Crime", "Thriller"],
        "director": {"@type": "Person", "name": "Michael Mann"}
      }
    </script>
  </head>
</html>
"""

    meta = parse_film_metadata_from_html("heat", html)
    assert meta.slug == "heat"
    assert meta.title == "Heat"
    assert meta.year == 1995
    assert meta.runtime_minutes == 170
    assert meta.average_rating == 4.2
