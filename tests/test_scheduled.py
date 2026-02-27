"""TE / FMP collector tests"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import requests as requests_lib

from sector_event_radar.collectors.scheduled import (
    fetch_tradingeconomics_events,
    fetch_fmp_earnings_events,
    TE_CATEGORY_FILTER,
)


MOCK_TE_RESPONSE = [
    {
        "CalendarId": "400001",
        "Date": "2026-03-12T12:30:00",
        "Country": "United States",
        "Category": "inflation rate",
        "Event": "CPI YoY",
        "Reference": "Feb",
        "Importance": 3,
    },
    {
        "CalendarId": "400002",
        "Date": "2026-03-18T18:00:00",
        "Country": "United States",
        "Category": "interest rate decision",
        "Event": "Fed Interest Rate Decision",
        "Reference": "Mar",
        "Importance": 3,
    },
    {
        "CalendarId": "400003",
        "Date": "2026-03-15T14:00:00",
        "Country": "United States",
        "Category": "api crude oil stock change",
        "Event": "API Crude Oil Stock Change",
        "Importance": 2,
    },
]


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_te_fetches_and_filters(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_TE_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    events = fetch_tradingeconomics_events("test_key", "2026-03-01", "2026-03-31")

    assert len(events) == 2
    assert all(ev.category == "macro" for ev in events)

    cpi = [e for e in events if "CPI" in e.title][0]
    assert cpi.risk_score == 50
    assert cpi.confidence == 1.0
    assert cpi.source_name == "tradingeconomics"
    assert cpi.start_at.tzinfo is not None

    fomc = [e for e in events if "Fed" in e.title][0]
    assert fomc.risk_score == 50


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_te_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    events = fetch_tradingeconomics_events("key", "2026-03-01", "2026-03-31")
    assert events == []


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_te_api_error_propagates(mock_get):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests_lib.exceptions.HTTPError("429")
    mock_get.return_value = mock_resp

    with pytest.raises(requests_lib.exceptions.HTTPError):
        fetch_tradingeconomics_events("key", "2026-03-01", "2026-03-31")


MOCK_FMP_RESPONSE = [
    {
        "date": "2026-02-26",
        "symbol": "NVDA",
        "eps": None,
        "epsEstimated": 0.89,
        "time": "amc",
        "revenue": None,
        "revenueEstimated": 38000000000,
    },
    {
        "date": "2026-04-24",
        "symbol": "MSFT",
        "eps": None,
        "epsEstimated": 3.22,
        "time": "amc",
    },
    {
        "date": "2026-03-15",
        "symbol": "WMT",
        "eps": None,
        "epsEstimated": 1.65,
        "time": "bmo",
    },
]


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_fmp_fetches_and_filters(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_FMP_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    events = fetch_fmp_earnings_events(
        "test_key", "2026-02-01", "2026-04-30",
        tickers=["NVDA", "TSM", "ASML", "AMD", "AVGO", "MSFT", "GOOGL", "AMZN", "META"],
    )

    assert len(events) == 2
    assert all(ev.category == "bellwether" for ev in events)

    nvda = [e for e in events if "NVDA" in e.title][0]
    assert nvda.source_name == "fmp"
    assert "nvda" in nvda.sector_tags
    assert "AMC" in nvda.title
    assert nvda.start_at.tzinfo is not None

    msft = [e for e in events if "MSFT" in e.title][0]
    assert msft.source_id == "fmp:MSFT:2026-04-24"


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_fmp_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    events = fetch_fmp_earnings_events("key", "2026-03-01", "2026-03-31")
    assert events == []


@patch("sector_event_radar.collectors.scheduled.requests.get")
def test_fmp_chunks_long_range(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fetch_fmp_earnings_events("key", "2026-01-01", "2026-06-30")
    assert mock_get.call_count >= 2


def test_te_category_filter_has_key_indicators():
    assert "interest rate decision" in TE_CATEGORY_FILTER
    assert "inflation rate" in TE_CATEGORY_FILTER
    assert "non farm payrolls" in TE_CATEGORY_FILTER
    assert "gdp growth rate" in TE_CATEGORY_FILTER
    assert "initial jobless claims" in TE_CATEGORY_FILTER
