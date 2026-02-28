"""Tests for BLS HTML schedule fallback parser."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sector_event_radar.collectors.official_calendars import (
    _parse_bls_html_table,
    fetch_bls_html_events,
    fetch_official_macro_events,
)

ET = ZoneInfo("America/New_York")

# ── Sample HTML matching real BLS format ──────────────────

SAMPLE_CPI_HTML = """
<html><body>
<table>
<tr>
<th>Reference Month</th><th>Release Date</th><th>Release Time</th>
</tr>
<tr>
<td>January 2026</td><td>Feb. 13, 2026</td><td>08:30 AM</td>
</tr>
<tr>
<td>February 2026</td><td>Mar. 11, 2026</td><td>08:30 AM</td>
</tr>
<tr>
<td>March 2026</td><td>Apr. 10, 2026</td><td>08:30 AM</td>
</tr>
<tr>
<td>April 2026</td><td>May 12, 2026</td><td>08:30 AM</td>
</tr>
</table>
</body></html>
"""


class TestParseBLSHtmlTable:

    def test_basic_parsing(self):
        dates = _parse_bls_html_table(SAMPLE_CPI_HTML)
        assert len(dates) == 4
        assert dates[0] == datetime(2026, 2, 13, 8, 30, tzinfo=ET)
        assert dates[1] == datetime(2026, 3, 11, 8, 30, tzinfo=ET)

    def test_date_with_period_abbreviation(self):
        """BLS uses 'Feb.' with trailing period."""
        html = """<table><tr><td>x</td><td>Feb. 13, 2026</td><td>08:30 AM</td></tr></table>"""
        dates = _parse_bls_html_table(html)
        assert len(dates) == 1
        assert dates[0].month == 2
        assert dates[0].day == 13

    def test_date_without_period(self):
        """Also handle 'May 12, 2026' (no period for 3-letter months)."""
        html = """<table><tr><td>x</td><td>May 12, 2026</td><td>08:30 AM</td></tr></table>"""
        dates = _parse_bls_html_table(html)
        assert len(dates) == 1
        assert dates[0].month == 5

    def test_pm_time(self):
        html = """<table><tr><td>x</td><td>Mar. 11, 2026</td><td>02:00 PM</td></tr></table>"""
        dates = _parse_bls_html_table(html)
        assert dates[0].hour == 14

    def test_noon_time(self):
        html = """<table><tr><td>x</td><td>Mar. 11, 2026</td><td>12:00 PM</td></tr></table>"""
        dates = _parse_bls_html_table(html)
        assert dates[0].hour == 12

    def test_empty_html(self):
        dates = _parse_bls_html_table("<html></html>")
        assert dates == []

    def test_header_row_skipped(self):
        """Header row with <th> tags should not produce dates."""
        html = """<table>
        <tr><th>Month</th><th>Date</th><th>Time</th></tr>
        <tr><td>Jan 2026</td><td>Feb. 13, 2026</td><td>08:30 AM</td></tr>
        </table>"""
        dates = _parse_bls_html_table(html)
        assert len(dates) == 1

    def test_html_tags_in_cells(self):
        """Handle <strong>, <a> etc inside <td>."""
        html = """<table><tr>
        <td>Jan 2026</td>
        <td><strong>Feb. 13, 2026</strong></td>
        <td><a href="#">08:30 AM</a></td>
        </tr></table>"""
        dates = _parse_bls_html_table(html)
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 2, 13, 8, 30, tzinfo=ET)


class TestFetchBLSHtmlEvents:

    @patch("sector_event_radar.collectors.official_calendars.requests.get")
    def test_creates_events_for_three_indicators(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_CPI_HTML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        start = datetime(2026, 2, 28, tzinfo=ET)
        end = datetime(2026, 8, 28, tzinfo=ET)
        events = fetch_bls_html_events(start, end)

        # 3 pages (CPI/NFP/PPI) × dates in range
        assert len(events) > 0
        # All should be macro category
        for ev in events:
            assert ev.category == "macro"
            assert ev.source_name == "bls"

    @patch("sector_event_radar.collectors.official_calendars.requests.get")
    def test_date_range_filter(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_CPI_HTML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Only include March-April range
        start = datetime(2026, 3, 1, tzinfo=ET)
        end = datetime(2026, 4, 30, tzinfo=ET)
        events = fetch_bls_html_events(start, end)

        # Should get Mar 11 and Apr 10 for each of 3 indicators = 6
        dates = {ev.start_at.strftime("%m-%d") for ev in events}
        assert "03-11" in dates
        assert "04-10" in dates

    @patch("sector_event_radar.collectors.official_calendars.requests.get")
    def test_partial_failure_continues(self, mock_get):
        """If one page fails, others still work."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("CPI page down")
            mock_resp = MagicMock()
            mock_resp.text = SAMPLE_CPI_HTML
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        mock_get.side_effect = side_effect

        start = datetime(2026, 2, 28, tzinfo=ET)
        end = datetime(2026, 8, 28, tzinfo=ET)
        events = fetch_bls_html_events(start, end)

        # 1 failed + 2 succeeded → still have events
        assert len(events) > 0


