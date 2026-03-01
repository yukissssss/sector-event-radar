"""Session 15: shock category override + migration tests (10本)

TestOverrideShockCategory (4本):
  1. test_overrides_macro_to_shock — macro→shock上書き、戻り値=1
  2. test_shock_stays_shock — shockはそのまま、戻り値=0
  3. test_multiple_events_all_overridden — 複数イベント全てshockに統一
  4. test_empty_list — 空リストでも安全

TestMigrateShockCategory (6本):
  5. test_fixes_miscategorized_claude_event — macro→shock修正、canonical_key不変
  6. test_does_not_touch_official_macro — BLS等は変更なし
  7. test_no_op_when_already_shock — 既にshockなら何もしない
  8. test_canonical_key_unchanged — 旧prefixが残存してもOK
  9. test_mixed_sources_only_claude_fixed — Claude抽出のみ修正、公式温存
  10. test_idempotent — 2回実行で冪等性確認
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from sector_event_radar.run_daily import override_shock_category, migrate_shock_category
from sector_event_radar.models import Event


# ── Helpers ──────────────────────────────────────────────

def _make_event(
    title: str = "Test Event",
    category: str = "shock",
    source_name: str = "claude_extract",
    source_id: str = "claude:http://example.com#abc12345",
) -> Event:
    return Event(
        title=title,
        start_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        category=category,
        sector_tags=["semis"],
        risk_score=50,
        confidence=0.80,
        source_name=source_name,
        source_url="https://example.com/article",
        source_id=source_id,
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


def _insert_event(conn, canonical_key, title, category, source_name, source_id):
    """eventsとevent_sourcesに直接INSERT。"""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, NULL, ?, '[\"semis\"]', 50, 0.8, 'active', ?)",
        (canonical_key, title, "2026-04-01T00:00:00+00:00", category, now),
    )
    conn.execute(
        "INSERT INTO event_sources VALUES (?, ?, ?, 'https://example.com', 'test evidence', ?)",
        (canonical_key, source_name, source_id, now),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════
# TestOverrideShockCategory (4本)
# ══════════════════════════════════════════════════════════

class TestOverrideShockCategory:
    """Claude抽出直後にcategory=shockを強制する公開関数のテスト"""

    def test_overrides_macro_to_shock(self):
        """macro→shock上書き、戻り値=1"""
        events = [_make_event(title="HBM4 Validation", category="macro")]
        count = override_shock_category(events)
        assert events[0].category == "shock"
        assert count == 1

    def test_shock_stays_shock(self):
        """shockはそのまま、戻り値=0"""
        events = [_make_event(title="Export Ban", category="shock")]
        count = override_shock_category(events)
        assert events[0].category == "shock"
        assert count == 0

    def test_multiple_events_all_overridden(self):
        """複数イベント全てshockに統一"""
        events = [
            _make_event(title="Event A", category="macro", source_id="claude:a#1"),
            _make_event(title="Event B", category="bellwether", source_id="claude:b#2"),
            _make_event(title="Event C", category="shock", source_id="claude:c#3"),
        ]
        count = override_shock_category(events)
        assert all(ev.category == "shock" for ev in events)
        assert count == 2  # macro + bellwether の2件が上書き

    def test_empty_list(self):
        """空リストでも安全"""
        count = override_shock_category([])
        assert count == 0


# ══════════════════════════════════════════════════════════
# TestMigrateShockCategory (6本)
# ══════════════════════════════════════════════════════════

class TestMigrateShockCategory:
    """既存DBの誤分類イベントをshockに修正するマイグレーション"""

    def test_fixes_miscategorized_claude_event(self):
        """macro→shock修正、canonical_key不変"""
        conn = _make_db()
        key = "macro:hbm4:shock:2026-04-01"
        _insert_event(conn, key, "HBM4 Validation", "macro",
                       "claude_extract", "claude:http://example.com#abc")

        fixed = migrate_shock_category(conn)
        assert fixed == 1

        row = conn.execute("SELECT * FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "shock"
        assert row["canonical_key"] == key  # canonical_key不変

    def test_does_not_touch_official_macro(self):
        """BLS等の公式macroイベントは変更なし"""
        conn = _make_db()
        key = "macro:us:cpi:2026-03-11"
        _insert_event(conn, key, "US CPI", "macro",
                       "bls_static", "bls:cpi:2026-03-11")

        fixed = migrate_shock_category(conn)
        assert fixed == 0

        row = conn.execute("SELECT * FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "macro"  # 変更なし

    def test_no_op_when_already_shock(self):
        """既にshockなら何もしない"""
        conn = _make_db()
        key = "shock:export:shock:2026-04-01"
        _insert_event(conn, key, "Export Ban", "shock",
                       "claude_extract", "claude:http://example.com#def")

        fixed = migrate_shock_category(conn)
        assert fixed == 0

    def test_canonical_key_unchanged(self):
        """旧categoryプレフィックスが残存してもcanonical_keyは書き換えない"""
        conn = _make_db()
        key = "macro:nvidia:shock:2026-05-01"
        _insert_event(conn, key, "NVIDIA Guidance Cut", "macro",
                       "claude_extract", "claude:http://example.com#ghi")

        migrate_shock_category(conn)

        row = conn.execute("SELECT * FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "shock"
        assert row["canonical_key"] == key  # "macro:" prefix残存でOK

    def test_mixed_sources_only_claude_fixed(self):
        """Claude抽出のみ修正、公式macroは温存"""
        conn = _make_db()
        claude_key = "macro:hbm4:shock:2026-04-01"
        _insert_event(conn, claude_key, "HBM4 Validation", "macro",
                       "claude_extract", "claude:http://example.com#mix1")
        bls_key = "macro:us:nfp:2026-04-03"
        _insert_event(conn, bls_key, "US NFP", "macro",
                       "bls_static", "bls:nfp:2026-04-03")

        fixed = migrate_shock_category(conn)
        assert fixed == 1  # Claude抽出の1件のみ

        claude_row = conn.execute(
            "SELECT category FROM events WHERE canonical_key = ?", (claude_key,)
        ).fetchone()
        assert claude_row["category"] == "shock"

        bls_row = conn.execute(
            "SELECT category FROM events WHERE canonical_key = ?", (bls_key,)
        ).fetchone()
        assert bls_row["category"] == "macro"  # 温存

    def test_idempotent(self):
        """2回実行で冪等性確認"""
        conn = _make_db()
        key = "macro:hbm4:shock:2026-04-01"
        _insert_event(conn, key, "HBM4 Validation", "macro",
                       "claude_extract", "claude:http://example.com#idem")

        first = migrate_shock_category(conn)
        assert first == 1

        second = migrate_shock_category(conn)
        assert second == 0  # 2回目はno-op

        row = conn.execute("SELECT category FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "shock"
