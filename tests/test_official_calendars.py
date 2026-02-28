"""Tests for collectors/official_calendars.py — BLS/BEA .ics + FOMC

GPT review improvements covered:
  - macro_rules compiled once and passed (not per-event recompile)
  - _parse_datetime_flexible: HHMMSS + HHMM support
  - source_url populated (ics_url for BLS/BEA, FRB page for FOMC)
  - matched=0 warning when config mismatch detected
"""
from __future__ import annotations

import logging
import textwrap
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.sector_event_radar.collectors.official_calendars import (
    _unfold_ics,
    _parse_vevent_blocks,
    _parse_datetime_flexible,
    _parse_dtstart,
    _get_summary,
    _match_and_build_event,
    fetch_ics_macro_events,
    generate_fomc_events,
    fetch_official_macro_events,
    FRB_FOMC_URL,
    ET, UTC,
)
from src.sector_event_radar.config import AppConfig

# ── Fixtures ──────────────────────────────────────────────

SAMPLE_BLS_ICS = textwrap.dedent("""\
    BEGIN:VCALENDAR
    VERSION:2.0
    PRODID:-//BLS//NONSGML Release Schedule//EN
    BEGIN:VEVENT
    DTSTART;TZID=US-Eastern:20260310T083000
    DURATION:PT1H
    SUMMARY:Consumer Price Index
    UID:bls-cpi-20260310@bls.gov
    END:VEVENT
    BEGIN:VEVENT
    DTSTART;TZID=US-Eastern:20260403T083000
    DURATION:PT1H
    SUMMARY:Employment Situation
    UID:bls-nfp-20260403@bls.gov
    END:VEVENT
    BEGIN:VEVENT
    DTSTART;TZID=US-Eastern:20260414T083000
    DURATION:PT1H
    SUMMARY:Producer Price Index
    UID:bls-ppi-20260414@bls.gov
    END:VEVENT
    BEGIN:VEVENT
    DTSTART;TZID=US-Eastern:20260320T100000
    DURATION:PT1H
    SUMMARY:Job Openings and Labor Turnover Survey
    UID:bls-jolts-20260320@bls.gov
    END:VEVENT
    END:VCALENDAR
""")

SAMPLE_BEA_ICS = textwrap.dedent("""\
    BEGIN:VCALENDAR
    VERSION:2.0
    PRODID:-//BEA//Release Schedule//EN
    BEGIN:VEVENT
    DTSTART:20260327T123000Z
    SUMMARY:Gross Domestic Product
    UID:bea-gdp-20260327@bea.gov
    END:VEVENT
    BEGIN:VEVENT
    DTSTART:20260401T123000Z
    SUMMARY:Personal Income and Outlays
    UID:bea-pce-20260401@bea.gov
    END:VEVENT
    BEGIN:VEVENT
    DTSTART:20260415T123000Z
    SUMMARY:International Transactions
    UID:bea-intl-20260415@bea.gov
    END:VEVENT
    END:VCALENDAR
""")

# ICS with no-seconds HHMM format (GPT review: format resilience)
SAMPLE_HHMM_ICS = textwrap.dedent("""\
    BEGIN:VCALENDAR
    VERSION:2.0
    BEGIN:VEVENT
    DTSTART;TZID=US-Eastern:20260310T0830
    SUMMARY:Consumer Price Index
    UID:test-hhmm@test
    END:VEVENT
    END:VCALENDAR
""")


@pytest.fixture
def cfg():
    """AppConfig with full-spell + abbreviation macro_title_map."""
    return AppConfig(
        macro_title_map={
            '(?i)\\bCPI\\b': {'entity': 'us', 'sub_type': 'cpi'},
            '(?i)\\b(nonfarm|NFP|non-farm)\\b': {'entity': 'us', 'sub_type': 'nfp'},
            '(?i)\\bPPI\\b': {'entity': 'us', 'sub_type': 'ppi'},
            '(?i)\\bGDP\\b': {'entity': 'us', 'sub_type': 'gdp'},
            '(?i)\\bPCE\\b': {'entity': 'us', 'sub_type': 'pce'},
            '(?i)Consumer Price Index': {'entity': 'us', 'sub_type': 'cpi'},
            '(?i)Employment Situation': {'entity': 'us', 'sub_type': 'nfp'},
            '(?i)Producer Price Index': {'entity': 'us', 'sub_type': 'ppi'},
            '(?i)Gross Domestic Product': {'entity': 'us', 'sub_type': 'gdp'},
            '(?i)Personal Income and Outlays': {'entity': 'us', 'sub_type': 'pce'},
        },
        fomc_dates=['2026-03-18', '2026-04-29', '2026-06-17'],
    )


@pytest.fixture
def macro_rules(cfg):
    """Precompiled macro rules (GPT review: compile once)."""
    return cfg.macro_rules_compiled()


