"""run_daily.py — 日次バッチパイプライン

設計契約:
- 各collectorは独立try/exceptで囲む（部分失敗でも後続は継続）
- ICS生成は「最後に必ず実行」（collector全滅でもDBの既存データからICSを出す）
- upsertは冪等（リトライ安全）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from .canonical import make_canonical_key
from .config import AppConfig
from .db import connect, init_db, upsert_event, is_article_seen, mark_article_seen
from .flows import generate_opex_events
from .ics import events_to_ics
from .models import Article, Event
from .prefilter import prefilter
from .validate import validate_event
from .collectors.rss import fetch_rss
from .collectors.scheduled import fetch_tradingeconomics_events, fetch_fmp_earnings_events
from .collectors.official_calendars import fetch_official_macro_events
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


def _content_hash(title: str, body: str) -> str:
    """記事のcontent hashを生成。articlesテーブルに記録用。
    現在の既出判定はURL単位（コスト優先）。将来、内容変更で再処理したい場合は
    is_article_seenでcontent_hashも比較する方式に切替え可能。"""
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:16]


def _list_events_from_db(conn, start: datetime, end: datetime) -> List[Event]:
    """DBからactive eventsを取得してEvent objectに変換。
    event_sourcesから最新のsource_url/evidenceもJOINで取得。"""
    cur = conn.execute(
        """
        SELECT e.canonical_key, e.title, e.start_at, e.end_at, e.category,
               e.sector_tags, e.risk_score, e.confidence, e.status,
               es.source_url, es.evidence
          FROM events e
          LEFT JOIN event_sources es
            ON e.canonical_key = es.canonical_key
           AND es.seen_at = (
               SELECT MAX(es2.seen_at) FROM event_sources es2
                WHERE es2.canonical_key = e.canonical_key
           )
         WHERE e.status = 'active'
           AND e.start_at >= ?
           AND e.start_at <= ?
         ORDER BY e.start_at ASC
        """,
        (start.isoformat(), end.isoformat()),
    )
    rows = cur.fetchall()
    out: List[Event] = []
    for r in rows:
        source_url = r["source_url"] if r["source_url"] else None
        evidence = r["evidence"] if r["evidence"] else "from database"
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
            source_url=source_url,
            source_id="db",
            evidence=evidence,
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

    # Official government calendars (BLS/BEA/FOMC — free, authoritative)
    start_dt = now
    end_dt = now + timedelta(days=180)
    try:
        official_events, official_errs = fetch_official_macro_events(cfg, start_dt, end_dt)
        events.extend(official_events)
        errors.extend(official_errs)
        logger.info("Official macro: collected %d events", len(official_events))
    except Exception as e:
        msg = f"Official macro collector failed: {e}"
        logger.warning(msg)
        errors.append(msg)

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
    cfg: AppConfig, conn, now: datetime, dry_run: bool
) -> Tuple[List[Event], List[str]]:
    """Unscheduled: RSS → 既出フィルタ → prefilter → Claude抽出。

    各段独立try/except。観測ログを厚めに出力。
    """
    events: List[Event] = []
    errors: List[str] = []

    # 1) RSS取得（disabled対応）
    articles: List[Article] = []
    for src in cfg.sources.rss:
        if src.disabled:
            logger.info("RSS %s: SKIPPED (disabled)", src.name)
            continue
        try:
            fetched = fetch_rss(src.url)
            articles.extend(fetched)
            logger.info("RSS %s: %d articles fetched", src.name, len(fetched))
        except Exception as e:
            msg = f"RSS {src.name} failed: {e}"
            logger.warning(msg)
            errors.append(msg)

    if not articles:
        logger.info("No RSS articles fetched, skipping prefilter/extract")
        return events, errors

    # 2) 既出記事フィルタ + 同一run内URL dedup
    #    - DBチェック: 過去runで処理済みの記事をスキップ
    #    - in-memory dedup: 複数RSSソースに同じURLが混ざった場合の二重課金を防止
    new_articles: List[Article] = []
    skipped_db_seen = 0
    skipped_dup_in_run = 0
    seen_in_run: set = set()
    for a in articles:
        if a.url in seen_in_run:
            skipped_dup_in_run += 1
            logger.debug("Duplicate URL in run skipped: '%s'", a.title[:80])
            continue
        if is_article_seen(conn, a.url):
            skipped_db_seen += 1
            seen_in_run.add(a.url)
            logger.debug("Seen article skipped: '%s'", a.title[:80])
            continue
        seen_in_run.add(a.url)
        new_articles.append(a)

    logger.info(
        "Seen filter: %d/%d articles are new (skipped: %d already-processed, %d duplicate-in-run)",
        len(new_articles), len(articles), skipped_db_seen, skipped_dup_in_run,
    )

    if not new_articles:
        logger.info("All articles already processed, skipping prefilter/extract")
        return events, errors

    # 3) Prefilter
    try:
        filtered = prefilter(
            new_articles,
            keywords=cfg.keywords,
            stage_a_threshold=cfg.prefilter.stage_a_threshold,
            stage_b_top_k=cfg.prefilter.stage_b_top_k,
        )
        logger.info("Prefilter: %d → %d articles", len(new_articles), len(filtered))
    except Exception as e:
        msg = f"Prefilter failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return events, errors

    if not filtered:
        logger.info("Prefilter: 0 articles passed, no Claude extraction needed")
        return events, errors

    # 4) Claude抽出
    if dry_run:
        logger.info("Dry-run: skipping Claude extraction for %d articles", len(filtered))
        return events, errors

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        msg = "ANTHROPIC_API_KEY not set, skipping Claude extraction"
        logger.warning(msg)
        errors.append(msg)
        return events, errors

    max_articles = cfg.llm.max_articles_per_run
    claude_cfg = ClaudeConfig(api_key=api_key, model=cfg.llm.model)

    if len(filtered) > max_articles:
        logger.warning(
            "LLM guard: %d articles exceed limit (%d), processing top %d only",
            len(filtered), max_articles, max_articles,
        )
        filtered = filtered[:max_articles]

    llm_calls = 0
    llm_events_total = 0
    for article in filtered:
        extract_succeeded = False
        try:
            extracted = extract_events_from_article(
                cfg=claude_cfg,
                article_title=article.article.title,
                article_published=article.article.published,
                article_url=article.article.url,
                article_content=article.article.body,
            )
            llm_calls += 1

            # RSS→Claude抽出パイプラインは設計上すべてshockカテゴリ
            override_shock_category(extracted)

            llm_events_total += len(extracted)
            events.extend(extracted)
            extract_succeeded = True

            logger.info(
                "Claude extract: %d events from '%s'",
                len(extracted), article.article.title[:60],
            )
        except ClaudeExtractError as e:
            msg = f"Claude extract failed for '{article.article.title[:50]}': {e}"
            logger.warning(msg)
            errors.append(msg)
        except Exception as e:
            msg = f"Unexpected error extracting '{article.article.title[:50]}': {e}"
            logger.warning(msg)
            errors.append(msg)

        # Claude APIが正常応答した場合のみ既出マーク。
        # API例外（429/529リトライ尽き、timeout等）は翌日自動再試行される。
        if extract_succeeded:
            try:
                mark_article_seen(
                    conn,
                    url=article.article.url,
                    content_hash=_content_hash(article.article.title, article.article.body),
                    relevance_score=article.relevance_score,
                )
            except Exception as e:
                logger.warning("Failed to mark article as seen: %s", e)

    logger.info(
        "Claude summary: %d API calls, %d events extracted from %d articles",
        llm_calls, llm_events_total, len(filtered),
    )
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
            logger.warning(
                "Rejected: title='%s' key=%s start_at=%s category=%s reason=%s",
                ev.title, ev.canonical_key, ev.start_at.isoformat() if ev.start_at else "None",
                ev.category, reason,
            )
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


def override_shock_category(events: List[Event]) -> int:
    """Claude抽出イベントのcategoryをshockに強制する。

    RSS→Claude抽出パイプラインは設計上すべてshockカテゴリ。
    macro/bellwether/flowsは専用collectorが担当するため、
    Claudeの分類に依存せずコード側で強制する。

    Returns:
        int: 上書きした件数
    """
    overridden = 0
    for ev in events:
        if ev.category != "shock":
            logger.info(
                "Category override: '%s' %s → shock",
                ev.title[:50], ev.category,
            )
            ev.category = "shock"
            overridden += 1
    return overridden


def migrate_shock_category(conn) -> int:
    """既存のClaude抽出イベントでcategory!=shockのものをshockに修正。

    Session 14以前、Claudeがcategoryを自由選択していたため
    macro等に誤分類されたshockイベントが存在しうる。

    安全設計:
    - categoryカラムのみ更新。canonical_keyは変更しない（PK衝突・外部キー破損を回避）
    - canonical_keyの先頭が旧categoryのままになるが、ICSフィルタは events.category で
      判定するため機能上は問題ない
    - 対象イベントがなければno-op（毎回走っても安全）
    """
    cur = conn.execute("""
        SELECT DISTINCT e.canonical_key, e.title, e.category
          FROM events e
          JOIN event_sources es ON e.canonical_key = es.canonical_key
         WHERE es.source_name = 'claude_extract'
           AND e.category != 'shock'
    """)
    rows = cur.fetchall()
    if not rows:
        return 0

    for r in rows:
        logger.info(
            "Migration: '%s' category %s → shock (key=%s unchanged)",
            r["title"], r["category"], r["canonical_key"],
        )
        conn.execute(
            "UPDATE events SET category = 'shock' WHERE canonical_key = ?",
            (r["canonical_key"],),
        )
    conn.commit()
    logger.info("Migration: fixed %d miscategorized shock events", len(rows))
    return len(rows)


def run_daily(config_path: str, db_path: str, ics_dir: str, dry_run: bool = False) -> dict:
    """メインエントリポイント。

    Returns:
        dict: 実行サマリ（collector結果、upsert統計、エラー一覧）
    """
    cfg = AppConfig.load(config_path)
    conn = connect(db_path)
    init_db(conn)

    # 誤分類マイグレーション（Claude抽出イベントをshockに統一）
    # 設計契約: 失敗してもICS生成まで必ず到達する
    try:
        migrate_shock_category(conn)
    except Exception as e:
        logger.warning("Migration failed (non-fatal, continuing): %s", e)

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

    unscheduled, errs = _collect_unscheduled(cfg, conn, now, dry_run)
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
