from __future__ import annotations

from letterboxd_recommender.core.letterboxd_ingest import parse_letterboxd_rss


def test_parse_letterboxd_rss_extracts_unique_slugs_in_order() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example</title>
    <item>
      <title>Alien</title>
      <link>https://letterboxd.com/film/alien/</link>
    </item>
    <item>
      <title>Heat</title>
      <link>https://letterboxd.com/film/heat/</link>
    </item>
    <item>
      <title>Alien (duplicate)</title>
      <link>https://letterboxd.com/film/alien/</link>
    </item>
    <item>
      <title>Not a film</title>
      <link>https://letterboxd.com/alice/</link>
    </item>
  </channel>
</rss>
"""

    assert parse_letterboxd_rss(xml) == ["alien", "heat"]
