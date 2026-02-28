"""run_daily.py — 日次バッチパイプライン

設計契約:
- 各collectorは独立try/exceptで囲む（部分失敗でも後続は継続）
- ICS生成は「最後に必ず実行」（collector全滅でもDBの既存データからICSを出す）
- upsertは冪等（リトライ安全）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from .canonical import make_canonical_key
from .config import AppConfig
from .db import connect, init_db, upsert_event
from .flows import generate_opex_events
from .ics import events_to_ics
from .models import Article, Event
from .prefilter import prefilter
from .validate import validate_event
from .collectors.rss import fetch_rss
from .collectors.scheduled import fetch_tradingeconomics_events, fetch_fmp_earnings_events
from .llm.claude_extract import ClaudeConfig, extract_events_from_article, ClaudeExtractError

logger = logging.getLogger(__name__)

# ── カテゴリ別ICSフィルタ ─────────────────────────────
CATEGORY_ICS_MAP = {
    "macro": "sector_events_macro.ics",
    "bellwether": "sector_events_bellwether.ics",
    "flows": "sector_events_flows.ics",
    "shock": "sector_events_shock.ics",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sector Event Radar daily batch")
    p.add_argument("--config", required=True, help="config.yaml path")
    p.add_argument("--db", required=True, help="SQLite path (events.db)")
    p.add_argument("--ics-dir", required=True, help="Output directory for .ics files")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip LLM calls and email sending")
    return p.parse_args()


def _list_events_from_db(conn, start: datetime, end: datetime) -> List[Event]:
    """DBからactive eventsを取得してEvent objectに変換"""
    cur = conn.execute(
        """
        SELECT canonical_key, title, start_at, end_at, category,
               sector_tags, risk_score, confidence, status
          FROM events
         WHERE status = 'active'
           AND start_at >= ?
           AND start_at <= ?
         ORDER BY start_at ASC
        """,
        (start.isoformat(), end.isoformat()),
    )
    rows = cur.fetchall()
    out: List[Event] = []
    for r in rows:
        out.append(Event(
            canonical_key=r["canonical_key"],
            title=r["title"],
            start_at=datetime.fromisoformat(r["start_at"]),
            end_at=datetime.fromisoformat(r["end_at"]) if r["end_at"] else None,
            category=r["category"],
            sector_tags=json.loads(r["sector_tags"]),
            risk_score=int(r["risk_score"]),
            confidence=float(r["confidence"]),
            source_name="db",
            source_url=None,
            source_id="db",
            evidence="from database",
            action="add",
        ))
    return out


def _collect_scheduled(cfg: AppConfig, now: datetime) -> Tuple[List[Event], List[str]]:
    """Scheduled sources: TE API + FMP API。各独立try/except。"""
    events: List[Event] = []
    errors: List[str] = []

    start_str = now.strftime("%Y-%m-%d")
    end_str = (now + timedelta(days=180)).strftime("%Y-%m-%d")

    # Trading Economics (macro)
    te_key = os.environ.get("TE_API_KEY", "")
    if te_key:
        try:
            te_events = fetch_tradingeconomics_events(
                te_key, start_str, end_str,
                country=cfg.te_country,
                importance=cfg.te_importance,
            )
            events.extend(te_events)
            logger.info("TE: collected %d events", len(te_events))
        except Exception as e:
            msg = f"TE collector failed: {e}"
            logger.warning(msg)
            errors.append(msg)
    else:
        logger.info("TE_API_KEY not set, skipping TradingEconomics")

    # FMP (bellwether earnings)
    fmp_key = os.environ.get("FMP_API_KEY", "")
    if fmp_key:
        try:
            fmp_events = fetch_fmp_earnings_events(
                fmp_key, start_str, end_str,
                tickers=cfg.bellwether_tickers,
            )
            events.extend(fmp_events)
            logger.info("FMP: collected %d events", len(fmp_events))
        except Exception as e:
            msg = f"FMP collector failed: {e}"
            logger.warning(msg)
            errors.append(msg)
    else:
        logger.info("FMP_API_KEY not set, skipping FMP earnings")

    return events, errors


def _collect_computed(now: datetime) -> Tuple[List[Event], List[str]]:
    """Computed sources: OPEX計算"""
    events: List[Event] = []
    errors: List[str] = []

    try:
        y, m = now.year, now.month
        opex = generate_opex_events(y, m, months=6)
        events.extend(opex)
        logger.info("OPEX: generated %d events", len(opex))
    except Exception as e:
        msg = f"OPEX generation failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    return events, errors


def _collect_unscheduled(
    cfg: AppConfig, now: datetime, dry_run: bool
) -> Tuple[List[Event], List[str]]:
    """Unscheduled: RSS → prefilter → Claude抽出。各段独立try/except。"""
    events: List[Event] = []
    errors: List[str] = []

    # 1) RSS取得
    articles: List[Article] = []
    for src in cfg.sources.rss:
        try:
            fetched = fetch_rss(src.url)
            articles.extend(fetched)
            logger.info("RSS %s: %d articles", src.name, len(fetched))
        except Exception as e:
            msg = f"RSS {src.name} failed: {e}"
            logger.warning(msg)
            errors.append(msg)

    if not articles:
        logger.info("No RSS articles fetched, skipping prefilter/extract")
        return events, errors

    # 2) Prefilter
    try:
        filtered = prefilter(
            articles,
            keywords=cfg.keywords,
            stage_a_threshold=cfg.prefilter.stage_a_threshold,
            stage_b_top_k=cfg.prefilter.stage_b_top_k,
        )
        logger.info("Prefilter: %d → %d articles", len(articles), len(filtered))
    except Exception as e:
        msg = f"Prefilter failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return events, errors

    # 3) Claude抽出
    if dry_run:
        logger.info("Dry-run: skipping Claude extraction for %d articles", len(filtered))
        return events, errors

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        msg = "ANTHROPIC_API_KEY not set, skipping Claude extraction"
        logger.warning(msg)
        errors.append(msg)
        return events, errors

    claude_cfg = ClaudeConfig(api_key=api_key)
    for article in filtered:
        try:
            extracted = extract_events_from_article(
                cfg=claude_cfg,
                article_title=article.title,
                article_published=article.published,
                article_url=article.url,
                article_content=article.body,
            )
            events.extend(extracted)
        except ClaudeExtractError as e:
            msg = f"Claude extract failed for '{article.title[:50]}': {e}"
            logger.warning(msg)
            errors.append(msg)
        except Exception as e:
            msg = f"Unexpected error extracting '{article.title[:50]}': {e}"
            logger.warning(msg)
            errors.append(msg)

    logger.info("Claude: extracted %d events from %d articles", len(events), len(filtered))
    return events, errors


def _upsert_pipeline(
    conn, events: List[Event], cfg: AppConfig, now: datetime
) -> dict:
    """canonical_key生成 → 検証 → upsert。結果のサマリを返す。"""
    stats = {"inserted": 0, "updated": 0, "merged": 0, "cancelled": 0, "ignored": 0, "rejected": 0}

    for ev in events:
        # canonical_key が未設定なら生成
        if not ev.canonical_key:
            ev.canonical_key = make_canonical_key(ev, cfg)

        # 検証
        ok, reason = validate_event(ev, now=now)
        if not ok:
            logger.debug("Rejected: %s (%s) reason=%s", ev.title, ev.canonical_key, reason)
            stats["rejected"] += 1
            continue

        # upsert
        result = upsert_event(conn, ev)
        stats[result] = stats.get(result, 0) + 1
        logger.debug("Upsert: %s %s %s", result, ev.canonical_key, ev.title)

    return stats


def _generate_ics_files(conn, ics_dir: str, now: datetime) -> None:
    """全体ICS + カテゴリ別ICSを生成。ここは絶対に例外で止めない。"""
    ics_path = Path(ics_dir)
    ics_path.mkdir(parents=True, exist_ok=True)

    start = now - timedelta(days=1)
    end = now + timedelta(days=180)
    all_events = _list_events_from_db(conn, start, end)

    # 全体ICS
    try:
        ics_all = events_to_ics(all_events, cal_name="Sector Event Radar")
        out_all = ics_path / "sector_events_all.ics"
        out_all.write_text(ics_all, encoding="utf-8")
        logger.info("ICS all: %s (%d events)", out_all, len(all_events))
    except Exception as e:
        logger.error("Failed to write all.ics: %s", e)

    # カテゴリ別ICS
    for category, filename in CATEGORY_ICS_MAP.items():
        try:
            cat_events = [e for e in all_events if e.category == category]
            ics_cat = events_to_ics(cat_events, cal_name=f"SER - {category}")
            out_cat = ics_path / filename
            out_cat.write_text(ics_cat, encoding="utf-8")
            logger.info("ICS %s: %s (%d events)", category, out_cat, len(cat_events))
        except Exception as e:
            logger.error("Failed to write %s: %s", filename, e)


def run_daily(config_path: str, db_path: str, ics_dir: str, dry_run: bool = False) -> dict:
    """メインエントリポイント。

    Returns:
        dict: 実行サマリ（collector結果、upsert統計、エラー一覧）
    """
    cfg = AppConfig.load(config_path)
    conn = connect(db_path)
    init_db(conn)

    now = datetime.now(timezone.utc)
    all_errors: List[str] = []
    all_events: List[Event] = []

    # ── Phase 1: 収集（各collector独立、部分失敗OK）──
    scheduled, errs = _collect_scheduled(cfg, now)
    all_events.extend(scheduled)
    all_errors.extend(errs)

    computed, errs = _collect_computed(now)
    all_events.extend(computed)
    all_errors.extend(errs)

    unscheduled, errs = _collect_unscheduled(cfg, now, dry_run)
    all_events.extend(unscheduled)
    all_errors.extend(errs)

    logger.info(
        "Collection complete: scheduled=%d, computed=%d, unscheduled=%d, errors=%d",
        len(scheduled), len(computed), len(unscheduled), len(all_errors),
    )

    # ── Phase 2: upsert pipeline ──
    stats = _upsert_pipeline(conn, all_events, cfg, now)
    logger.info("Upsert stats: %s", stats)

    # ── Phase 3: ICS生成（絶対に実行）──
    _generate_ics_files(conn, ics_dir, now)

    # ── サマリ ──
    summary = {
        "timestamp": now.isoformat(),
        "dry_run": dry_run,
        "collected": {
            "scheduled": len(scheduled),
            "computed": len(computed),
            "unscheduled": len(unscheduled),
        },
        "upsert": stats,
        "errors": all_errors,
    }

    # GitHub Actions向けにサマリをstdoutに出力
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    run_daily(args.config, args.db, args.ics_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
