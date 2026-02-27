from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from ..models import Article


def _text(elem: Optional[ET.Element]) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def fetch_rss(url: str, timeout_sec: int = 20) -> List[Article]:
    """軽量RSS/Atomパーサ（feedparser無しでも動くための最低限）。"""
    r = requests.get(url, timeout=timeout_sec, headers={"User-Agent": "sector-event-radar/0.1"})
    r.raise_for_status()
    xml = r.text

    root = ET.fromstring(xml)

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
