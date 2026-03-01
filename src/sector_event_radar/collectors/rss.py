"""RSS/Atom フィード取得器。

feedparser があれば堅牢パース（Atom/名前空間/不正XML対応）。
なければ ElementTree で最低限のRSS2/Atomパース（既存動作を維持）。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from ..models import Article

logger = logging.getLogger(__name__)

try:
    import feedparser

    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False


def fetch_rss(url: str, timeout_sec: int = 20) -> List[Article]:
    """RSSまたはAtomフィードを取得してArticleリストを返す。

    feedparser利用可能時: feedparserでパース（堅牢、Atom/namespace/不正XML対応）
    feedparser未インストール時: ElementTree直パース（既存動作）
    """
    r = requests.get(url, timeout=timeout_sec, headers={"User-Agent": "sector-event-radar/0.1"})
    r.raise_for_status()
    raw = r.text

    if _HAS_FEEDPARSER:
        return _parse_with_feedparser(raw)
    else:
        return _parse_with_etree(raw)


def _parse_with_feedparser(raw: str) -> List[Article]:
    """feedparserで堅牢パース。RSS2/Atom/RDF/不正XMLすべて対応。"""
    d = feedparser.parse(raw)

    if d.bozo and not d.entries:
        # パースエラーかつエントリ0件の場合のみ警告
        logger.warning("feedparser bozo error (0 entries): %s", d.bozo_exception)
        return []

    if d.bozo and d.entries:
        # パースエラーだがエントリは取れた場合（部分的に壊れたXML）
        logger.info(
            "feedparser bozo but %d entries recovered: %s",
            len(d.entries), d.bozo_exception,
        )

    out: List[Article] = []
    for entry in d.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        published = entry.get("published", "") or entry.get("updated", "")
        published = published.strip() if published else ""

        # body: summary → content → description の優先順
        body = ""
        if entry.get("summary"):
            body = entry["summary"].strip()
        elif entry.get("content"):
            body = entry["content"][0].get("value", "").strip()
        elif entry.get("description"):
            body = entry["description"].strip()

        if not link:
            continue

        out.append(Article(title=title, body=body, url=link, published=published))

    return out


# ── ElementTree フォールバック（feedparser未インストール時）──


def _text(elem: Optional[ET.Element]) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _parse_with_etree(raw: str) -> List[Article]:
    """ElementTree直パース（既存動作維持用フォールバック）。"""
    root = ET.fromstring(raw)

    # RSS2: <rss><channel><item>...
    items = root.findall(".//item")
    out: List[Article] = []
    if items:
        for it in items:
            title = _text(it.find("title"))
            link = _text(it.find("link"))
            pub = _text(it.find("pubDate")) or _text(it.find("{http://purl.org/dc/elements/1.1/}date"))
            desc = _text(it.find("description"))
            if not link:
                continue
            out.append(Article(title=title, body=desc, url=link, published=pub))
        return out

    # Atom: <feed><entry>...
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for en in entries:
        title = _text(en.find("{http://www.w3.org/2005/Atom}title"))
        pub = _text(en.find("{http://www.w3.org/2005/Atom}updated")) or _text(en.find("{http://www.w3.org/2005/Atom}published"))
        link = ""
        for l in en.findall("{http://www.w3.org/2005/Atom}link"):
            if l.attrib.get("rel", "alternate") == "alternate":
                link = l.attrib.get("href", "") or link
        summary = _text(en.find("{http://www.w3.org/2005/Atom}summary"))
        if link:
            out.append(Article(title=title, body=summary, url=link, published=pub))
    return out