@pytest.fixture
def date_range():
    """Standard test date range: 2026-03-01 → 2026-06-30."""
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    return start, end


# ── ICS Parser tests ──────────────────────────────────────

class TestUnfoldIcs:
    def test_unfold_crlf_space(self):
        text = "SUMMARY:This is a long\r\n  description that wraps"
        assert _unfold_ics(text) == "SUMMARY:This is a long description that wraps"

    def test_unfold_tab_continuation(self):
        text = "SUMMARY:Hello\r\n\tworld"
        assert _unfold_ics(text) == "SUMMARY:Helloworld"

    def test_no_continuation(self):
        text = "SUMMARY:Simple line"
        assert _unfold_ics(text) == "SUMMARY:Simple line"


class TestParseVeventBlocks:
    def test_bls_format(self):
        blocks = _parse_vevent_blocks(SAMPLE_BLS_ICS)
        assert len(blocks) == 4

    def test_bea_format(self):
        blocks = _parse_vevent_blocks(SAMPLE_BEA_ICS)
        assert len(blocks) == 3

    def test_empty_calendar(self):
        ics = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        assert _parse_vevent_blocks(ics) == []

    def test_properties_extracted(self):
        blocks = _parse_vevent_blocks(SAMPLE_BLS_ICS)
        cpi = blocks[0]
        assert "DTSTART;TZID=US-Eastern" in cpi
        assert "SUMMARY" in cpi


# ── _parse_datetime_flexible tests (GPT review: HHMM support) ──

class TestParseDatetimeFlexible:
    def test_hhmmss(self):
        dt = _parse_datetime_flexible("20260310T083000")
        assert dt is not None
        assert dt.hour == 8 and dt.minute == 30 and dt.second == 0

    def test_hhmm_no_seconds(self):
        dt = _parse_datetime_flexible("20260310T0830")
        assert dt is not None
        assert dt.hour == 8 and dt.minute == 30

    def test_date_only(self):
        dt = _parse_datetime_flexible("20260310")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 3 and dt.day == 10

    def test_with_z_suffix(self):
        dt = _parse_datetime_flexible("20260327T123000Z")
        assert dt is not None
        assert dt.hour == 12 and dt.minute == 30

    def test_invalid_returns_none(self):
        assert _parse_datetime_flexible("not-a-date") is None
        assert _parse_datetime_flexible("") is None


class TestParseDtstart:
    def test_bls_eastern_timezone(self):
        ve = {"DTSTART;TZID=US-Eastern": "20260310T083000", "SUMMARY": "CPI"}
        dt = _parse_dtstart(ve)
        assert dt is not None
        assert dt.year == 2026 and dt.month == 3 and dt.day == 10
        assert dt.hour == 8 and dt.minute == 30
        assert dt.tzinfo == ET

    def test_bea_utc(self):
        ve = {"DTSTART": "20260327T123000Z", "SUMMARY": "GDP"}
        dt = _parse_dtstart(ve)
        assert dt is not None
        assert dt.hour == 12 and dt.minute == 30
        assert dt.tzinfo == UTC

    def test_hhmm_no_seconds(self):
        """GPT review: HHMM format without seconds."""
        ve = {"DTSTART;TZID=US-Eastern": "20260310T0830", "SUMMARY": "CPI"}
        dt = _parse_dtstart(ve)
        assert dt is not None
        assert dt.hour == 8 and dt.minute == 30
        assert dt.tzinfo == ET

    def test_date_only(self):
        ve = {"DTSTART;VALUE=DATE": "20260310", "SUMMARY": "Something"}
        dt = _parse_dtstart(ve)
        assert dt is not None
        assert dt.hour == 8 and dt.minute == 30
        assert dt.tzinfo == ET

    def test_no_dtstart(self):
        ve = {"SUMMARY": "No date"}
        assert _parse_dtstart(ve) is None

    def test_invalid_format(self):
        ve = {"DTSTART": "not-a-date", "SUMMARY": "Bad"}
        assert _parse_dtstart(ve) is None

    def test_bare_datetime_assumes_et(self):
        ve = {"DTSTART": "20260310T083000", "SUMMARY": "Test"}
        dt = _parse_dtstart(ve)
        assert dt is not None
        assert dt.tzinfo == ET


class TestGetSummary:
    def test_basic(self):
        assert _get_summary({"SUMMARY": "Consumer Price Index"}) == "Consumer Price Index"

    def test_with_params(self):
        assert _get_summary({"SUMMARY;LANGUAGE=en-US": "GDP"}) == "GDP"

    def test_missing(self):
        assert _get_summary({"DTSTART": "20260101T000000Z"}) == ""


# ── Event matching tests (GPT review: uses precompiled rules) ──

