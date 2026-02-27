from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field


class PrefilterConfig(BaseModel):
    stage_a_threshold: float = 6.0
    stage_b_top_k: int = 30


class MacroTitleRule(BaseModel):
    entity: str
    sub_type: str


class RssSource(BaseModel):
    name: str
    url: str


class SourcesConfig(BaseModel):
    rss: List[RssSource] = Field(default_factory=list)


class AppConfig(BaseModel):
    keywords: Dict[str, float] = Field(default_factory=dict)
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    macro_title_map: Dict[str, MacroTitleRule] = Field(default_factory=dict)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    bellwether_tickers: List[str] = Field(
        default_factory=lambda: ["NVDA", "TSM", "ASML", "AMD", "AVGO",
                                  "MSFT", "GOOGL", "AMZN", "META"]
    )
    te_country: str = "united states"
    te_importance: int = 3

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def macro_rules_compiled(self) -> List[Tuple[re.Pattern, MacroTitleRule]]:
        compiled: List[Tuple[re.Pattern, MacroTitleRule]] = []
        for pattern, rule in self.macro_title_map.items():
            compiled.append((re.compile(pattern), rule))
        return compiled
