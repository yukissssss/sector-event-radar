from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from .models import ImpactStats, ImpactSummary, Scenario


try:
    import yfinance as yf

    _HAS_YF = True
except Exception:
    _HAS_YF = False


def _stats(x: Sequence[float]) -> ImpactStats:
    arr = np.array(list(x), dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return ImpactStats(n=0, mean=float("nan"), median=float("nan"), min=float("nan"), max=float("nan"))
    return ImpactStats(
        n=int(arr.size),
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        min=float(np.min(arr)),
        max=float(np.max(arr)),
    )


def fetch_prices(tickers: List[str], start: date, end: date) -> pd.DataFrame:
    """yFinanceで価格データを取得（Adj Close優先）。"""
    if not _HAS_YF:
        raise RuntimeError("yfinance is not installed. Add it to your environment to use impact module.")

    df = yf.download(
        tickers=tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
    )

    # yfinanceは単一tickerと複数tickerで列構造が変わるので正規化
    if isinstance(df.columns, pd.MultiIndex):
        # prefer Close/Adj Close
        if ("Close" in df.columns.levels[0]) or ("Adj Close" in df.columns.levels[0]):
            field = "Adj Close" if "Adj Close" in df.columns.levels[0] else "Close"
            out = df[field].copy()
        else:
            # fallback to first level
            out = df.xs(df.columns.levels[0][0], axis=1, level=0)
    else:
        # single ticker
        out = df[["Close"]].copy()
        out.columns = [tickers[0]]

    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def event_day_returns(prices: pd.DataFrame, event_dates: List[date]) -> Dict[str, List[float]]:
    """イベント日の1日リターン(close/prev_close-1)を計算。"""
    # indexは日付、列はticker
    idx = pd.to_datetime(prices.index).normalize()
    prices2 = prices.copy()
    prices2.index = idx

    returns: Dict[str, List[float]] = {c: [] for c in prices2.columns}
    for d in event_dates:
        dts = pd.Timestamp(d)
        if dts not in prices2.index:
            # 非取引日はスキップ（別途「直近営業日へ丸める」設計もあり）
            continue
        loc = prices2.index.get_loc(dts)
        if isinstance(loc, slice) or isinstance(loc, np.ndarray):
            continue
        if loc == 0:
            continue
        prev_dt = prices2.index[loc - 1]
        for c in prices2.columns:
            prev = prices2.loc[prev_dt, c]
            cur = prices2.loc[dts, c]
            if pd.isna(prev) or pd.isna(cur) or prev == 0:
                returns[c].append(float("nan"))
            else:
                returns[c].append(float(cur / prev - 1.0))
    return returns


def build_impact_summary(
    tickers: List[str],
    event_dates: List[date],
    start: date,
    end: date,
) -> ImpactSummary:
    """Spec M7 Step2-3 をPython側で確定値として作る。
    Step4(文章化)はここではテンプレで返す（LLM接続は別途）。
    """
    prices = fetch_prices(tickers, start, end)
    rets = event_day_returns(prices, event_dates)

    stats = {t: _stats(v).model_dump() for t, v in rets.items()}

    # シナリオはLLMに渡す前提だが、最低限の構造は返す
    scenario_up = Scenario(label="up", description="historical pattern summary (placeholder)", stats=stats)
    scenario_flat = Scenario(label="flat", description="historical pattern summary (placeholder)", stats=stats)
    scenario_down = Scenario(label="down", description="historical pattern summary (placeholder)", stats=stats)

    return ImpactSummary(
        scenario_up=scenario_up,
        scenario_flat=scenario_flat,
        scenario_down=scenario_down,
        historical_stats=stats,
    )
