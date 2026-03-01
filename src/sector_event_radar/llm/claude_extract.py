"""M2: Claude抽出器 — RSS記事からイベントをStrict Tool Useで抽出

仕様上の受入基準:
- 本文に日時が明示されていない記事は必ず events=[] を返す
- 幻覚率0%（日時推測・捏造の禁止）
- evidence フィールドは本文からの引用（1行で検証可能）
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import List

import requests
from pydantic import ValidationError

from ..models import Event

logger = logging.getLogger(__name__)

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


@dataclass(frozen=True)
class ClaudeConfig:
    api_key: str
    model: str = "claude-sonnet-4-20250514"
    max_retries: int = 5
    timeout_sec: int = 60


class ClaudeExtractError(RuntimeError):
    pass


# ── Strict Tool Schema ──────────────────────────────────
EMIT_EVENTS_TOOL = {
    "name": "emit_events",
    "description": (
        "Return extracted events as structured JSON. "
        "Only include events with explicit date/time found in the article text. "
        "If no explicit date/time is found, return events as an empty array []."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short event title in English"
                        },
                        "start_at": {
                            "type": "string",
                            "description": "ISO8601 datetime with timezone, e.g. 2026-03-12T08:30:00-05:00"
                        },
                        "end_at": {
                            "type": ["string", "null"],
                            "description": (
                                "ISO8601 end time or null. "
                                "For quarter-only, month-only, or half-year-only expressions, ALWAYS use null."
                            )
                        },
                        "category": {
                            "type": "string",
                            "enum": ["macro", "bellwether", "flows", "shock"],
                            "description": "Event category"
                        },
                        "sector_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Related tickers or sector tags, e.g. ['NVDA', 'semis']"
                        },
                        "risk_score": {
                            "type": "integer",
                            "description": "0-100 impact score. macro>=20, shock>=30"
                        },
                        "confidence": {
                            "type": "number",
                            "description": (
                                "0.0-1.0 extraction confidence. "
                                "Exact date → 0.8-0.95. Quarter/month/half-year only → 0.4-0.6."
                            )
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Verbatim quote from article proving the date/time. 12-280 chars."
                        },
                        "action": {
                            "type": "string",
                            "enum": ["add", "update", "cancel"],
                            "description": "add=new event, update=date/detail changed, cancel=event cancelled"
                        }
                    },
                    "required": [
                        "title", "start_at", "category", "sector_tags",
                        "risk_score", "confidence", "evidence", "action"
                    ]
                }
            }
        },
        "required": ["events"]
    }
}

SYSTEM_PROMPT = """You are an event extractor for an AI semiconductor sector calendar.

RULES (strictly follow all):
1. Extract ONLY events with an EXPLICIT date or datetime in the article text. Explicit quarter/month/half-year expressions with a year (e.g. "Q2 2026", "March 2026", "1H26") are considered explicit time references.
2. If no explicit date/time is found, you MUST return events=[].
3. Vague expressions like "soon", "later this year", "in the coming weeks" are NOT explicit dates. Return events=[] for these.
4. The "evidence" field MUST be a verbatim quote from the article that contains the date/time. Keep it 12-280 characters.
5. Do NOT predict, guess, or infer dates that are not stated in the text.
6. Category rules: macro=economic indicators (CPI/FOMC/NFP), bellwether=earnings of major companies, flows=options/rebalancing events, shock=sudden regulatory/supply events.
7. risk_score: macro events >= 20, shock events >= 30.
8. Use ISO8601 format with timezone for start_at. If only a date is given (no time), use T00:00:00Z.
9. source_name and source_url will be added by the caller. Do not include them.
10. IMPORTANT (calendar noise guard): Do NOT create multi-day range events for quarter-only, month-only, or half-year-only expressions. These must be point-in-time placeholders with end_at=null.
11. Quarter-only expressions (e.g. "2Q26", "Q2 2026", "second quarter of 2026"):
    - start_at = first day of the quarter at T00:00:00Z (Q1=Jan 1, Q2=Apr 1, Q3=Jul 1, Q4=Oct 1)
    - end_at = null (NEVER set end_at to the last day of the quarter)
    - confidence = 0.4-0.6 (lower than exact dates)
