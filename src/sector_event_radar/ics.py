from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional
from uuid import uuid4

from .models import Event

# ── カテゴリ → iPhoneカレンダー表示用プレフィックス ──
CATEGORY_PREFIX = {
    "macro": "[MACRO]",
    "bellwether": "[BW]",
    "flows": "[FLOW]",
    "shock": "[SHOCK]",
}


def _fmt_utc(dt: datetime) -> str:
    # RFC5545 basic format
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        # naiveはそのまま扱うと危険。呼び出し側でvalidate済み想定だが、保険でUTCにみなす
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_line(line: str) -> str:
    """RFC5545 §3.1: 長い行を75オクテットで折り返す。
    最初の行は75オクテット、継続行はSPACE+74オクテット。
    UTF-8マルチバイトの途中で切らない。
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    parts = []
    pos = 0
    first = True

    while pos < len(encoded):
        max_bytes = 75 if first else 74
        end = min(pos + max_bytes, len(encoded))
        chunk = encoded[pos:end]

        # UTF-8マルチバイトの途中で切れないよう調整
        if end < len(encoded):
            while len(chunk) > 0:
                try:
                    chunk.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    chunk = chunk[:-1]

        text = chunk.decode("utf-8")
        if first:
            parts.append(text)
            first = False
        else:
            parts.append(" " + text)
        pos += len(chunk)

    return "\r\n".join(parts)


def _format_summary(ev: Event) -> str:
    """カテゴリプレフィックス付きタイトルを生成。
    例: [MACRO] US CPI, [BW] NVDA Earnings, [SHOCK] Export Controls
    """
    prefix = CATEGORY_PREFIX.get(ev.category, f"[{ev.category.upper()}]")
    return f"{prefix} {ev.title}"


def _format_description(ev: Event) -> str:
    """iPhoneカレンダーで「何が・どの程度重要で・どこソースか」が即わかる定型DESCRIPTION。

    フォーマット:
        Risk: 50/100 | Confidence: 0.80
        Tags: NVDA, semis
        Source: https://example.com/...
        ---
        Evidence: "effective March 15, 2026"
    """
    parts: List[str] = []

    # 1行目: 重要度
    parts.append(f"Risk: {ev.risk_score}/100 | Confidence: {ev.confidence:.2f}")

    # 2行目: タグ
    if ev.sector_tags:
        parts.append(f"Tags: {', '.join(ev.sector_tags)}")

    # 3行目: ソースURL
    if ev.source_url:
        parts.append(f"Source: {ev.source_url}")

    # 区切り + evidence
    if hasattr(ev, "evidence") and ev.evidence and ev.evidence != "from database":
        parts.append("---")
        parts.append(f"Evidence: {ev.evidence}")

    return "\n".join(parts)


def events_to_ics(events: Iterable[Event], cal_name: str = "Sector Event Radar") -> str:
    now = datetime.now(timezone.utc)
    dtstamp = _fmt_utc(now)

    lines: List[str] = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//SectorEventRadar//EN")
    lines.append(f"X-WR-CALNAME:{_escape(cal_name)}")

    for ev in events:
        uid = ev.canonical_key or str(uuid4())
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{_escape(uid)}")
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"SUMMARY:{_escape(_format_summary(ev))}")
        lines.append(f"DTSTART:{_fmt_utc(ev.start_at)}")
        if ev.end_at:
            lines.append(f"DTEND:{_fmt_utc(ev.end_at)}")
        if ev.source_url:
            lines.append(f"URL:{_escape(str(ev.source_url))}")
        # 定型DESCRIPTION
        lines.append(f"DESCRIPTION:{_escape(_format_description(ev))}")
        # category / tags
        lines.append(f"CATEGORIES:{_escape(ev.category)}")
        if ev.sector_tags:
            lines.append(f"X-SECTOR-TAGS:{_escape(','.join(ev.sector_tags))}")
        # cancelled handling
        if ev.action == "cancel":
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # RFC5545: 各行をline foldingしてCRLFで結合
    folded = [_fold_line(line) for line in lines]
    return "\r\n".join(folded) + "\r\n"