class TestBLSFallbackIntegration:

    @patch("sector_event_radar.collectors.official_calendars.fetch_ics_macro_events")
    @patch("sector_event_radar.collectors.official_calendars.fetch_bls_html_events")
    @patch("sector_event_radar.collectors.official_calendars.generate_fomc_events")
    def test_ics_403_triggers_html_fallback(self, mock_fomc, mock_html, mock_ics):
        """When .ics returns 403 for BLS, HTML fallback should be called."""
        from requests.exceptions import HTTPError

        # BLS .ics fails (first call), BEA .ics succeeds (second call)
        mock_ics.side_effect = [HTTPError("403 Client Error: Forbidden"), []]
        mock_html.return_value = []
        mock_fomc.return_value = []

        cfg = MagicMock()
        cfg.fomc_dates = []
        start = datetime(2026, 2, 28, tzinfo=ET)
        end = datetime(2026, 8, 28, tzinfo=ET)

        events, errors = fetch_official_macro_events(cfg, start, end)

        mock_html.assert_called_once_with(start, end)
        # No error in errors list if HTML fallback succeeded
        assert len(errors) == 0

    @patch("sector_event_radar.collectors.official_calendars.fetch_ics_macro_events")
    @patch("sector_event_radar.collectors.official_calendars.fetch_bls_html_events")
    @patch("sector_event_radar.collectors.official_calendars.generate_fomc_events")
    def test_ics_success_skips_html(self, mock_fomc, mock_html, mock_ics):
        """When .ics succeeds, HTML fallback should NOT be called."""
        mock_ics.return_value = []
        mock_fomc.return_value = []

        cfg = MagicMock()
        cfg.fomc_dates = []
        start = datetime(2026, 2, 28, tzinfo=ET)
        end = datetime(2026, 8, 28, tzinfo=ET)

        fetch_official_macro_events(cfg, start, end)

        mock_html.assert_not_called()

    @patch("sector_event_radar.collectors.official_calendars.fetch_ics_macro_events")
    @patch("sector_event_radar.collectors.official_calendars.fetch_bls_html_events")
    @patch("sector_event_radar.collectors.official_calendars.generate_fomc_events")
    def test_both_fail_records_error(self, mock_fomc, mock_html, mock_ics):
        """When both .ics and HTML fail, error is recorded."""
        from requests.exceptions import HTTPError
        mock_ics.side_effect = HTTPError("403")
        mock_html.side_effect = ConnectionError("all pages blocked")
        mock_fomc.return_value = []

        cfg = MagicMock()
        cfg.fomc_dates = []
        start = datetime(2026, 2, 28, tzinfo=ET)
        end = datetime(2026, 8, 28, tzinfo=ET)

        events, errors = fetch_official_macro_events(cfg, start, end)

        assert any("both .ics and HTML" in e for e in errors)