12. Month-only and half-year-only expressions:
    - "March 2026": start_at = 2026-03-01T00:00:00Z, end_at = null
    - "1H26" or "first half of 2026": start_at = 2026-01-01T00:00:00Z, end_at = null
    - "H2 2026" or "second half of 2026": start_at = 2026-07-01T00:00:00Z, end_at = null
    - confidence = 0.4-0.6 (lower than exact dates)"""


def _build_headers(api_key: str) -> dict:
    """Anthropic API は x-api-key ヘッダで認証（Bearer ではない）"""
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }


def _parse_tool_output(response_json: dict) -> dict | None:
    """Anthropic Messages APIのレスポンスからtool_use blockのinputを取り出す"""
    content = response_json.get("content", [])
    for block in content:
        if block.get("type") == "tool_use" and block.get("name") == "emit_events":
            return block.get("input")
    return None


def extract_events_from_article(
    cfg: ClaudeConfig,
    article_title: str,
    article_published: str,
    article_url: str,
    article_content: str,
) -> List[Event]:
    """RSS記事1本からイベントを抽出。

    Returns:
        List[Event]: 抽出されたイベント。日時不明なら空リスト。
        source_name / source_url / source_id は呼び出し元で設定すること。
    """
    headers = _build_headers(cfg.api_key)

    user_text = (
        f"TITLE: {article_title}\n"
        f"PUBLISHED: {article_published}\n"
        f"URL: {article_url}\n\n"
        f"CONTENT:\n{article_content[:8000]}"
    )

    payload = {
        "model": cfg.model,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
        "tools": [EMIT_EVENTS_TOOL],
        "tool_choice": {"type": "tool", "name": "emit_events"},
    }

    backoff = 1.0
    last_error = None

    for attempt in range(cfg.max_retries):
        try:
            resp = requests.post(
                ANTHROPIC_ENDPOINT,
                headers=headers,
                data=json.dumps(payload),
                timeout=cfg.timeout_sec,
            )
        except requests.RequestException as e:
            logger.warning("Claude API request failed (attempt %d): %s", attempt + 1, e)
            last_error = e
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            sleep_s = float(retry_after) if retry_after else backoff
            logger.warning("Claude API 429, sleeping %.1fs (attempt %d)", sleep_s, attempt + 1)
            time.sleep(sleep_s)
            backoff = min(backoff * 2, 30)
            continue

        if resp.status_code == 529:
            logger.warning("Claude API 529 overloaded, sleeping %.1fs", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue

        if resp.status_code >= 400:
            raise ClaudeExtractError(
                f"Claude API error {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        tool_output = _parse_tool_output(data)

        if tool_output is None:
            logger.warning("No emit_events tool_use block in response")
            return []

        raw_events = tool_output.get("events", [])
        if not raw_events:
            return []

        events: List[Event] = []
        for raw in raw_events:
            # source_id をイベント単位でユニークにする。
            # 1記事→複数イベント時にevent_sourcesの(source_name, source_id)主キーが
            # 衝突して最後のイベントだけ残る事故を防止。
            ev_title = raw.get("title", "")
            ev_start = raw.get("start_at", "")
            ev_hash = hashlib.sha256(f"{ev_title}:{ev_start}".encode()).hexdigest()[:8]
            raw.setdefault("source_name", "claude_extract")
            raw.setdefault("source_url", article_url)
            raw.setdefault("source_id", f"claude:{article_url}#{ev_hash}")
            raw.setdefault("end_at", None)
            try:
                ev = Event.model_validate(raw)
                events.append(ev)
            except ValidationError as e:
                logger.warning("Event validation failed, skipping: %s", e)
                continue

        return events

    raise ClaudeExtractError(
        f"Claude API: max retries ({cfg.max_retries}) exceeded. Last error: {last_error}"
    )