class TestMatchAndBuildEvent:
    def test_cpi_full_spell(self, macro_rules):
        dt = datetime(2026, 3, 10, 8, 30, tzinfo=ET)
        ev = _match_and_build_event("Consumer Price Index", dt, "bls", "https://bls.gov/bls.ics", macro_rules)
        assert ev is not None
        assert ev.category == "macro"
        assert ev.risk_score == 50
        assert ev.source_id == "bls:cpi:2026-03-10"

    def test_nfp_full_spell(self, macro_rules):
        dt = datetime(2026, 4, 3, 8, 30, tzinfo=ET)
        ev = _match_and_build_event("Employment Situation", dt, "bls", "https://bls.gov/bls.ics", macro_rules)
        assert ev is not None
        assert ev.risk_score == 50

    def test_gdp_full_spell(self, macro_rules):
        dt = datetime(2026, 3, 27, 8, 30, tzinfo=UTC)
        ev = _match_and_build_event("Gross Domestic Product", dt, "bea", "https://bea.gov/bea.ics", macro_rules)
        assert ev is not None
        assert ev.risk_score == 45

    def test_pce_full_spell(self, macro_rules):
        dt = datetime(2026, 4, 1, 8, 30, tzinfo=UTC)
        ev = _match_and_build_event("Personal Income and Outlays", dt, "bea", "https://bea.gov/bea.ics", macro_rules)
        assert ev is not None
        assert ev.risk_score == 45

    def test_unmatched_returns_none(self, macro_rules):
        dt = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        ev = _match_and_build_event("Job Openings and Labor Turnover Survey", dt, "bls", "https://bls.gov/bls.ics", macro_rules)
        assert ev is None

    def test_source_url_populated(self, macro_rules):
        """GPT review: source_url should be set (not None)."""
        dt = datetime(2026, 3, 10, 8, 30, tzinfo=ET)
        ev = _match_and_build_event("Consumer Price Index", dt, "bls", "https://bls.gov/bls.ics", macro_rules)
        assert ev is not None
        assert str(ev.source_url) == "https://bls.gov/bls.ics"

    def test_evidence_truncation(self, macro_rules):
        dt = datetime(2026, 3, 10, 8, 30, tzinfo=ET)
        long_summary = "Consumer Price Index " + "x" * 300
        ev = _match_and_build_event(long_summary, dt, "bls", "https://bls.gov/bls.ics", macro_rules)
        assert ev is not None
        assert len(ev.evidence) <= 280


# ── fetch_ics_macro_events tests ──────────────────────────

class TestFetchIcsMacroEvents:
    def test_bls_parsing(self, cfg, date_range):
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BLS_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events = fetch_ics_macro_events(
                "https://example.com/bls.ics", "bls", cfg, start, end,
            )

        # CPI (Mar 10), NFP (Apr 3), PPI (Apr 14) in range; JOLTS unmatched
        assert len(events) == 3
        cats = {e.source_id.split(":")[1] for e in events}
        assert cats == {"cpi", "nfp", "ppi"}

    def test_bls_source_url_is_ics_url(self, cfg, date_range):
        """GPT review: source_url = ics_url for traceability."""
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BLS_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events = fetch_ics_macro_events(
                "https://www.bls.gov/schedule/news_release/bls.ics", "bls", cfg, start, end,
            )

        assert len(events) > 0
        for ev in events:
            assert str(ev.source_url) == "https://www.bls.gov/schedule/news_release/bls.ics"

    def test_bea_parsing(self, cfg, date_range):
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BEA_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events = fetch_ics_macro_events(
                "https://example.com/bea.ics", "bea", cfg, start, end,
            )

        # GDP (Mar 27), PCE (Apr 1) in range
        assert len(events) == 2
        cats = {e.source_id.split(":")[1] for e in events}
        assert cats == {"gdp", "pce"}

    def test_hhmm_format_parsed(self, cfg, date_range):
        """GPT review: HHMM (no seconds) format should work."""
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HHMM_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events = fetch_ics_macro_events(
                "https://example.com/test.ics", "test", cfg, start, end,
            )

        assert len(events) == 1
        assert events[0].start_at.hour == 8
        assert events[0].start_at.minute == 30

    def test_date_range_filter(self, cfg):
        """Events outside range are excluded."""
        start = datetime(2026, 4, 1, tzinfo=UTC)
        end = datetime(2026, 4, 30, tzinfo=UTC)

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BLS_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events = fetch_ics_macro_events(
                "https://example.com/bls.ics", "bls", cfg, start, end,
            )

        # Only NFP (Apr 3) and PPI (Apr 14) in April
        assert len(events) == 2

    def test_matched_zero_warning(self, date_range, caplog):
        """GPT review: warning when events exist but none match."""
        cfg_no_match = AppConfig(
            macro_title_map={
                '(?i)NONEXISTENT_PATTERN': {'entity': 'us', 'sub_type': 'fake'},
            },
        )
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BLS_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            with caplog.at_level(logging.WARNING):
                events = fetch_ics_macro_events(
                    "https://example.com/bls.ics", "bls", cfg_no_match, start, end,
                )

        assert len(events) == 0
        assert any("0 matched" in r.message for r in caplog.records)
        assert any("Check macro_title_map" in r.message for r in caplog.records)

    def test_http_error_propagates(self, cfg, date_range):
        start, end = date_range
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 500"):
                fetch_ics_macro_events(
                    "https://example.com/bls.ics", "bls", cfg, start, end,
                )


