"""Session 16: quarter/month/half-year range normalization tests

TestIsQuarterLikeRange (6本):
  1. test_quarter_range_detected — 91日=四半期
  2. test_month_range_detected — 31日=月
  3. test_short_range_not_detected — 1日は対象外
  4. test_non_first_day_not_detected — start_at.day!=1は対象外
  5. test_end_not_first_day_not_detected — end_at.day!=1は対象外（2月末）
  6. test_irregular_month_span_not_detected — 4ヶ月差は{1,3,6}外

TestNormalizeDateRange (5本):
  7. test_quarter_range_nullified — Q2 4/1→7/1 → end_at=None
  8. test_month_range_nullified — March 3/1→4/1 → end_at=None
  9. test_half_year_range_nullified — H1 1/1→7/1 → end_at=None
  10. test_exact_date_preserved — 1日イベント(end_at=start_at+1h)は温存
  11. test_no_end_at_noop — end_at=None はそのまま

TestMigrateQuarterRange (4本):
  12. test_fixes_existing_quarter_range — DB内レンジ→NULL
  13. test_does_not_touch_non_claude — 公式macroは温存
  14. test_noop_when_no_end_at — end_at=NULLなら何もしない
  15. test_idempotent — 2回実行で冪等性
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from sector_event_radar.run_daily import (
    normalize_date_range,
    migrate_quarter_range,
    _is_quarter_like_range,
)
from sector_event_radar.models import Event


# ── Helpers ──────────────────────────────────────────────

def _make_event(
    title: str = "Test Event",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> Event:
    if start_at is None:
        start_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    return Event(
        title=title,
        start_at=start_at,
        end_at=end_at,
        category="shock",
        sector_tags=["semis"],
        risk_score=50,
        confidence=0.50,
        source_name="claude_extract",
        source_url="https://example.com/article",
        source_id="claude:http://example.com#abc12345",
        evidence="expected in Q2 2026",
        action="add",
    )


def _make_db():
    """In-memory SQLite with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
          canonical_key TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          start_at TEXT NOT NULL,
          end_at TEXT,
          category TEXT NOT NULL,
          sector_tags TEXT NOT NULL,
          risk_score INTEGER NOT NULL,
          confidence REAL NOT NULL,
          status TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE event_sources (
          canonical_key TEXT NOT NULL,
          source_name TEXT NOT NULL,
          source_id TEXT NOT NULL,
          source_url TEXT,
          evidence TEXT NOT NULL,
          seen_at TEXT NOT NULL,
          PRIMARY KEY (source_name, source_id)
        );
        CREATE TABLE articles (
          url TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          relevance_score REAL NOT NULL,
          fetched_at TEXT NOT NULL
        );
    """)
    return conn


def _insert_event(conn, canonical_key, title, category, source_name, source_id,
                   start_at="2026-04-01T00:00:00+00:00", end_at=None):
    """eventsとevent_sourcesに直接INSERT。"""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, '[\"semis\"]', 50, 0.5, 'active', ?)",
        (canonical_key, title, start_at, end_at, category, now),
    )
    conn.execute(
        "INSERT INTO event_sources VALUES (?, ?, ?, 'https://example.com', 'test evidence', ?)",
        (canonical_key, source_name, source_id, now),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════
# TestIsQuarterLikeRange (4本)
# ══════════════════════════════════════════════════════════

class TestIsQuarterLikeRange:
    """四半期/月/半期レンジの判定ロジック"""

    def test_quarter_range_detected(self):
        """Q2: 4/1→7/1 (91日) は四半期レンジ"""
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is True

    def test_month_range_detected(self):
        """March: 3/1→4/1 (31日) は月レンジ"""
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is True

    def test_short_range_not_detected(self):
        """1日イベント（1時間）は対象外"""
        start = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is False

    def test_non_first_day_not_detected(self):
        """start_at.day=15 は月初でないので対象外"""
        start = datetime(2026, 4, 15, tzinfo=timezone.utc)
        end = datetime(2026, 7, 15, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is False

    def test_month_end_detected(self):
        """2/1→2/28（月末閉じ・月差0）は月レンジとして検出"""
        start = datetime(2026, 2, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 28, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is True

    def test_quarter_end_detected(self):
        """4/1→6/30（四半期末閉じ・月差2）は四半期レンジとして検出"""
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 30, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is True

    def test_irregular_month_span_not_detected(self):
        """2/1→6/1 (4ヶ月差)は{1,3,6}に含まれないので対象外"""
        start = datetime(2026, 2, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is False

    def test_mid_month_end_not_detected(self):
        """4/1→6/15（月中日）は月末でも月初でもないので対象外"""
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 15, tzinfo=timezone.utc)
        assert _is_quarter_like_range(start, end) is False


# ══════════════════════════════════════════════════════════
# TestNormalizeDateRange (5本)
# ══════════════════════════════════════════════════════════

class TestNormalizeDateRange:
    """Claude抽出後のレンジ正規化（防火扉）"""

    def test_quarter_range_nullified(self):
        """Q2 range (4/1→7/1) → end_at=None"""
        ev = _make_event(
            title="HBM4 Validation",
            start_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        count = normalize_date_range([ev])
        assert ev.end_at is None
        assert count == 1

    def test_month_range_nullified(self):
        """Month range (3/1→4/1) → end_at=None"""
        ev = _make_event(
            title="March Production",
            start_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        count = normalize_date_range([ev])
        assert ev.end_at is None
        assert count == 1

    def test_half_year_range_nullified(self):
        """Half-year range (1/1→7/1, 181日) → end_at=None"""
        ev = _make_event(
            title="H1 2026 Target",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        count = normalize_date_range([ev])
        assert ev.end_at is None
        assert count == 1

    def test_exact_date_preserved(self):
        """1時間イベント（end_at=start_at+1h）は温存"""
        start = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
        ev = _make_event(
            title="Exact Event",
            start_at=start,
            end_at=start + timedelta(hours=1),
        )
        count = normalize_date_range([ev])
        assert ev.end_at is not None
        assert count == 0

    def test_no_end_at_noop(self):
        """end_at=None はそのまま"""
        ev = _make_event(title="Point Event", end_at=None)
        count = normalize_date_range([ev])
        assert ev.end_at is None
        assert count == 0


# ══════════════════════════════════════════════════════════
# TestMigrateQuarterRange (4本)
# ══════════════════════════════════════════════════════════

class TestMigrateQuarterRange:
    """既存DBの四半期レンジをNULLに修正するマイグレーション"""

    def test_fixes_existing_quarter_range(self):
        """DB内のQ2レンジ → end_at=NULL"""
        conn = _make_db()
        key = "shock:hbm4:shock:2026-04-01"
        _insert_event(conn, key, "HBM4 Validation", "shock",
                       "claude_extract", "claude:http://example.com#abc",
                       start_at="2026-04-01T00:00:00+00:00",
                       end_at="2026-07-01T00:00:00+00:00")

        fixed = migrate_quarter_range(conn)
        assert fixed == 1

        row = conn.execute("SELECT end_at FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["end_at"] is None

    def test_does_not_touch_non_claude(self):
        """公式macroイベントのend_atは温存"""
        conn = _make_db()
        key = "macro:us:fomc:2026-03-18"
        # FOMCは2日間イベント（start=3/17, end=3/18）
        _insert_event(conn, key, "FOMC Meeting", "macro",
                       "fomc_static", "fomc:2026-03-18",
                       start_at="2026-03-17T00:00:00+00:00",
                       end_at="2026-03-18T14:00:00-05:00")

        fixed = migrate_quarter_range(conn)
        assert fixed == 0

    def test_noop_when_no_end_at(self):
        """end_at=NULLのClaude抽出イベントは何もしない"""
        conn = _make_db()
        key = "shock:export:shock:2026-05-01"
        _insert_event(conn, key, "Export Ban", "shock",
                       "claude_extract", "claude:http://example.com#def",
                       start_at="2026-05-01T00:00:00+00:00",
                       end_at=None)

        fixed = migrate_quarter_range(conn)
        assert fixed == 0

    def test_idempotent(self):
        """2回実行で冪等性"""
        conn = _make_db()
        key = "shock:hbm4:shock:2026-04-01"
        _insert_event(conn, key, "HBM4 Validation", "shock",
                       "claude_extract", "claude:http://example.com#idem",
                       start_at="2026-04-01T00:00:00+00:00",
                       end_at="2026-07-01T00:00:00+00:00")

        first = migrate_quarter_range(conn)
        assert first == 1

        second = migrate_quarter_range(conn)
        assert second == 0
