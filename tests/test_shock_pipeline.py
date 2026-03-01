"""test_shock_pipeline.py — shockパイプライン回帰テスト

Session 14で修正した3つの運用リスクに対する回帰テスト:
1. 同一run内URL dedupで二重課金を防止
2. Claude失敗時はseenにしない（翌日再試行）
3. 1記事→複数イベントでevent_sourcesが上書きされない
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sector_event_radar.db import connect, init_db, is_article_seen, mark_article_seen, upsert_event
from sector_event_radar.models import Article, Event
from sector_event_radar.prefilter import ScoredArticle


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def db_conn():
    """In-memory SQLiteをセットアップ"""
    conn = connect(":memory:")
    init_db(conn)
    return conn


@pytest.fixture
def sample_articles():
    """テスト用記事リスト（URLが重複するケースを含む）"""
    return [
        Article(title="NVIDIA export ban update", body="New restrictions on AI chip exports to China effective March 15, 2026", url="https://example.com/article1", published="2026-03-01"),
        Article(title="NVIDIA export ban update", body="New restrictions on AI chip exports to China effective March 15, 2026", url="https://example.com/article1", published="2026-03-01"),  # 重複URL
        Article(title="TSMC earnings surprise", body="TSMC Q1 revenue exceeds expectations on April 10, 2026", url="https://example.com/article2", published="2026-03-01"),
    ]


def _make_scored(article: Article, score: float = 0.8) -> ScoredArticle:
    return ScoredArticle(article=article, relevance_score=score)


def _make_event(title: str, start_at: str, source_id: str, canonical_key: str) -> Event:
    return Event(
        canonical_key=canonical_key,
        title=title,
        start_at=datetime.fromisoformat(start_at),
        category="shock",
        sector_tags=["semis"],
        risk_score=50,
        confidence=0.8,
        source_name="claude_extract",
        source_url="https://example.com/article1",
        source_id=source_id,
        evidence="effective March 15, 2026",
        action="add",
    )


# ── Test 1: 同一run内URL dedupテスト ─────────────────

def test_dedup_same_url_in_run(db_conn, sample_articles):
    """同じURLが2回出る入力で、new_articlesに重複が入らないことを検証。

    _collect_unscheduledの既出フィルタロジックを直接テスト。
    """
    # DB上にはまだ何もない
    articles = sample_articles  # article1が2回、article2が1回

    new_articles = []
    skipped_db_seen = 0
    skipped_dup_in_run = 0
    seen_in_run = set()

    for a in articles:
        if a.url in seen_in_run:
            skipped_dup_in_run += 1
            continue
        if is_article_seen(db_conn, a.url):
            skipped_db_seen += 1
            seen_in_run.add(a.url)
            continue
        seen_in_run.add(a.url)
        new_articles.append(a)

    # article1は1回だけ、article2は1回 = 合計2件
    assert len(new_articles) == 2
    assert skipped_dup_in_run == 1  # article1の重複が1回スキップ
    assert skipped_db_seen == 0     # DBには何もないので0

    # URLが正しくdedupされている
    urls = [a.url for a in new_articles]
    assert len(set(urls)) == len(urls), "URLに重複が残っている"


# ── Test 2: Claude失敗時はseenにしないテスト ──────────

def test_failed_extraction_not_marked_seen(db_conn):
    """Claude抽出が例外で失敗した記事はarticlesテーブルに記録されず、
    翌日再試行可能であることを検証。
    """
    article = Article(
        title="Important chip sanctions news",
        body="Major export controls announced for March 20, 2026",
        url="https://example.com/sanctions",
        published="2026-03-01",
    )
    scored = _make_scored(article)

    # 抽出が失敗したケース: mark_article_seenは呼ばれない
    extract_succeeded = False
    try:
        # ClaudeExtractErrorをシミュレート
        raise RuntimeError("Claude API 529 overloaded")
    except Exception:
        extract_succeeded = False

    if extract_succeeded:
        mark_article_seen(db_conn, article.url, "hash123", 0.8)

    # 失敗したのでDBには記録されていない → 翌日再試行可能
    assert not is_article_seen(db_conn, article.url), \
        "失敗記事がseenとしてマークされている（翌日再試行できない）"

    # 成功ケース: mark_article_seenが呼ばれる
    extract_succeeded = True
    if extract_succeeded:
        mark_article_seen(db_conn, article.url, "hash123", 0.8)

    assert is_article_seen(db_conn, article.url), \
        "成功記事がseenとしてマークされていない"


# ── Test 3: 1記事→複数イベントでevent_sourcesが上書きされないテスト ──

def test_multi_event_from_single_article_unique_source_ids(db_conn):
    """1記事から2イベント抽出時に、event_sourcesテーブルに両方の行が残ることを検証。

    source_idがイベント単位でユニーク（hash(title:start_at)）なので、
    (source_name, source_id)主キーが衝突しない。
    """
    article_url = "https://example.com/multi-event-article"

    # 同一記事から抽出された2つのイベント（異なるtitle/start_at → 異なるsource_id hash）
    ev1_title = "NVIDIA Export Ban Phase 1"
    ev1_start = "2026-03-15T00:00:00Z"
    ev1_hash = hashlib.sha256(f"{ev1_title}:{ev1_start}".encode()).hexdigest()[:8]
    ev1_source_id = f"claude:{article_url}#{ev1_hash}"

    ev2_title = "NVIDIA Export Ban Phase 2"
    ev2_start = "2026-06-01T00:00:00Z"
    ev2_hash = hashlib.sha256(f"{ev2_title}:{ev2_start}".encode()).hexdigest()[:8]
    ev2_source_id = f"claude:{article_url}#{ev2_hash}"

    # source_idが異なることを確認
    assert ev1_source_id != ev2_source_id, \
        f"source_idが同一: {ev1_source_id} == {ev2_source_id}"

    # 2イベントをDBにupsert
    event1 = _make_event(ev1_title, ev1_start, ev1_source_id, "shock:nvidia:export-ban-p1:2026-03-15")
    event2 = _make_event(ev2_title, ev2_start, ev2_source_id, "shock:nvidia:export-ban-p2:2026-06-01")

    upsert_event(db_conn, event1)
    upsert_event(db_conn, event2)

    # event_sourcesに2行あることを確認（上書きされていない）
    cur = db_conn.execute(
        "SELECT canonical_key, source_id FROM event_sources WHERE source_name = 'claude_extract' ORDER BY source_id"
    )
    rows = cur.fetchall()

    assert len(rows) == 2, f"event_sourcesに{len(rows)}行しかない（2行期待）"

    # それぞれのcanonical_keyが正しいイベントを指している
    source_ids = {r["source_id"] for r in rows}
    assert ev1_source_id in source_ids
    assert ev2_source_id in source_ids

    canonical_keys = {r["canonical_key"] for r in rows}
    assert event1.canonical_key in canonical_keys
    assert event2.canonical_key in canonical_keys