# ── FOMC tests ────────────────────────────────────────────

class TestGenerateFomcEvents:
    def test_basic_generation(self, date_range):
        start, end = date_range
        fomc_dates = ["2026-03-18", "2026-04-29", "2026-06-17"]
        events = generate_fomc_events(fomc_dates, start, end)
        assert len(events) == 3
        assert all(e.category == "macro" for e in events)
        assert all(e.risk_score == 60 for e in events)
        assert all(e.confidence == 1.0 for e in events)

    def test_fomc_time_is_2pm_et(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        events = generate_fomc_events(["2026-03-18"], start, end)
        assert len(events) == 1
        assert events[0].start_at.hour == 14
        assert events[0].start_at.minute == 0
        assert events[0].start_at.tzinfo == ET

    def test_fomc_source_url_is_frb(self):
        """GPT review: FOMC events should link to FRB schedule page."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        events = generate_fomc_events(["2026-03-18"], start, end)
        assert len(events) == 1
        assert str(events[0].source_url) == FRB_FOMC_URL

    def test_date_range_filter(self):
        start = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 8, 31, tzinfo=UTC)
        fomc_dates = ["2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29"]
        events = generate_fomc_events(fomc_dates, start, end)
        # Jun 17 and Jul 29 in range
        assert len(events) == 2

    def test_invalid_date_skipped(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        events = generate_fomc_events(["2026-13-99", "2026-03-18"], start, end)
        assert len(events) == 1

    def test_empty_dates(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        events = generate_fomc_events([], start, end)
        assert len(events) == 0


# ── Integration: fetch_official_macro_events ──────────────

class TestFetchOfficialMacroEvents:
    def test_all_sources_combined(self, cfg):
        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 6, 30, tzinfo=UTC)

        mock_bls_resp = MagicMock()
        mock_bls_resp.text = SAMPLE_BLS_ICS
        mock_bls_resp.raise_for_status = MagicMock()

        mock_bea_resp = MagicMock()
        mock_bea_resp.text = SAMPLE_BEA_ICS
        mock_bea_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "bls.gov" in url:
                return mock_bls_resp
            elif "bea.gov" in url:
                return mock_bea_resp
            raise Exception(f"Unexpected URL: {url}")

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", side_effect=mock_get):
            events, errors = fetch_official_macro_events(cfg, start, end)

        # BLS: 3 (CPI, NFP, PPI) + BEA: 2 (GDP, PCE) + FOMC: 3 (Mar, Apr, Jun)
        assert len(events) == 8
        assert len(errors) == 0

        sources = {e.source_name for e in events}
        assert sources == {"bls", "bea", "frb"}

        # All events have source_url set
        for ev in events:
            assert ev.source_url is not None

    def test_partial_failure_bls(self, cfg):
        """BLS fails but BEA and FOMC still work."""
        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 6, 30, tzinfo=UTC)

        mock_bea_resp = MagicMock()
        mock_bea_resp.text = SAMPLE_BEA_ICS
        mock_bea_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "bls.gov" in url:
                raise ConnectionError("BLS down")
            return mock_bea_resp

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", side_effect=mock_get):
            events, errors = fetch_official_macro_events(cfg, start, end)

        # BEA: 2 + FOMC: 3 (BLS failed)
        assert len(events) == 5
        assert len(errors) == 1
        assert "BLS" in errors[0]

    def test_no_fomc_dates_configured(self):
        """No fomc_dates → FOMC silently skipped."""
        cfg_no_fomc = AppConfig(
            macro_title_map={
                '(?i)Consumer Price Index': {'entity': 'us', 'sub_type': 'cpi'},
            },
            fomc_dates=[],
        )
        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 6, 30, tzinfo=UTC)

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BLS_ICS
        mock_resp.raise_for_status = MagicMock()

        with patch("src.sector_event_radar.collectors.official_calendars.requests.get", return_value=mock_resp):
            events, errors = fetch_official_macro_events(cfg_no_fomc, start, end)

        fomc_events = [e for e in events if e.source_name == "frb"]
        assert len(fomc_events) == 0
        assert len(errors) == 0
