from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MappingChange:
    mapping_key: str
    ticker: str
    old_ratio: float
    new_ratio: float
    recommendation: str


def _mean_abs_return(prices: pd.Series) -> float:
    r = prices.pct_change().abs().dropna()
    if r.empty:
        return float("nan")
    return float(r.mean())


def reaction_ratio(prices: pd.Series, event_dates: List[date]) -> float:
    """Reaction Ratio = mean(|return| on event days) / mean(|return| on non-event days)"""
    px = prices.copy().dropna()
    if px.empty:
        return float("nan")

    r = px.pct_change().abs().dropna()
    if r.empty:
        return float("nan")

    idx_dates = set([d for d in event_dates])
    r_event = r[r.index.date.astype(object).isin(idx_dates)]
    r_non = r[~r.index.date.astype(object).isin(idx_dates)]

    if r_event.empty or r_non.empty:
        return float("nan")

    return float(r_event.mean() / r_non.mean())


def detect_mapping_changes(
    mapping_key: str,
    ticker: str,
    old_ratio: float,
    new_ratio: float,
    weak_threshold: float = 1.5,
    add_threshold: float = 2.5,
) -> List[MappingChange]:
    """Spec M8: ratio < 1.5 → 降格候補、mapping外でratio > 2.5 → 追加候補
    ここでは単一tickerの変化判定だけ行う。
    """
    out: List[MappingChange] = []

    if np.isnan(new_ratio):
        return out

    if new_ratio < weak_threshold:
        out.append(
            MappingChange(
                mapping_key=mapping_key,
                ticker=ticker,
                old_ratio=float(old_ratio),
                new_ratio=float(new_ratio),
                recommendation="weakening: consider demotion/removal",
            )
        )
    elif new_ratio > add_threshold:
        out.append(
            MappingChange(
                mapping_key=mapping_key,
                ticker=ticker,
                old_ratio=float(old_ratio),
                new_ratio=float(new_ratio),
                recommendation="strong reaction: consider adding",
            )
        )

    return out
