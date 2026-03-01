"""Task C-2: Federal Register BIS コレクターテスト

TestExtractEventsFromDocument (6本):
  1. test_effective_date_creates_event — effective_on → 施行日イベント
  2. test_comment_deadline_creates_event — comments_close_on → 締切日イベント
  3. test_both_dates_creates_two_events — 両方 → 2件
  4. test_no_dates_creates_no_events — 日付なし → 0件（ノイズ殺し）
  5. test_missing_title_skipped — titleなし → スキップ
  6. test_event_fields_correct — イベントフィールドの正確性

TestFetchFederalRegisterBisEvents (3本):
  7. test_api_success — 正常レスポンス → イベント生成
  8. test_api_error_returns_empty — HTTPエラー → errors記録、events空
  9. test_empty_results — 結果0件 → events空

TestParseDate (2本):
  10. test_valid_date — YYYY-MM-DD → UTC datetime
  11. test_invalid_date_raises — 不正文字列 → ValueError
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from sector_event_radar.collectors.federal_register import (
    _extract_events_from_document,
    _parse_date,
    fetch_federal_register_bis_events,
)


# ── テスト用ドキュメント ──

DOC_EFFECTIVE = {
    "title": "Export Control Reform: Entity List Additions",
    "abstract": "The Bureau of Industry and Security adds entities to the Entity List.",
    "html_url": "https://www.federalregister.gov/documents/2026/03/01/2026-12345/entity-list",
    "publication_date": "2026-03-01",
    "effective_on": "2026-04-01",
    "comments_close_on": None,
    "type": "Rule",
    "document_number": "2026-12345",
}

DOC_COMMENT = {
    "title": "Proposed Rule: Semiconductor Equipment Controls",
    "abstract": "BIS proposes additional controls on semiconductor manufacturing equipment.",
    "html_url": "https://www.federalregister.gov/documents/2026/03/01/2026-67890/semi-controls",
    "publication_date": "2026-03-01",
    "effective_on": None,
    "comments_close_on": "2026-05-01",
    "type": "Proposed Rule",
    "document_number": "2026-67890",
}

DOC_BOTH = {
    "title": "Final Rule: Advanced Computing Controls",
    "abstract": "BIS finalizes restrictions on advanced computing ICs.",
    "html_url": "https://www.federalregister.gov/documents/2026/03/01/2026-11111/advanced-computing",
    "publication_date": "2026-03-01",
    "effective_on": "2026-04-15",
    "comments_close_on": "2026-03-31",
    "type": "Rule",
    "document_number": "2026-11111",
}

DOC_NO_DATES = {
    "title": "Notice: BIS Advisory Committee Meeting",
    "abstract": "Notice of open meeting.",
    "html_url": "https://www.federalregister.gov/documents/2026/03/01/2026-22222/meeting",
    "publication_date": "2026-03-01",
    "effective_on": None,
    "comments_close_on": None,
    "type": "Notice",
    "document_number": "2026-22222",
}

DOC_NO_TITLE = {
    "title": "",
    "abstract": "Some abstract",
    "html_url": "https://example.com/doc",
    "effective_on": "2026-04-01",
    "document_number": "2026-33333",
}


# ══════════════════════════════════════════════════════════
# TestExtractEventsFromDocument (6本)
# ══════════════════════════════════════════════════════════

class TestExtractEventsFromDocument:

    def test_effective_date_creates_event(self):
        events = _extract_events_from_document(DOC_EFFECTIVE)
        assert len(events) == 1
        assert "BIS Rule Effective" in events[0].title
        assert events[0].start_at == datetime(2026, 4, 1, tzinfo=timezone.utc)

    def test_comment_deadline_creates_event(self):
        events = _extract_events_from_document(DOC_COMMENT)
        assert len(events) == 1
        assert "BIS Comment Deadline" in events[0].title
        assert events[0].start_at == datetime(2026, 5, 1, tzinfo=timezone.utc)

    def test_both_dates_creates_two_events(self):
        events = _extract_events_from_document(DOC_BOTH)
        assert len(events) == 2
        titles = [e.title for e in events]
        assert any("Effective" in t for t in titles)
        assert any("Deadline" in t for t in titles)

    def test_no_dates_creates_no_events(self):
        events = _extract_events_from_document(DOC_NO_DATES)
        assert len(events) == 0

    def test_missing_title_skipped(self):
        events = _extract_events_from_document(DOC_NO_TITLE)
        assert len(events) == 0

    def test_event_fields_correct(self):
        events = _extract_events_from_document(DOC_EFFECTIVE)
        ev = events[0]
        assert ev.category == "shock"
        assert ev.confidence == 0.9
        assert ev.risk_score == 70
        assert ev.source_name == "federal_register"
        assert ev.source_id == "fr:2026-12345:effective"
        assert "semiconductor" in ev.sector_tags
        assert "regulation" in ev.sector_tags
        assert ev.end_at is None
        assert str(ev.source_url) == DOC_EFFECTIVE["html_url"]


# ══════════════════════════════════════════════════════════
# TestFetchFederalRegisterBisEvents (3本)
# ══════════════════════════════════════════════════════════

class TestFetchFederalRegisterBisEvents:

    @patch("sector_event_radar.collectors.federal_register.requests.get")
    def test_api_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [DOC_EFFECTIVE, DOC_COMMENT],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        events, errors = fetch_federal_register_bis_events("2026-03-01", "2026-09-01")
        assert len(events) == 2
        assert len(errors) == 0

    @patch("sector_event_radar.collectors.federal_register.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        import requests as req; mock_get.side_effect = req.exceptions.ConnectionError("Connection refused")

        events, errors = fetch_federal_register_bis_events("2026-03-01", "2026-09-01")
        assert len(events) == 0
        assert len(errors) == 1
        assert "failed" in errors[0].lower() or "Federal Register" in errors[0]

    @patch("sector_event_radar.collectors.federal_register.requests.get")
    def test_empty_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        events, errors = fetch_federal_register_bis_events("2026-03-01", "2026-09-01")
        assert len(events) == 0
        assert len(errors) == 0


# ══════════════════════════════════════════════════════════
# TestParseDate (2本)
# ══════════════════════════════════════════════════════════

class TestParseDate:

    def test_valid_date(self):
        dt = _parse_date("2026-04-01")
        assert dt == datetime(2026, 4, 1, tzinfo=timezone.utc)

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            _parse_date("not-a-date")
