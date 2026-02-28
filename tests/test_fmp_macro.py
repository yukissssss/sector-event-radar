"""Tests for FMP Economic Calendar macro collector."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from sector_event_radar.collectors.scheduled import (
    fetch_fmp_macro_events,
    _match_macro_event,
    _macro_subtype_to_risk,
    _parse_fmp_datetime,
)
from sector_event_radar.config import MacroTitleRule


# ── テスト用 macro_rules ────────────────────────────────

def _make_rules():
    """config.yamlのmacro_title_mapと同等のルールを生成"""
    raw = {
        r"(?i)\b(FOMC|fed funds|interest rate decision|federal reserve)\b": MacroTitleRule(entity="us", sub_type="fomc"),
        r"(?i)\bCPI\b": MacroTitleRule(entity="us", sub_type="cpi"),
        r"(?i)\b(nonfarm|NFP|non-farm)\b": MacroTitleRule(entity="us", sub_type="nfp"),
        r"(?i)\bPPI\b": MacroTitleRule(entity="us", sub_type="ppi"),
        r"(?i)\bPCE\b": MacroTitleRule(entity="us", sub_type="pce"),
        r"(?i)\bGDP\b": MacroTitleRule(entity="us", sub_type="gdp"),
        r"(?i)\bjobless claims\b": MacroTitleRule(entity="us", sub_type="jobless-claims"),
        r"(?i)\bISM\b": MacroTitleRule(entity="us", sub_type="ism"),
        r"(?i)\bretail sales\b": MacroTitleRule(entity="us", sub_type="retail-sales"),
    }
    return [(re.compile(pat), rule) for pat, rule in raw.items()]


MACRO_RULES = _make_rules()


# ── _match_macro_event テスト ────────────────────────────

class TestMatchMacroEvent:
    def test_cpi_match(self):
        result = _match_macro_event("United States CPI YoY", MACRO_RULES)
        assert result == ("us", "cpi")

    def test_fomc_match(self):
        result = _match_macro_event("United States FOMC Meeting", MACRO_RULES)
        assert result == ("us", "fomc")

    def test_fed_interest_rate_decision(self):
        """FMPが 'Fed Interest Rate Decision' 表記を使う場合のマッチ確認"""
        result = _match_macro_event("United States Fed Interest Rate Decision", MACRO_RULES)
        assert result == ("us", "fomc")

    def test_nonfarm_payrolls(self):
        result = _match_macro_event("United States Nonfarm Payrolls", MACRO_RULES)
        assert result == ("us", "nfp")

    def test_non_farm_hyphen(self):
        result = _match_macro_event("United States Non-Farm Payrolls", MACRO_RULES)
        assert result == ("us", "nfp")

    def test_gdp_match(self):
        result = _match_macro_event("United States GDP Growth Rate QoQ", MACRO_RULES)
        assert result == ("us", "gdp")

    def test_ism_match(self):
        result = _match_macro_event("United States ISM Manufacturing PMI", MACRO_RULES)
        assert result == ("us", "ism")

    def test_retail_sales(self):
        result = _match_macro_event("United States Retail Sales MoM", MACRO_RULES)
        assert result == ("us", "retail-sales")

    def test_noise_no_match(self):
        """マッチすべきでないイベントはNone"""
        result = _match_macro_event("United States Redbook YoY", MACRO_RULES)
        assert result is None

    def test_non_us_event_name_still_matches(self):
        """_match_macro_eventはイベント名だけ見る（country filterは呼び出し側）"""
        result = _match_macro_event("Germany CPI MoM", MACRO_RULES)
        assert result == ("us", "cpi")  # マッチはする。countryフィルタは別


# ── risk_score テスト ────────────────────────────────────

class TestMacroSubtypeToRisk:
    def test_fomc_highest(self):
        assert _macro_subtype_to_risk("fomc") == 60

    def test_cpi_nfp(self):
        assert _macro_subtype_to_risk("cpi") == 50
        assert _macro_subtype_to_risk("nfp") == 50

    def test_pce_gdp(self):
        assert _macro_subtype_to_risk("pce") == 45
        assert _macro_subtype_to_risk("gdp") == 45

    def test_others(self):
        assert _macro_subtype_to_risk("ppi") == 35
        assert _macro_subtype_to_risk("ism") == 35
        assert _macro_subtype_to_risk("retail-sales") == 35

    def test_unknown_subtype(self):
        assert _macro_subtype_to_risk("unknown_thing") == 30


# ── _parse_fmp_datetime テスト ───────────────────────────

class TestParseFmpDatetime:
    def test_space_format(self):
        dt = _parse_fmp_datetime("2026-03-12 12:30:00")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.hour == 12

    def test_z_suffix(self):
        dt = _parse_fmp_datetime("2026-03-12T12:30:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_empty_string(self):
        assert _parse_fmp_datetime("") is None

    def test_none(self):
        assert _parse_fmp_datetime(None) is None

    def test_garbage(self):
        assert _parse_fmp_datetime("not-a-date") is None


# ── fetch_fmp_macro_events 統合テスト ────────────────────

FMP_SAMPLE_RESPONSE = [
    {"event": "United States CPI YoY", "date": "2026-03-12 12:30:00", "country": "US",
     "actual": None, "previous": 3.0, "estimate": 2.9},
    {"event": "United States Fed Interest Rate Decision", "date": "2026-03-19 18:00:00", "country": "US",
     "actual": None, "previous": 5.25, "estimate": 5.25},
    {"event": "United States Nonfarm Payrolls", "date": "2026-04-04 12:30:00", "country": "US",
     "actual": None, "previous": 225, "estimate": 200},
    {"event": "United States Redbook YoY", "date": "2026-03-11 12:55:00", "country": "US",
     "actual": None, "previous": 5.5, "estimate": None},
    {"event": "Germany CPI MoM", "date": "2026-03-13 07:00:00", "country": "DE",
     "actual": None, "previous": 0.3, "estimate": 0.4},
    {"event": "United States ISM Manufacturing PMI", "date": "2026-04-01 14:00:00", "country": "US",
     "actual": None, "previous": 50.3, "estimate": 50.5},
]


class TestFetchFmpMacroEvents:
    @patch("sector_event_radar.collectors.scheduled.requests.get")
    def test_filters_and_creates_events(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = FMP_SAMPLE_RESPONSE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        events = fetch_fmp_macro_events(
            "fake_key", "2026-03-01", "2026-04-30",
            macro_rules=MACRO_RULES,
        )

        # US only + macro_title_mapマッチ: CPI, Fed Rate Decision, NFP, ISM = 4件
        # Redbook = マッチしない、Germany CPI = country filterで除外
        assert len(events) == 4

        titles = {e.title for e in events}
        assert "United States CPI YoY" in titles
        assert "United States Fed Interest Rate Decision" in titles
        assert "United States Nonfarm Payrolls" in titles
        assert "United States ISM Manufacturing PMI" in titles
        assert "United States Redbook YoY" not in titles
        assert "Germany CPI MoM" not in titles

    @patch("sector_event_radar.collectors.scheduled.requests.get")
    def test_events_have_correct_attributes(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = FMP_SAMPLE_RESPONSE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        events = fetch_fmp_macro_events(
            "fake_key", "2026-03-01", "2026-04-30",
            macro_rules=MACRO_RULES,
        )

        cpi = [e for e in events if "CPI" in e.title][0]
        assert cpi.category == "macro"
        assert cpi.risk_score == 50  # sub_type="cpi" → 50
        assert cpi.start_at.tzinfo is not None
        assert cpi.source_name == "fmp_economic"
        assert cpi.source_id.startswith("fmp_eco:us:cpi:")

        fomc = [e for e in events if "Interest Rate" in e.title][0]
        assert fomc.risk_score == 60  # sub_type="fomc" → 60
        assert fomc.source_id.startswith("fmp_eco:us:fomc:")

    @patch("sector_event_radar.collectors.scheduled.requests.get")
    def test_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        events = fetch_fmp_macro_events(
            "fake_key", "2026-03-01", "2026-04-30",
            macro_rules=MACRO_RULES,
        )
        assert events == []

    @patch("sector_event_radar.collectors.scheduled.requests.get")
    def test_error_dict_response(self, mock_get):
        """FMP APIがエラーdictを返した場合、空リストを返す（例外は出さない）"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Error Message": "Limit Reach. Please upgrade your plan."}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        events = fetch_fmp_macro_events(
            "fake_key", "2026-03-01", "2026-04-30",
            macro_rules=MACRO_RULES,
        )
        assert events == []

    @patch("sector_event_radar.collectors.scheduled.requests.get")
    def test_api_error_propagates(self, mock_get):
        """HTTPエラーは呼び出し元に伝播する（run_dailyのtry/exceptで拾う）"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_get.return_value = mock_resp

        with pytest.raises(Exception, match="403"):
            fetch_fmp_macro_events(
                "fake_key", "2026-03-01", "2026-04-30",
                macro_rules=MACRO_RULES,
            )
