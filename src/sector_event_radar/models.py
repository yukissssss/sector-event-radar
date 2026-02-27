from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, conint, confloat


class Article(BaseModel):
    title: str
    body: str = ""
    url: str
    published: str = ""  # ISO8601文字列を想定（RSS由来は揺れるので文字列で保持）


class Event(BaseModel):
    # --- Spec v1.0 準拠 (3. Event Schema) ---
    canonical_key: Optional[str] = None
    title: str
    start_at: datetime
    end_at: Optional[datetime] = None
    category: Literal["macro", "sector", "bellwether", "flows", "shock"]
    sector_tags: List[str] = Field(default_factory=list)
    risk_score: conint(ge=0, le=100)
    confidence: confloat(ge=0.0, le=1.0)
    source_name: str
    source_url: Optional[HttpUrl] = None  # computedイベントはNone
    source_id: str
    evidence: str = Field(min_length=1, max_length=280)
    action: Literal["add", "update", "cancel", "ignore"]


class ImpactStats(BaseModel):
    n: int
    mean: float
    median: float
    min: float
    max: float


class Scenario(BaseModel):
    label: Literal["up", "flat", "down"]
    description: str
    stats: dict  # {ticker: ImpactStats} を想定（ここは柔軟に）


class ImpactSummary(BaseModel):
    scenario_up: Scenario
    scenario_flat: Scenario
    scenario_down: Scenario
    historical_stats: dict  # raw stats dump (python側で作った確定値)
