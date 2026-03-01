"""Session 15: shock category override + migration tests

run_daily.py の override_shock_category() / migrate_shock_category() を
直接テストする。実装と乖離しない統合寄りのテスト。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import List

import pytest

# ── run_daily.py の関数を直接import ──
from sector_event_radar.run_daily import override_shock_category, migrate_shock_category
from sector_event_radar.models import Event


# ── Helpers ──────────────────────────────────────────────

def _make_in_memory_db():
    """テスト用のin-memoryDB（schema付き）"""
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
        CREATE TABLE event_history (
          canonical_key TEXT NOT NULL,
          actual_value REAL,
          forecast_value REAL,
          surprise_direction TEXT,
          surprise_pct REAL
        );
    """)
    return conn


def _make_event(title: str = "Test Event", category: str = "macro", **kwargs) -> Event:
    """テスト用Eventファクトリ"""
    defaults = dict(
        canonical_key=f"{category}:test:sub:2026-04-01",
        title=title,
        start_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end_at=None,
        category=category,
        sector_tags=["semis"],
        risk_score=40,
        confidence=0.75,
        source_name="claude_extract",
        source_url="http://example.com/article",
        source_id="claude:http://example.com#abc12345",
        evidence="HBM4 Validation Expected in 2Q26",
        action="add",
    )
    defaults.update(kwargs)
    return Event(**defaults)


def _insert_claude_event(conn, title="HBM4 Validation", category="macro"):
    """Claude抽出だがcategoryが誤分類されたイベントをDBに挿入"""
    now = datetime.now(timezone.utc).isoformat()
    key = f"{category}:hbm4:shock:2026-04-01"
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, title, "2026-04-01T00:00:00+00:00", None, category,
         '["semis"]', 40, 0.75, "active", now),
    )
    conn.execute(
        "INSERT INTO event_sources VALUES (?, ?, ?, ?, ?, ?)",
        (key, "claude_extract", f"claude:http://example.com#{category[:4]}",
         "http://example.com/hbm4", "HBM4 Validation Expected in 2Q26", now),
    )
    conn.commit()
    return key


def _insert_official_event(conn, title="US CPI", category="macro", source_name="bls_static"):
    """BLS等の公式ソースイベントを挿入"""
    now = datetime.now(timezone.utc).isoformat()
    key = f"{category}:us:cpi:2026-03-11"
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, title, "2026-03-11T08:30:00-05:00", None, category,
         '["macro"]', 80, 0.99, "active", now),
    )
    conn.execute(
        "INSERT INTO event_sources VALUES (?, ?, ?, ?, ?, ?)",
        (key, source_name, f"{source_name}:cpi:2026-03-11",
         "https://bls.gov", "BLS official", now),
    )
    conn.commit()
    return key


# ── Tests: override_shock_category ──────────────────────

class TestOverrideShockCategory:
    """Claude抽出後にcategory=shockを強制する関数のテスト"""

    def test_overrides_macro_to_shock(self):
        events = [_make_event("HBM4 Validation", category="macro")]
        count = override_shock_category(events)
        assert events[0].category == "shock"
        assert count == 1

    def test_shock_stays_shock(self):
        events = [_make_event("Export Ban", category="shock")]
        count = override_shock_category(events)
        assert events[0].category == "shock"
        assert count == 0

    def test_multiple_events_all_overridden(self):
        events = [
            _make_event("Event A", category="macro"),
            _make_event("Event B", category="bellwether"),
            _make_event("Event C", category="shock"),
        ]
        count = override_shock_category(events)
        assert all(ev.category == "shock" for ev in events)
        assert count == 2  # A and B overridden, C untouched

    def test_empty_list(self):
        count = override_shock_category([])
        assert count == 0


# ── Tests: migrate_shock_category ───────────────────────

class TestMigrateShockCategory:
    """既存DBの誤分類イベントをshockに修正するマイグレーション"""

    def test_fixes_miscategorized_claude_event(self):
        """claude_extractソースでcategory=macroのイベントがshockに修正"""
        conn = _make_in_memory_db()
        key = _insert_claude_event(conn, category="macro")

        fixed = migrate_shock_category(conn)
        assert fixed == 1

        row = conn.execute(
            "SELECT category, canonical_key FROM events WHERE canonical_key = ?", (key,)
        ).fetchone()
        assert row["category"] == "shock"
        # canonical_keyは変更しない（PK衝突回避の安全設計）
        assert row["canonical_key"] == key

    def test_does_not_touch_official_macro(self):
        """BLS/BEA等のmacroイベントは変更されない"""
        conn = _make_in_memory_db()
        key = _insert_official_event(conn, source_name="bls_static")

        fixed = migrate_shock_category(conn)
        assert fixed == 0

        row = conn.execute("SELECT category FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "macro"

    def test_no_op_when_already_shock(self):
        """すでにshockのClaude抽出イベントは変更なし"""
        conn = _make_in_memory_db()
        _insert_claude_event(conn, category="shock")

        fixed = migrate_shock_category(conn)
        assert fixed == 0

    def test_canonical_key_unchanged(self):
        """canonical_keyが旧categoryプレフィックスのままでも機能する"""
        conn = _make_in_memory_db()
        key = _insert_claude_event(conn, category="bellwether")

        migrate_shock_category(conn)

        row = conn.execute("SELECT * FROM events WHERE canonical_key = ?", (key,)).fetchone()
        assert row["category"] == "shock"
        assert row["canonical_key"] == key  # キーは変更なし
        assert row["canonical_key"].startswith("bellwether:")  # 旧prefix残存OK

    def test_mixed_sources_only_claude_fixed(self):
        """Claude抽出のみ修正、公式ソースは温存"""
        conn = _make_in_memory_db()
        claude_key = _insert_claude_event(conn, title="HBM4", category="macro")
        official_key = _insert_official_event(conn, title="CPI", source_name="bls_static")

        fixed = migrate_shock_category(conn)
        assert fixed == 1

        claude_row = conn.execute(
            "SELECT category FROM events WHERE canonical_key = ?", (claude_key,)
        ).fetchone()
        assert claude_row["category"] == "shock"

        official_row = conn.execute(
            "SELECT category FROM events WHERE canonical_key = ?", (official_key,)
        ).fetchone()
        assert official_row["category"] == "macro"

    def test_idempotent(self):
        """2回実行しても結果が同じ（冪等）"""
        conn = _make_in_memory_db()
        _insert_claude_event(conn, category="macro")

        first = migrate_shock_category(conn)
        assert first == 1

        second = migrate_shock_category(conn)
        assert second == 0  # 既にshockなのでno-op
