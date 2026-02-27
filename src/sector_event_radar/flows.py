from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from zoneinfo import ZoneInfo

from .models import Event

try:
    import pandas as pd
    import exchange_calendars as ecals

    _HAS_EXCHANGE_CAL = True
except Exception:
    _HAS_EXCHANGE_CAL = False


NY_TZ = ZoneInfo("America/New_York")


def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    # 0=Mon ... 4=Fri
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d + timedelta(days=14)


def _add_months(y: int, m: int, add: int) -> tuple[int, int]:
    # month in 1..12
    total = (y * 12 + (m - 1)) + add
    y2 = total // 12
    m2 = (total % 12) + 1
    return y2, m2


def generate_opex_events(start_year: int, start_month: int, months: int) -> List[Event]:
    """Spec M5:
    第3金曜日(OPEX)を計算し、XNYSの休場日なら前営業日にずらす。
    """
    if months <= 0:
        return []

    cal = None
    if _HAS_EXCHANGE_CAL:
        cal = ecals.get_calendar("XNYS")

    out: List[Event] = []
    for i in range(months):
        y, m = _add_months(start_year, start_month, i)
        tf = _third_friday(y, m)
        adj = tf

        if cal is not None:
            ts = pd.Timestamp(tf)
            if not cal.is_session(ts):
                prev = cal.date_to_session(ts, direction="previous")
                adj = prev.date()

        # OPEXは「その日」イベントとして扱い、時刻は16:00 ETに固定（要TZ）
        start_at = datetime(adj.year, adj.month, adj.day, 16, 0, tzinfo=NY_TZ)
        end_at = start_at + timedelta(hours=1)

        out.append(
            Event(
                canonical_key=None,
                title=f"OPEX (US) {adj.isoformat()}",
                start_at=start_at,
                end_at=end_at,
                category="flows",
                sector_tags=["OPEX"],
                risk_score=35,
                confidence=1.0,
                source_name="computed_opex",
                source_url=None,
                source_id=f"opex:{y:04d}-{m:02d}",
                evidence="computed: 3rd Friday adjusted to previous trading day",
                action="add",
            )
        )

    return out
