"""test_ics_display.py — ICS表示品質の回帰テスト

工程2（iPhoneでの見栄え改善）のDoDを守るテスト:
1. SUMMARYにカテゴリプレフィックスが付く
2. DESCRIPTIONが全イベントに出力される
3. DESCRIPTIONの改行エスケープが正しい（二重エスケープしない）
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sector_event_radar.ics import events_to_ics, _format_summary, _format_description, _escape
from sector_event_radar.models import Event


# ── Fixtures ──────────────────────────────────────────

def _make_event(
    category: str = "shock",
    title: str = "NVIDIA Export Ban",
    risk_score: int = 50,
    confidence: float = 0.80,
    sector_tags: list = None,
    source_url: str = "https://example.com/article",
    evidence: str = "effective March 15, 2026",
) -> Event:
    return Event(
        canonical_key=f"test:{category}:nvidia:2026-03-15",
        title=title,
        start_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        category=category,
        sector_tags=sector_tags or ["NVDA", "semis"],
        risk_score=risk_score,
        confidence=confidence,
        source_name="test",
        source_url=source_url,
        source_id="test:1",
        evidence=evidence,
        action="add",
    )


# ── Test 1: SUMMARYにカテゴリプレフィックスが付く ─────

@pytest.mark.parametrize("category,prefix", [
    ("macro", "[MACRO]"),
    ("bellwether", "[BW]"),
    ("flows", "[FLOW]"),
    ("shock", "[SHOCK]"),
])
def test_summary_has_category_prefix(category, prefix):
    ev = _make_event(category=category, title="Test Event")
    summary = _format_summary(ev)
    assert summary.startswith(prefix), f"Expected '{prefix}' prefix, got: '{summary}'"
    assert "Test Event" in summary


def test_summary_prefix_in_ics_output():
    """ICS全体出力の中でSUMMARY行にプレフィックスが含まれる"""
    ev = _make_event(category="macro", title="US CPI")
    ics = events_to_ics([ev])
    # SUMMARY行を探す（foldingされている可能性があるのでunfold）
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:[MACRO] US CPI" in unfolded


# ── Test 2: DESCRIPTIONが全イベントに出力される ──────

def test_description_always_present():
    """evidenceが"from database"でもDESCRIPTIONは出力される"""
    ev = _make_event(evidence="from database")
    ics = events_to_ics([ev])
    assert "DESCRIPTION:" in ics


def test_description_contains_risk_and_confidence():
    ev = _make_event(risk_score=75, confidence=0.92)
    desc = _format_description(ev)
    assert "Risk: 75/100" in desc
    assert "Confidence: 0.92" in desc


def test_description_contains_tags():
    ev = _make_event(sector_tags=["NVDA", "ASML"])
    desc = _format_description(ev)
    assert "Tags: NVDA, ASML" in desc


def test_description_contains_source_url():
    ev = _make_event(source_url="https://example.com/news")
    desc = _format_description(ev)
    assert "Source: https://example.com/news" in desc


def test_description_contains_evidence():
    ev = _make_event(evidence="announced on March 15, 2026")
    desc = _format_description(ev)
    assert "Evidence: announced on March 15, 2026" in desc


# ── Test 3: 改行エスケープが正しい ────────────────────

def test_description_newline_escape_not_doubled():
    """_format_description → _escape の結果が \\n（1個）であり、
    \\\\n（2個＝二重エスケープ）にならないこと。"""
    ev = _make_event()
    desc = _format_description(ev)  # 本物の\nで結合
    escaped = _escape(desc)         # ICS仕様の\\nに変換

    # \\n（バックスラッシュ1個 + n）が含まれる
    assert "\\n" in escaped, f"Expected \\n in escaped description, got: {escaped!r}"
    # \\\\n（バックスラッシュ2個 + n）が含まれない
    assert "\\\\n" not in escaped, f"Double-escaped newline found: {escaped!r}"


def test_ics_description_line_has_correct_newlines():
    """ICS全体出力のDESCRIPTION行が正しい改行表現を持つ"""
    ev = _make_event()
    ics = events_to_ics([ev])
    # unfold
    unfolded = ics.replace("\r\n ", "")

    # DESCRIPTION行を抽出
    desc_line = ""
    for line in unfolded.split("\r\n"):
        if line.startswith("DESCRIPTION:"):
            desc_line = line
            break

    assert desc_line, "DESCRIPTION line not found in ICS output"
    # \\n（ICS改行表現）がある
    assert "\\n" in desc_line
    # \\\\n（二重エスケープ）がない
    assert "\\\\n" not in desc_line
