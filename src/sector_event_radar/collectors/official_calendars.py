"""Official government calendar collectors: BLS .ics + BEA .ics + FOMC static

Data sources (all free, auto-updating, authoritative):
  BLS: https://www.bls.gov/schedule/news_release/bls.ics
    - Consumer Price Index (CPI)
    - Employment Situation (NFP)
    - Producer Price Index (PPI)
    - Format: DTSTART;TZID=US-Eastern:YYYYMMDDTHHMMSS

  BEA: https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics
    - Gross Domestic Product (GDP)
    - Personal Income and Outlays (PCE)
    - Format: DTSTART:YYYYMMDDTHHMMSSZ  (UTC)

  FOMC: Static dates from config.yaml (FRB page requires HTML parsing)
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from ..config import AppConfig, MacroTitleRule
from ..models import Event

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FRB_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

_HTTP_HEADERS = {
    "User-Agent": (
        "sector-event-radar/1.0 "
        "(+https://github.com/yukissssss/sector-event-radar)"
    ),
    "Accept": "text/html, text/calendar, text/plain;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# BLS HTML schedule pages (fallback when .ics is blocked)
BLS_HTML_SCHEDULES: Dict[str, Dict[str, str]] = {
    "cpi": {
        "url": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "title": "Consumer Price Index",
    },
    "nfp": {
        "url": "https://www.bls.gov/schedule/news_release/empsit.htm",
        "title": "Employment Situation",
    },
    "ppi": {
        "url": "https://www.bls.gov/schedule/news_release/ppi.htm",
        "title": "Producer Price Index",
    },
}

_MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Matches "Dec. 18, 2025" or "Mar 11, 2026"
_HTML_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[.]?\s+(\d{1,2}),\s+(\d{4})"
)
# Matches "08:30 AM"
_HTML_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE)

# risk_score by sub_type (same scale as FMP macro collector)
_RISK_BY_SUBTYPE: Dict[str, int] = {
    "fomc": 60,
    "cpi": 50,
    "nfp": 50,
    "pce": 45,
    "gdp": 45,
    "ppi": 35,
    "jobless-claims": 30,
    "ism": 35,
    "retail-sales": 30,
}


# ── ICS VEVENT parser ────────────────────────────────────

def _unfold_ics(text: str) -> str:
    """RFC5545 line unfolding: CRLF + LWSP → continuation."""
    return re.sub(r'\r?\n[ \t]', '', text)


def _parse_vevent_blocks(ics_text: str) -> List[Dict[str, str]]:
    """Extract VEVENT blocks from ICS text into list of {prop: value} dicts."""
    unfolded = _unfold_ics(ics_text)
    events: List[Dict[str, str]] = []
    in_event = False
    current: Dict[str, str] = {}

    for line in unfolded.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT":
            if current:
                events.append(current)
            in_event = False
            current = {}
        elif in_event and ":" in line:
            key_part, _, value = line.partition(":")
            current[key_part] = value

    return events


def _parse_datetime_flexible(val: str) -> Optional[datetime]:
    """Parse ICS datetime string with multiple format support.

    Handles: YYYYMMDDTHHMMSS, YYYYMMDDTHHMM (no seconds), YYYYMMDD (date-only)
    """
    val = val.strip()

    # Date-only
    if len(val) == 8 and val.isdigit():
        return datetime.strptime(val, "%Y%m%d")

    # Strip trailing Z for UTC (handled by caller)
    bare = val.rstrip("Z")

    # Length-based dispatch to avoid strptime greedy matching
    # YYYYMMDDTHHMMSS = 15 chars, YYYYMMDDTHHMM = 13 chars
    if len(bare) == 15:
        try:
            return datetime.strptime(bare, "%Y%m%dT%H%M%S")
        except ValueError:
            pass
    elif len(bare) == 13:
        try:
            return datetime.strptime(bare, "%Y%m%dT%H%M")
        except ValueError:
            pass

    return None


def _parse_dtstart(vevent: Dict[str, str]) -> Optional[datetime]:
    """Parse DTSTART from a VEVENT dict. Handles timezone variants.

    Patterns seen:
      BLS:  DTSTART;TZID=US-Eastern:20260310T083000
      BEA:  DTSTART:20260327T123000Z
      Also: DTSTART;VALUE=DATE:20260310  (date-only)
      Also: DTSTART:20260310T0830       (no seconds)
    """
    dtstart_key = None
    dtstart_val = None
    for k, v in vevent.items():
        if k.startswith("DTSTART"):
            dtstart_key = k
            dtstart_val = v
            break

    if not dtstart_key or not dtstart_val:
        return None

    dtstart_val = dtstart_val.strip()

    try:
        # Date-only (VALUE=DATE)
        if len(dtstart_val) == 8 and dtstart_val.isdigit():
            dt = datetime.strptime(dtstart_val, "%Y%m%d")
            return dt.replace(hour=8, minute=30, tzinfo=ET)

        # UTC (trailing Z)
        if dtstart_val.endswith("Z"):
            dt = _parse_datetime_flexible(dtstart_val)
            if dt is None:
                return None
            return dt.replace(tzinfo=UTC)

        # Datetime without Z
        dt = _parse_datetime_flexible(dtstart_val)
        if dt is None:
            return None

        if "TZID" in dtstart_key:
            tzid = dtstart_key.split("TZID=", 1)[-1].split(":")[0] if "TZID=" in dtstart_key else ""
            if "eastern" in tzid.lower() or "us-eastern" in tzid.lower():
                return dt.replace(tzinfo=ET)
            elif "central" in tzid.lower():
                return dt.replace(tzinfo=ZoneInfo("America/Chicago"))
            elif "pacific" in tzid.lower():
                return dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
            else:
                logger.debug("Unknown TZID '%s', assuming ET", tzid)
                return dt.replace(tzinfo=ET)

        # No timezone → assume ET for US government sources
        return dt.replace(tzinfo=ET)

    except (ValueError, TypeError) as e:
        logger.debug("Failed to parse DTSTART '%s': %s", dtstart_val, e)
        return None


def _get_summary(vevent: Dict[str, str]) -> str:
    """Extract SUMMARY from VEVENT dict."""
    for k, v in vevent.items():
        if k.startswith("SUMMARY"):
            return v.strip()
    return ""


# ── Event matching ────────────────────────────────────────

def _match_and_build_event(
    summary: str,
    dt: datetime,
    source_name: str,
    source_url: str,
    macro_rules: List[Tuple[re.Pattern, MacroTitleRule]],
) -> Optional[Event]:
    """Match VEVENT summary against precompiled macro rules → Event or None."""
    for pat, rule in macro_rules:
        if pat.search(summary):
            sub_type = rule.sub_type.lower()
            risk = _RISK_BY_SUBTYPE.get(sub_type, 35)

            evidence = f"{source_name}: {summary}, {dt.strftime('%Y-%m-%d %H:%M %Z')}"
            if len(evidence) > 280:
                evidence = evidence[:277] + "..."

            return Event(
                canonical_key=None,
                title=summary,
                start_at=dt,
                end_at=None,
                category="macro",
                sector_tags=[],
                risk_score=risk,
                confidence=0.95,
                source_name=source_name,
                source_url=source_url,
                source_id=f"{source_name}:{sub_type}:{dt.strftime('%Y-%m-%d')}",
                evidence=evidence,
                action="add",
            )
    return None


# ── Public API ────────────────────────────────────────────

def fetch_ics_macro_events(
    ics_url: str,
    source_name: str,
    cfg: AppConfig,
    start: datetime,
    end: datetime,
    timeout: int = 30,
) -> List[Event]:
    """Fetch and parse a government .ics feed → macro Events.

    Args:
        ics_url: URL to .ics calendar feed
        source_name: e.g. "bls" or "bea"
        cfg: AppConfig with macro_title_map
        start: only include events on or after this datetime
        end: only include events on or before this datetime
        timeout: HTTP request timeout
    """
    logger.info("%s: fetching %s", source_name.upper(), ics_url)
    resp = requests.get(ics_url, headers=_HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()

    vevents = _parse_vevent_blocks(resp.text)
    logger.info("%s: parsed %d VEVENT blocks", source_name.upper(), len(vevents))

    # Compile rules once per call (not per event)
    macro_rules = cfg.macro_rules_compiled()

    events: List[Event] = []
    matched_counter: Counter = Counter()
    unmatched_counter: Counter = Counter()

    for ve in vevents:
        summary = _get_summary(ve)
        dt = _parse_dtstart(ve)

        if not summary or not dt:
            continue

        if dt < start or dt > end:
            continue

        ev = _match_and_build_event(summary, dt, source_name, ics_url, macro_rules)
        if ev:
            events.append(ev)
            matched_counter[summary] += 1
        else:
            unmatched_counter[summary] += 1

    # Observability: matched=0 warning (config mismatch detection)
    total_in_range = len(events) + sum(unmatched_counter.values())
    if total_in_range > 0 and len(events) == 0:
        logger.warning(
            "%s: %d events in date range but 0 matched! "
            "Check macro_title_map patterns. Top unmatched: %s",
            source_name.upper(), total_in_range,
            ", ".join(f"'{k}'" for k, _ in unmatched_counter.most_common(5)),
        )
    elif unmatched_counter:
        top_unmatched = unmatched_counter.most_common(5)
        logger.info(
            "%s: %d matched, %d unmatched (top: %s)",
            source_name.upper(), len(events), sum(unmatched_counter.values()),
            ", ".join(f"'{k}'({v})" for k, v in top_unmatched),
        )
    else:
        logger.info("%s: %d matched, 0 unmatched", source_name.upper(), len(events))

    return events


def generate_fomc_events(
    fomc_dates: List[str],
    start: datetime,
    end: datetime,
) -> List[Event]:
    """Generate FOMC meeting events from static date list in config.

    Args:
        fomc_dates: list of "YYYY-MM-DD" strings (announcement dates, day 2)
        start: filter start
        end: filter end
    """
    events: List[Event] = []

    for date_str in fomc_dates:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dt = dt.replace(hour=14, minute=0, tzinfo=ET)
        except (ValueError, TypeError) as e:
            logger.warning("FOMC: invalid date '%s': %s", date_str, e)
            continue

        if dt < start or dt > end:
            continue

        ev = Event(
            canonical_key=None,
            title="FOMC Rate Decision",
            start_at=dt,
            end_at=None,
            category="macro",
            sector_tags=[],
            risk_score=60,
            confidence=1.0,
            source_name="frb",
            source_url=FRB_FOMC_URL,
            source_id=f"frb:fomc:{date_str}",
            evidence=f"FRB: FOMC meeting {date_str}, announcement 14:00 ET",
            action="add",
        )
        events.append(ev)

    logger.info("FOMC: %d events from %d configured dates", len(events), len(fomc_dates))
    return events


# ── BLS HTML fallback ─────────────────────────────────────

def _parse_bls_html_table(html: str) -> List[datetime]:
    """Parse BLS schedule HTML table → list of release datetimes (ET).

    Table format: Reference Month | Release Date | Release Time
    Date format:  "Mar. 11, 2026"  Time format: "08:30 AM"
    """
    results: List[datetime] = []

    # Extract table rows
    rows = re.split(r"<tr[^>]*>", html, flags=re.IGNORECASE)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue

        # Strip HTML tags from cells
        date_text = re.sub(r"<[^>]+>", "", cells[1]).strip()
        time_text = re.sub(r"<[^>]+>", "", cells[2]).strip()

        date_m = _HTML_DATE_RE.search(date_text)
        if not date_m:
            continue

        month = _MONTH_ABBR.get(date_m.group(1))
        day = int(date_m.group(2))
        year = int(date_m.group(3))
        if not month:
            continue

        # Default: 08:30 AM ET (standard BLS release time)
        hour, minute = 8, 30
        time_m = _HTML_TIME_RE.search(time_text)
        if time_m:
            hour = int(time_m.group(1))
            minute = int(time_m.group(2))
            ampm = time_m.group(3).upper()
            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

        try:
            dt = datetime(year, month, day, hour, minute, tzinfo=ET)
            results.append(dt)
        except ValueError:
            continue

    return results


def fetch_bls_html_events(
    start: datetime,
    end: datetime,
    timeout: int = 30,
) -> List[Event]:
    """Fallback: parse BLS HTML schedule pages for CPI/NFP/PPI release dates."""
    events: List[Event] = []

    for sub_type, info in BLS_HTML_SCHEDULES.items():
        url = info["url"]
        title = info["title"]
        count = 0

        try:
            logger.info("BLS HTML fallback: fetching %s from %s", sub_type.upper(), url)
            resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
            resp.raise_for_status()

            dates = _parse_bls_html_table(resp.text)

            for dt in dates:
                if dt < start or dt > end:
                    continue

                risk = _RISK_BY_SUBTYPE.get(sub_type, 35)
                date_str = dt.strftime("%Y-%m-%d")
                evidence = f"BLS HTML: {title}, {dt.strftime('%Y-%m-%d %H:%M %Z')}"

                ev = Event(
                    canonical_key=None,
                    title=title,
                    start_at=dt,
                    end_at=None,
                    category="macro",
                    sector_tags=[],
                    risk_score=risk,
                    confidence=0.95,
                    source_name="bls",
                    source_url=url,
                    source_id=f"bls:{sub_type}:{date_str}",
                    evidence=evidence,
                    action="add",
                )
                events.append(ev)
                count += 1

            logger.info("BLS HTML: %s → %d events in range", sub_type.upper(), count)
        except Exception as e:
            logger.warning("BLS HTML fallback failed for %s: %s", sub_type.upper(), e)

    return events


# ── BLS static YAML ──────────────────────────────────────

_BLS_TITLE_MAP: Dict[str, str] = {
    "cpi": "Consumer Price Index",
    "nfp": "Employment Situation",
    "ppi": "Producer Price Index",
}

_BLS_SOURCE_URL_MAP: Dict[str, str] = {
    "cpi": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "nfp": "https://www.bls.gov/schedule/news_release/empsit.htm",
    "ppi": "https://www.bls.gov/schedule/news_release/ppi.htm",
}


def generate_bls_static_events(
    bls_static: Dict,
    start: datetime,
    end: datetime,
) -> List[Event]:
    """Generate BLS events from static date config (YAML).

    Args:
        bls_static: dict with timezone, default_time, years.{year}.{sub_type}
        start: filter start
        end: filter end
    """
    tz_name = bls_static.get("timezone", "America/New_York")
    tz = ZoneInfo(tz_name)
    default_time = bls_static.get("default_time", "08:30")
    hour, minute = (int(x) for x in default_time.split(":"))

    years_data = bls_static.get("years", {})
    events: List[Event] = []
    counts: Dict[str, int] = {}

    for year_str, indicators in years_data.items():
        for sub_type, dates in indicators.items():
            title = _BLS_TITLE_MAP.get(sub_type, sub_type.upper())
            source_url = _BLS_SOURCE_URL_MAP.get(sub_type, "https://www.bls.gov/schedule/")
            risk = _RISK_BY_SUBTYPE.get(sub_type, 35)

            for date_str in dates:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    dt = dt.replace(hour=hour, minute=minute, tzinfo=tz)
                except (ValueError, TypeError) as e:
                    logger.warning("BLS static: invalid date '%s': %s", date_str, e)
                    continue

                if dt < start or dt > end:
                    continue

                ev = Event(
                    canonical_key=None,
                    title=title,
                    start_at=dt,
                    end_at=None,
                    category="macro",
                    sector_tags=[],
                    risk_score=risk,
                    confidence=1.0,
                    source_name="bls",
                    source_url=source_url,
                    source_id=f"bls:{sub_type}:{date_str}",
                    evidence=f"BLS static: {title}, {dt.strftime('%Y-%m-%d %H:%M %Z')}",
                    action="add",
                )
                events.append(ev)
                counts[sub_type] = counts.get(sub_type, 0) + 1

    # Observability: warn if any indicator has 0 events in range
    for sub_type in _BLS_TITLE_MAP:
        if counts.get(sub_type, 0) == 0:
            logger.warning(
                "BLS static: %s has 0 events in range %s — %s. "
                "Check bls_static.years config for current year.",
                sub_type.upper(),
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )

    logger.info(
        "BLS static: %d events (%s)",
        len(events),
        ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
    )
    return events


def fetch_official_macro_events(
    cfg: AppConfig,
    start: datetime,
    end: datetime,
) -> Tuple[List[Event], List[str]]:
    """Main entry: collect from BLS + BEA + FOMC. Each source independent try/except.

    Returns:
        (events, errors) tuple matching partial failure design
    """
    events: List[Event] = []
    errors: List[str] = []

    # BLS — mode-based dispatch
    bls_mode = getattr(cfg, 'bls_mode', 'static')

    if bls_mode == "ics":
        # Try .ics first, fall back to HTML, then static
        try:
            bls = fetch_ics_macro_events(BLS_ICS_URL, "bls", cfg, start, end)
            events.extend(bls)
        except Exception as e:
            logger.warning("BLS .ics failed: %s — trying HTML fallback", e)
            try:
                bls = fetch_bls_html_events(start, end)
                events.extend(bls)
            except Exception as e2:
                logger.warning("BLS HTML fallback also failed: %s — falling back to static", e2)
                bls_static = getattr(cfg, 'bls_static', None)
                if bls_static:
                    bls = generate_bls_static_events(bls_static, start, end)
                    events.extend(bls)
                else:
                    msg = "BLS collector failed (ics/html/static all unavailable)"
                    logger.warning(msg)
                    errors.append(msg)
    else:
        # Static mode: skip HTTP entirely (GitHub Actions IP blocked)
        bls_static = getattr(cfg, 'bls_static', None)
        if bls_static:
            bls = generate_bls_static_events(bls_static, start, end)
            events.extend(bls)
        else:
            msg = "BLS static mode but no bls_static config found"
            logger.warning(msg)
            errors.append(msg)

    # BEA
    try:
        bea = fetch_ics_macro_events(BEA_ICS_URL, "bea", cfg, start, end)
        events.extend(bea)
    except Exception as e:
        msg = f"BEA collector failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    # FOMC (static dates from config)
    fomc_dates = getattr(cfg, 'fomc_dates', [])
    if fomc_dates:
        try:
            fomc = generate_fomc_events(fomc_dates, start, end)
            events.extend(fomc)
        except Exception as e:
            msg = f"FOMC generator failed: {e}"
            logger.warning(msg)
            errors.append(msg)
    else:
        logger.info("FOMC: no fomc_dates configured, skipping")

    logger.info("Official macro: total %d events (%d errors)", len(events), len(errors))
    return events, errors
