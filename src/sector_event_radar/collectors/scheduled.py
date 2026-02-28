"""Scheduled collectors: Trading Economics (macro) + FMP (bellwether earnings + macro economic calendar)

TE API: https://docs.tradingeconomics.com/economic_calendar/country/
  - GET /calendar/country/{country}/{start}/{end}?c={key}&importance={n}
  - Rate limit: 1 req/sec

FMP Earnings API: https://financialmodelingprep.com/developer/docs/earnings-calendar-api
  - GET /v3/earning_calendar?from={start}&to={end}&apikey={key}
  - Free plan: 250 calls/day
  - from/to間隔は最大3ヶ月

FMP Economic Calendar API: https://financialmodelingprep.com/developer/docs/economic-calendar
  - GET /v3/economic_calendar?from={start}&to={end}&apikey={key}
  - from/to間隔は最大3ヶ月
  - macro_title_mapの正規表現でCPI/FOMC/NFP等をフィルタ
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

FMP_BASE = "https://financialmodelingprep.com/stable"


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

        url = f"{FMP_BASE}/earnings-calendar"
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


# ── FMP: Economic Calendar (macro) ──────────────────────

def _match_macro_event(event_name: str, macro_rules: list) -> Optional[tuple]:
    """macro_title_mapの正規表現でイベント名をマッチング。
    マッチしたら (entity, sub_type) を返す。マッチしなければ None。
    """
    for pattern, rule in macro_rules:
        if pattern.search(event_name):
            return (rule.entity, rule.sub_type)
    return None


# sub_typeベースのrisk_score（イベント名の表記揺れに依存しない）
_RISK_BY_SUBTYPE = {
    "fomc": 60,
    "cpi": 50,
    "nfp": 50,
    "pce": 45,
    "gdp": 45,
    "ppi": 35,
    "ism": 35,
    "retail-sales": 35,
    "jobless-claims": 35,
}


def _macro_subtype_to_risk(sub_type: str) -> int:
    """sub_typeベースでrisk_scoreを返す。未知のsub_typeは30。"""
    return _RISK_BY_SUBTYPE.get(sub_type, 30)


def _parse_fmp_datetime(date_str: str) -> Optional[datetime]:
    """FMP日付文字列をパース。"Z"末尾やスペース区切りに対応。"""
    if not date_str:
        return None
    # "Z" → "+00:00" に変換（fromisoformatの互換性）
    cleaned = date_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def fetch_fmp_macro_events(
    api_key: str,
    start: str,
    end: str,
    macro_rules: list,
    country: str = "US",
) -> List[Event]:
    """FMP Economic Calendar -> macro Events

    Args:
        api_key: FMP API key
        start: YYYY-MM-DD
        end: YYYY-MM-DD
        macro_rules: AppConfig.macro_rules_compiled() の戻り値
            [(re.Pattern, MacroTitleRule), ...]
        country: フィルタ対象国コード (default: "US")
    """
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    all_data: list = []
    cursor = start_dt
    while cursor <= end_dt:  # C. 境界修正: < → <=
        chunk_end = min(cursor + timedelta(days=89), end_dt)
        chunk_start_str = cursor.strftime("%Y-%m-%d")
        chunk_end_str = chunk_end.strftime("%Y-%m-%d")

        url = f"{FMP_BASE}/economic-calendar"
        params = {
            "from": chunk_start_str,
            "to": chunk_end_str,
            "apikey": api_key,
        }

        logger.info("FMP macro: fetching %s -> %s", chunk_start_str, chunk_end_str)
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        chunk_data = resp.json()

        # D. エラーレスポンスの見える化
        if isinstance(chunk_data, dict):
            error_msg = chunk_data.get("Error Message") or chunk_data.get("error") or str(chunk_data)
            logger.warning("FMP macro: API returned dict (possible error): %s", error_msg[:200])
        elif isinstance(chunk_data, list):
            all_data.extend(chunk_data)
        else:
            logger.warning("FMP macro: unexpected response type: %s", type(chunk_data))

        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.5)

    # countryフィルタ
    us_items = [item for item in all_data
                if (item.get("country") or "").upper().strip() == country.upper()]

    events: List[Event] = []
    unmatched_names: list = []  # F. 未マッチイベント名を収集

    for item in us_items:
        event_name = item.get("event") or ""
        date_str = item.get("date") or ""

        # macro_title_mapでフィルタ
        match = _match_macro_event(event_name, macro_rules)
        if match is None:
            unmatched_names.append(event_name)
            continue

        entity, sub_type = match

        # E. パース耐性強化
        dt = _parse_fmp_datetime(date_str)
        if dt is None:
            logger.debug("FMP macro: skip unparseable date: %s (%s)", date_str, event_name)
            continue

        # B. sub_typeベースのrisk_score
        risk = _macro_subtype_to_risk(sub_type)

        estimate = item.get("estimate")
        previous = item.get("previous")
        evidence_parts = [f"FMP Economic Calendar: {event_name}"]
        if previous is not None:
            evidence_parts.append(f"prev={previous}")
        if estimate is not None:
            evidence_parts.append(f"est={estimate}")
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
            confidence=0.95,
            source_name="fmp_economic",
            source_url=None,
            source_id=f"fmp_eco:{entity}:{sub_type}:{date_str[:10]}",
            evidence=evidence,
            action="add",
        )
        events.append(ev)

    # F. 観測性: raw/matched/dropped + 未マッチTop10
    logger.info(
        "FMP macro: raw_items=%d, us_items=%d, matched=%d, dropped=%d",
        len(all_data), len(us_items), len(events), len(unmatched_names),
    )
    if unmatched_names:
        from collections import Counter
        top_unmatched = Counter(unmatched_names).most_common(10)
        logger.info("FMP macro: top unmatched events: %s", top_unmatched)

    return events
