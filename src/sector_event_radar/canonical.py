from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .config import AppConfig, MacroTitleRule
from .models import Event
from .utils import slugify_ascii, short_hash


def _date_yyyy_mm_dd(dt: datetime) -> str:
    return dt.date().isoformat()


def _macro_entity_subtype_from_title(title: str, cfg: AppConfig) -> Optional[Tuple[str, str]]:
    for pat, rule in cfg.macro_rules_compiled():
        if pat.search(title):
            return (rule.entity.lower(), rule.sub_type.lower())
    return None


def _entity_from_tags(tags: list[str]) -> Optional[str]:
    # sector_tagsにティッカーが入っている前提の軽量推定
    for t in tags:
        t2 = t.strip().upper()
        if 1 <= len(t2) <= 6 and t2.isalnum():
            return t2.lower()
    return None


def make_canonical_key(event: Event, cfg: AppConfig, disambiguate_unscheduled: bool = True) -> str:
    """Spec: {category}:{entity}:{sub_type}:{YYYY-MM-DD} (lowercase ASCII only)"""
    category = event.category.lower()
    d = _date_yyyy_mm_dd(event.start_at)

    if category == "macro":
        inferred = _macro_entity_subtype_from_title(event.title, cfg)
        if inferred:
            entity, sub_type = inferred
        else:
            # マクロだが判別できない場合はタイトルからslug化して粒度を確保
            entity = "us"
            sub_type = slugify_ascii(event.title, max_len=32)

    elif category == "flows":
        entity = "us"
        if "opex" in event.title.lower() or "options" in event.title.lower():
            sub_type = "opex"
        else:
            sub_type = slugify_ascii(event.title, max_len=32)

    elif category == "bellwether":
        entity = _entity_from_tags(event.sector_tags) or "unknown"
        sub_type = "earnings" if "earn" in event.title.lower() else slugify_ascii(event.title, max_len=32)

    elif category == "sector":
        entity = "semis"
        sub_type = slugify_ascii(event.title, max_len=40)

    elif category == "shock":
        entity = "global"
        base = slugify_ascii(event.title, max_len=40)
        if disambiguate_unscheduled:
            # source_url or source_id でhash → タイトル表記揺れに強い
            # 同一ソースからの同一記事は同じhash → dedup成立
            # 別ソースからの同一トピックは別hash → 衝突回避
            hash_source = str(event.source_url or event.source_id)
            base = f"{base}-{short_hash(hash_source, 8)}"
        sub_type = base

    else:
        entity = "unknown"
        sub_type = slugify_ascii(event.title, max_len=40)

    # 追加のASCII安全化（念のため）
    entity = slugify_ascii(entity, max_len=24)
    sub_type = slugify_ascii(sub_type, max_len=48)

    return f"{category}:{entity}:{sub_type}:{d}"
