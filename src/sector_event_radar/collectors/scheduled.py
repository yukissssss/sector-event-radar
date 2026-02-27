"""Scheduled collectors: Trading Economics (macro) + FMP (bellwether earnings)

TE API: https://docs.tradingeconomics.com/economic_calendar/country/
  - GET /calendar/country/{country}/{start}/{end}?c={key}&importance={n}
  - Rate limit: 1 req/sec

FMP API: https://financialmodelingprep.com/developer/docs/earnings-calendar-api
  - GET /v3/earning_calendar?from={start}&to={end}&apikey={key}
  - Free plan: 250 calls/day
  - from/to間隔は最大3ヶ月
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Set
from zoneinfo import ZoneInfo

import requests

from ..models import Event

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# ── TE: Trading Economics ────────────────────────────────

TE_BASE = "https://api.tradingeconomics.com"

TE_CATEGORY_FILTER: Set[str] = {
    "interest rate", "interest rate decision", "fed interest rate decision",
    "inflation rate", "inflation rate mom",
    "core inflation rate", "core inflation rate mom", "core inflation rate yoy",
    "cpi", "core cpi",
    "pce price index", "core pce price index",
    "pce price index annual change", "core pce price index annual change",
    "non farm payrolls", "nonfarm payrolls",
    "unemployment rate", "initial jobless claims", "adp employment change",
    "gdp growth rate", "gdp growth rate qoq", "gdp growth annualized",
    "retail sales mom", "retail sales",
    "ism manufacturing pmi", "ism non manufacturing pmi", "ism services pmi",
    "ppi mom", "ppi", "producer price index",
    "michigan consumer sentiment",
}


def _te_importance_to_risk(importance: int) -> int:
    return {3: 50, 2: 30, 1: 20}.get(importance, 25)


def fetch_tradingeconomics_events(
    api_key: str,
    start: str,
    end: str,
    country: str = "united states",
    importance: int = 3,
) -> List[Event]:
    """Trading Economics Economic Calendar -> macro Events"""
    url = f"{TE_BASE}/calendar/country/{country}/{start}/{end}"
    params = {"c": api_key, "f": "json"}
    if importance > 0:
        params["importance"] = str(importance)

    logger.info("TE: fetching %s -> %s (importance>=%d)", start, end, importance)

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        logger.warning("TE: unexpected response type: %s", type(data))
        return []

    events: List[Event] = []
    for item in data:
        category_te = (item.get("Category") or "").lower().strip()
        event_name = item.get("Event") or ""
        date_str = item.get("Date") or ""
        imp = item.get("Importance", 1)

        if category_te not in TE_CATEGORY_FILTER:
            continue

        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            logger.debug("TE: skip unparseable date: %s (%s)", date_str, event_name)
            continue

        risk = _te_importance_to_risk(imp)

        ref = item.get("Reference") or ""
        evidence_parts = [f"TE Calendar: {event_name}"]
        if ref:
            evidence_parts.append(f"ref={ref}")
        evidence_parts.append(f"date={date_str}")
        evidence = ", ".join(evidence_parts)
        if len(evidence) > 280:
            evidence = evidence[:277] + "..."

        ev = Event(
            canonical_key=None,
            title=event_name,
            start_at=dt,
            end_at=None,
            category="macro",
            sector_tags=[],
            risk_score=risk,
            confidence=1.0,
            source_name="tradingeconomics",
            source_url=None,
            source_id=f"te:{item.get('CalendarId', '')}",
            evidence=evidence,
            action="add",
        )
        events.append(ev)

    logger.info("TE: %d items -> %d events after filter", len(data), len(events))
    return events


# ── FMP: Financial Modeling Prep ─────────────────────────

FMP_BASE = "https://financialmodelingprep.com/api/v3"


def _fmp_time_to_risk(time_str: str) -> int:
    return 40


def fetch_fmp_earnings_events(
    api_key: str,
    start: str,
    end: str,
    tickers: Optional[List[str]] = None,
) -> List[Event]:
    """FMP Earnings Calendar -> bellwether Events"""
    if tickers is None:
        tickers = ["NVDA", "TSM", "ASML", "AMD", "AVGO",
                    "MSFT", "GOOGL", "AMZN", "META"]

    ticker_set = {t.upper() for t in tickers}

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    all_data: list = []
    cursor = start_dt
    while cursor < end_dt:
        chunk_end = min(cursor + timedelta(days=89), end_dt)
        chunk_start_str = cursor.strftime("%Y-%m-%d")
        chunk_end_str = chunk_end.strftime("%Y-%m-%d")

        url = f"{FMP_BASE}/earning_calendar"
        params = {
            "from": chunk_start_str,
            "to": chunk_end_str,
            "apikey": api_key,
        }

        logger.info("FMP: fetching %s -> %s", chunk_start_str, chunk_end_str)
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        chunk_data = resp.json()

        if isinstance(chunk_data, list):
            all_data.extend(chunk_data)

        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.5)

    events: List[Event] = []
    for item in all_data:
        symbol = (item.get("symbol") or "").upper()
        if symbol not in ticker_set:
            continue

        date_str = item.get("date") or ""
        time_str = item.get("time") or ""
        eps_est = item.get("epsEstimated")

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if time_str == "bmo":
                dt = dt.replace(hour=7, minute=0, tzinfo=NY_TZ)
            elif time_str == "amc":
                dt = dt.replace(hour=16, minute=30, tzinfo=NY_TZ)
            else:
                dt = dt.replace(hour=16, minute=0, tzinfo=NY_TZ)
        except (ValueError, TypeError):
            logger.debug("FMP: skip unparseable date: %s (%s)", date_str, symbol)
            continue

        evidence_parts = [f"FMP: {symbol} earnings {date_str}"]
        if time_str:
            evidence_parts.append(f"time={time_str}")
        if eps_est is not None:
            evidence_parts.append(f"EPS est={eps_est}")
        evidence = ", ".join(evidence_parts)
        if len(evidence) > 280:
            evidence = evidence[:277] + "..."

        time_label = {"bmo": "BMO", "amc": "AMC"}.get(time_str, "")
        title = f"{symbol} Earnings {time_label}".strip()

        ev = Event(
            canonical_key=None,
            title=title,
            start_at=dt,
            end_at=None,
            category="bellwether",
            sector_tags=[symbol.lower()],
            risk_score=_fmp_time_to_risk(time_str),
            confidence=0.9,
            source_name="fmp",
            source_url=None,
            source_id=f"fmp:{symbol}:{date_str}",
            evidence=evidence,
            action="add",
        )
        events.append(ev)

    logger.info("FMP: %d items -> %d bellwether events", len(all_data), len(events))
    return events
