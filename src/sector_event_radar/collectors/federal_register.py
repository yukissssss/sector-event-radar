"""Federal Register — BIS (Bureau of Industry and Security) コレクター。

APIキー不要のJSON API。構造化フィールドからイベントを確定生成（LLM不要＝幻覚ゼロ）。
- effective_on    → 規制施行日イベント
- comments_close_on → パブコメ締切日イベント

GPT助言: BIS旧RSSは死亡（リダイレクトでHTMLのみ）。Federal Registerが一次ソース。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Tuple

import requests

from ..models import Event

logger = logging.getLogger(__name__)

# Federal Register API — 公式ドキュメント:
# https://www.federalregister.gov/developers/documentation/api/v1
_API_BASE = "https://www.federalregister.gov/api/v1/articles.json"
_BIS_AGENCY = "industry-and-security-bureau"

# 取得フィールド（最小限）
_FIELDS = [
    "title",
    "abstract",
    "html_url",
    "publication_date",
    "effective_on",
    "comments_close_on",
    "type",              # Rule, Proposed Rule, Notice
    "document_number",
]


def fetch_federal_register_bis_events(
    start_date: str,
    end_date: str,
    timeout_sec: int = 20,
) -> Tuple[List[Event], List[str]]:
    """Federal Register APIからBIS関連の規制イベントを取得。

    Args:
        start_date: "YYYY-MM-DD" 取得開始日（publication_date基準）
        end_date: "YYYY-MM-DD" 取得終了日
        timeout_sec: HTTPタイムアウト

    Returns:
        (events, errors) タプル。部分失敗設計準拠。
    """
    events: List[Event] = []
    errors: List[str] = []

    # publication_dateは「過去90日〜今日」で検索。
    # effective_on/comments_close_onが未来のドキュメントだけイベント化する。
    # （引数のstart_date/end_dateはイベント日の許容範囲として使う）
    from datetime import timedelta
    pub_start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    pub_end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        params = {
            "conditions[agencies][]": _BIS_AGENCY,
            "conditions[publication_date][gte]": pub_start,
            "conditions[publication_date][lte]": pub_end,
            "fields[]": _FIELDS,
            "per_page": 50,
            "order": "newest",
        }

        resp = requests.get(
            _API_BASE,
            params=params,
            timeout=timeout_sec,
            headers={"User-Agent": "sector-event-radar/0.1"},
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        logger.info(
            "Federal Register BIS: %d documents fetched (%s to %s)",
            len(results), start_date, end_date,
        )

        for doc in results:
            doc_events = _extract_events_from_document(doc, start_date, end_date)
            events.extend(doc_events)

        logger.info(
            "Federal Register BIS: %d events created from %d documents",
            len(events), len(results),
        )

    except requests.RequestException as e:
        msg = f"Federal Register API failed: {e}"
        logger.warning(msg)
        errors.append(msg)
    except (KeyError, ValueError) as e:
        msg = f"Federal Register parse error: {e}"
        logger.warning(msg)
        errors.append(msg)

    return events, errors


def _extract_events_from_document(
    doc: dict,
    event_start: str = "",
    event_end: str = "",
) -> List[Event]:
    """1つのFederal Register文書から0-2件のイベントを生成。

    - effective_on があれば → 施行日イベント
    - comments_close_on があれば → パブコメ締切イベント
    - どちらもなければ → 0件（ノイズ殺し）
    - event_start/event_end: イベント日の許容範囲（YYYY-MM-DD）。範囲外はスキップ。
    """
    events: List[Event] = []

    title = doc.get("title", "").strip()
    html_url = doc.get("html_url", "")
    abstract = doc.get("abstract", "") or ""
    doc_type = doc.get("type", "Notice")
    doc_number = doc.get("document_number", "")

    if not title or not html_url:
        return events

    # evidence: abstract先頭280文字（Event.evidence max_length=280）
    evidence = abstract[:270].strip() if abstract else f"Federal Register {doc_type}: {doc_number}"
    if len(evidence) < 12:
        evidence = f"Federal Register {doc_type}: {title[:250]}"

    # ── effective_on → 施行日イベント ──
    effective_on = doc.get("effective_on")
    if effective_on:
        try:
            dt = _parse_date(effective_on)
            if not _in_date_range(dt, event_start, event_end):
                logger.debug("Skipping effective_on %s (out of range)", effective_on)
            else:
                events.append(_build_event(
                title=f"BIS Rule Effective: {title[:180]}",
                start_at=dt,
                source_url=html_url,
                evidence=evidence,
                doc_number=doc_number,
                sub_type="effective",
                ))
        except ValueError:
            logger.debug("Skipping invalid effective_on: %s", effective_on)

    # ── comments_close_on → パブコメ締切イベント ──
    comments_close = doc.get("comments_close_on")
    if comments_close:
        try:
            dt = _parse_date(comments_close)
            if not _in_date_range(dt, event_start, event_end):
                logger.debug("Skipping comments_close_on %s (out of range)", comments_close)
            else:
                events.append(_build_event(
                title=f"BIS Comment Deadline: {title[:170]}",
                start_at=dt,
                source_url=html_url,
                evidence=evidence,
                doc_number=doc_number,
                sub_type="comment_deadline",
                ))
        except ValueError:
            logger.debug("Skipping invalid comments_close_on: %s", comments_close)

    return events


def _build_event(
    title: str,
    start_at: datetime,
    source_url: str,
    evidence: str,
    doc_number: str,
    sub_type: str,
) -> Event:
    """Federal Registerイベントを構築。"""
    return Event(
        title=title[:250],
        start_at=start_at,
        end_at=None,
        category="shock",
        sector_tags=["semiconductor", "regulation", "bis"],
        risk_score=70,
        confidence=0.9,  # 構造化データなので高信頼
        source_name="federal_register",
        source_url=source_url,
        source_id=f"fr:{doc_number}:{sub_type}",
        evidence=evidence[:280],
        action="add",
    )


def _in_date_range(dt: datetime, start: str, end: str) -> bool:
    """イベント日が許容範囲内かチェック。空文字なら制限なし。"""
    if start:
        try:
            if dt < _parse_date(start):
                return False
        except ValueError:
            pass
    if end:
        try:
            if dt > _parse_date(end):
                return False
        except ValueError:
            pass
    return True


def _parse_date(date_str: str) -> datetime:
    """YYYY-MM-DD → datetime (UTC midnight)。"""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
