"""Phase 1 追加テスト: ICS line folding, run_daily部分失敗, claude_extract パーサー"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

from sector_event_radar.ics import events_to_ics, _fold_line
from sector_event_radar.models import Event
from sector_event_radar.llm.claude_extract import _parse_tool_output


# ── ICS line folding ──────────────────────────────────

def test_fold_line_short():
    """75バイト以下はそのまま"""
    line = "SUMMARY:FOMC Statement"
    assert _fold_line(line) == line


def test_fold_line_long_ascii():
    """75バイト超のASCII行が正しく折り返される"""
    line = "DESCRIPTION:" + "A" * 100
    folded = _fold_line(line)
    parts = folded.split("\r\n")
    assert len(parts) > 1
    # 最初の行は75バイト以下
    assert len(parts[0].encode("utf-8")) <= 75
    # 継続行はSPACEで始まる
    for p in parts[1:]:
        assert p.startswith(" ")
        assert len(p.encode("utf-8")) <= 75


def test_fold_line_multibyte():
    """日本語（マルチバイト）の途中で切れない"""
    line = "SUMMARY:" + "あ" * 30  # 各3バイト = 90バイト + "SUMMARY:" = 98バイト超
    folded = _fold_line(line)
    # 折り返し後もデコード可能（マルチバイトの途中で切れていない）
    unfolded = folded.replace("\r\n ", "")
    assert unfolded == line


def test_ics_output_uses_crlf():
    """ICS出力がCRLFを使っていること"""
    ev = Event(
        canonical_key="macro:us:fomc:2026-03-18",
        title="FOMC",
        start_at=datetime(2026, 3, 18, 18, 0, tzinfo=timezone.utc),
        category="macro",
        sector_tags=[],
        risk_score=50,
        confidence=1.0,
        source_name="test",
        source_url=None,
        source_id="t1",
        evidence="FOMC statement March 18.",
        action="add",
    )
    ics = events_to_ics([ev])
    assert "\r\n" in ics
    # bare LF（CRLFでないLF）がないことを確認
    stripped = ics.replace("\r\n", "")
    assert "\n" not in stripped


def test_ics_long_evidence_folded():
    """長いevidenceがline foldingされること"""
    long_evidence = "X" * 250  # 250文字 → DESCRIPTION行が75バイト超
    ev = Event(
        canonical_key="shock:global:test:2026-03-05",
        title="Test Event",
        start_at=datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
        category="shock",
        sector_tags=[],
        risk_score=50,
        confidence=0.8,
        source_name="test",
        source_url=None,
        source_id="t1",
        evidence=long_evidence,
        action="add",
    )
    ics = events_to_ics([ev])
    # DESCRIPTION行が折り返されている（継続行のSPACEが存在する）
    assert "\r\n " in ics


# ── claude_extract tool output parser ────────────────

def test_parse_tool_output_valid():
    """正常なAnthropic APIレスポンスからtool出力を取り出せる"""
    response = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_123",
                "name": "emit_events",
                "input": {
                    "events": [
                        {
                            "title": "US CPI Release",
                            "start_at": "2026-03-12T08:30:00-05:00",
                            "category": "macro",
                            "sector_tags": [],
                            "risk_score": 60,
                            "confidence": 0.95,
                            "evidence": "CPI will be released on March 12, 2026.",
                            "action": "add",
                        }
                    ]
                },
            }
        ]
    }
    result = _parse_tool_output(response)
    assert result is not None
    assert len(result["events"]) == 1
    assert result["events"][0]["title"] == "US CPI Release"


def test_parse_tool_output_empty_events():
    """日時なし→events=[]のレスポンスをパースできる"""
    response = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_456",
                "name": "emit_events",
                "input": {"events": []},
            }
        ]
    }
    result = _parse_tool_output(response)
    assert result is not None
    assert result["events"] == []


def test_parse_tool_output_no_tool_block():
    """tool_useブロックがない場合はNone"""
    response = {
        "content": [
            {"type": "text", "text": "I found no events."}
        ]
    }
    result = _parse_tool_output(response)
    assert result is None


def test_parse_tool_output_wrong_tool_name():
    """別名のtoolブロックは無視"""
    response = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_789",
                "name": "other_tool",
                "input": {"data": "something"},
            }
        ]
    }
    result = _parse_tool_output(response)
    assert result is None


# ── run_daily 部分失敗 ────────────────────────────────

def test_run_daily_partial_failure_still_generates_ics(tmp_path: Path):
    """RSSが全滅してもOPEXはDBに入り、ICSが生成される"""
    from sector_event_radar.run_daily import run_daily

    # config
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "keywords: {}\n"
        "prefilter: {stage_a_threshold: 6.0, stage_b_top_k: 30}\n"
        "macro_title_map: {}\n"
        "sources:\n"
        "  rss:\n"
        "    - name: broken_feed\n"
        "      url: http://nonexistent.invalid/feed.xml\n",
        encoding="utf-8",
    )
    db_path = str(tmp_path / "events.db")
    ics_dir = str(tmp_path / "ics")

    # dry_run=True でLLM呼び出しをスキップ、RSSも接続できないが例外で止まらない
    summary = run_daily(str(cfg_path), db_path, ics_dir, dry_run=True)

    # OPEXイベントは生成されているはず
    assert summary["collected"]["computed"] > 0

    # ICSファイルが生成されている
    ics_all = Path(ics_dir) / "sector_events_all.ics"
    assert ics_all.exists()
    content = ics_all.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content
    assert "OPEX" in content

    # エラーは記録されているがクラッシュしていない
    assert isinstance(summary["errors"], list)
