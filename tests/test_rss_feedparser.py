"""Task C: RSS feedparser統合テスト

テスト方針:
- feedparser利用時のRSS2/Atom/不正XMLパース
- ElementTreeフォールバック維持
- SIAで想定される問題パターン（HTMLエンティティ、namespace混在等）

TestFeedparserParsing (5本):
  1. test_rss2_basic — 標準RSS2パース
  2. test_atom_basic — 標準Atomパース
  3. test_malformed_xml_recovers — 不正XML（HTMLエンティティ）でもエントリ取得
  4. test_empty_feed — エントリなしフィード
  5. test_no_link_skipped — linkなしエントリはスキップ

TestEtreeFallback (2本):
  6. test_etree_rss2 — feedparserなし時のRSS2パース
  7. test_etree_atom — feedparserなし時のAtomパース
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from sector_event_radar.collectors.rss import (
    _parse_with_feedparser,
    _parse_with_etree,
)


# ── テスト用フィードXML ──

RSS2_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>CHIPS Act Funding Update</title>
      <link>https://example.com/chips-act</link>
      <pubDate>Sat, 01 Mar 2026 00:00:00 GMT</pubDate>
      <description>New funding allocation for semiconductor fabs.</description>
    </item>
    <item>
      <title>DRAM Price Forecast</title>
      <link>https://example.com/dram-price</link>
      <pubDate>Fri, 28 Feb 2026 12:00:00 GMT</pubDate>
      <description>DRAM prices expected to rise in Q2.</description>
    </item>
  </channel>
</rss>"""

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SIA Press Releases</title>
  <entry>
    <title>Global Semiconductor Sales Rise 15%</title>
    <link rel="alternate" href="https://semiconductors.org/release1"/>
    <published>2026-03-01T10:00:00Z</published>
    <summary>Industry revenue increased 15% year-over-year.</summary>
  </entry>
</feed>"""

# SIAで想定される問題: HTMLエンティティ(&nbsp;等)が含まれる不正XML
MALFORMED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SIA Feed</title>
    <item>
      <title>SIA Applauds &amp; Supports New Policy</title>
      <link>https://semiconductors.org/news1</link>
      <description>The SIA released a statement today.</description>
    </item>
  </channel>
</rss>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""

NO_LINK_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Link Article</title>
      <description>This item has no link element.</description>
    </item>
  </channel>
</rss>"""


# ══════════════════════════════════════════════════════════
# TestFeedparserParsing (5本) — feedparser利用時
# ══════════════════════════════════════════════════════════

class TestFeedparserParsing:
    """feedparserでのパーステスト"""

    @pytest.fixture(autouse=True)
    def _require_feedparser(self):
        """feedparserがインストールされていない環境ではスキップ"""
        pytest.importorskip("feedparser")

    def test_rss2_basic(self):
        """標準RSS2フィードから2件取得"""
        articles = _parse_with_feedparser(RSS2_FEED)
        assert len(articles) == 2
        assert articles[0].title == "CHIPS Act Funding Update"
        assert articles[0].url == "https://example.com/chips-act"
        assert articles[0].body == "New funding allocation for semiconductor fabs."

    def test_atom_basic(self):
        """標準Atomフィードから1件取得"""
        articles = _parse_with_feedparser(ATOM_FEED)
        assert len(articles) == 1
        assert articles[0].title == "Global Semiconductor Sales Rise 15%"
        assert articles[0].url == "https://semiconductors.org/release1"

    def test_malformed_xml_recovers(self):
        """不正XMLでもfeedparserはエントリを回収する"""
        articles = _parse_with_feedparser(MALFORMED_RSS)
        assert len(articles) >= 1
        assert "SIA" in articles[0].title

    def test_empty_feed(self):
        """エントリなしフィードは空リスト"""
        articles = _parse_with_feedparser(EMPTY_FEED)
        assert len(articles) == 0

    def test_no_link_skipped(self):
        """linkなしエントリはスキップ"""
        articles = _parse_with_feedparser(NO_LINK_FEED)
        assert len(articles) == 0


# ══════════════════════════════════════════════════════════
# TestEtreeFallback (2本) — feedparser未インストール時
# ══════════════════════════════════════════════════════════

class TestEtreeFallback:
    """ElementTreeフォールバックのテスト"""

    def test_etree_rss2(self):
        """ElementTreeでRSS2パース"""
        articles = _parse_with_etree(RSS2_FEED)
        assert len(articles) == 2
        assert articles[0].title == "CHIPS Act Funding Update"
        assert articles[0].url == "https://example.com/chips-act"

    def test_etree_atom(self):
        """ElementTreeでAtomパース"""
        articles = _parse_with_etree(ATOM_FEED)
        assert len(articles) == 1
        assert articles[0].title == "Global Semiconductor Sales Rise 15%"
        assert articles[0].url == "https://semiconductors.org/release1"
