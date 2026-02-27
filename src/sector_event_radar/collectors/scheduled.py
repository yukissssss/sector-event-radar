from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

from ..models import Event

NY_TZ = ZoneInfo("America/New_York")


def fetch_tradingeconomics_events(api_key: str, start: str, end: str) -> List[Event]:
    """Scheduled Source: TradingEconomics (macro)
    - 実際のエンドポイントは運用環境に合わせて実装してください。
    - ここでは「戻り値がEventのListである」契約だけ固定します。
    """
    # TODO: implement with the correct endpoint
    return []


def fetch_fmp_earnings_events(api_key: str, start: str, end: str) -> List[Event]:
    """Scheduled Source: Financial Modeling Prep (earnings)
    - 実際のエンドポイントは運用環境に合わせて実装してください。
    """
    # TODO: implement with the correct endpoint
    return []
