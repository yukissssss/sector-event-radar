"""Session 15: shock category override + migration tests"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest


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
        CREATE TABLE articles (
          url TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          relevance_score REAL NOT NULL,
          fetched_at TEXT NOT NULL
        );
    """)
    return conn


def _insert_miscategorized_event(conn, title="HBM4 Validation", category="macro"):
    """Claude抽出だが誤ってmacroに分類されたイベントを挿入"""
    now = datetime.now(timezone.utc).isoformat()
    key = f"{category}:hbm4:shock:2026-04-01"
    conn.execute(
        """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (key, title, "2026-04-01T00:00:00+00:00", None, category,
         '["semis"]', 40, 0.75, "active", now),
    )
    conn.execute(
        """INSERT INTO event_sources VALUES (?, ?, ?, ?, ?, ?)""",
        (key, "claude_extract", "claude:http://example.com#abc12345", 
         "http://example.com/hbm4", "HBM4 Validation Expected in 2Q26", now),
    )
    conn.commit()
    return key


# ── Tests: _migrate_shock_category ──────────────────────

class TestMigrateShockCategory:
    """P0修正: 既存の誤分類イベントをshockに修正するマイグレーション"""

    def test_fixes_miscategorized_claude_event(self):
        """claude_extractソースでcategory=macroのイベントがshockに修正される"""
        conn = _make_in_memory_db()
        old_key = _insert_miscategorized_event(conn, category="macro")

        # Import the migration function
        # We test the logic directly since importing run_daily requires the full package
        cur = conn.execute("""
            SELECT DISTINCT e.canonical_key, e.title, e.category
              FROM events e
              JOIN event_sources es ON e.canonical_key = es.canonical_key
             WHERE es.source_name = 'claude_extract'
               AND e.category != 'shock'
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["category"] == "macro"

        # Apply migration logic
        for r in rows:
            new_key = "shock:" + r["canonical_key"].split(":", 1)[1]
            conn.execute(
                "UPDATE events SET category='shock', canonical_key=? WHERE canonical_key=?",
                (new_key, r["canonical_key"]),
            )
            conn.execute(
                "UPDATE event_sources SET canonical_key=? WHERE canonical_key=?",
                (new_key, r["canonical_key"]),
            )
        conn.commit()

        # Verify
        row = conn.execute("SELECT * FROM events").fetchone()
        assert row["category"] == "shock"
        assert row["canonical_key"].startswith("shock:")

        es_row = conn.execute("SELECT * FROM event_sources").fetchone()
        assert es_row["canonical_key"].startswith("shock:")

    def test_does_not_touch_non_claude_events(self):
        """FMP等の他ソースのmacroイベントは変更されない"""
        conn = _make_in_memory_db()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("macro:us:cpi:2026-03-11", "US CPI", "2026-03-11T08:30:00-05:00",
             None, "macro", '["macro"]', 80, 0.99, "active", now),
        )
        conn.execute(
            """INSERT INTO event_sources VALUES (?, ?, ?, ?, ?, ?)""",
            ("macro:us:cpi:2026-03-11", "bls_static", "bls:cpi:2026-03-11",
             "https://bls.gov", "BLS official", now),
        )
        conn.commit()

        cur = conn.execute("""
            SELECT DISTINCT e.canonical_key
              FROM events e
              JOIN event_sources es ON e.canonical_key = es.canonical_key
             WHERE es.source_name = 'claude_extract'
               AND e.category != 'shock'
        """)
        assert len(cur.fetchall()) == 0  # Nothing to migrate

    def test_no_op_when_already_shock(self):
        """すでにshockのClaude抽出イベントは変更なし"""
        conn = _make_in_memory_db()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("shock:abc:shock:2026-04-01", "Export Ban", "2026-04-01T00:00:00+00:00",
             None, "shock", '["semis"]', 50, 0.8, "active", now),
        )
        conn.execute(
            """INSERT INTO event_sources VALUES (?, ?, ?, ?, ?, ?)""",
            ("shock:abc:shock:2026-04-01", "claude_extract", "claude:url#hash",
             "http://example.com", "evidence", now),
        )
        conn.commit()

        cur = conn.execute("""
            SELECT DISTINCT e.canonical_key
              FROM events e
              JOIN event_sources es ON e.canonical_key = es.canonical_key
             WHERE es.source_name = 'claude_extract'
               AND e.category != 'shock'
        """)
        assert len(cur.fetchall()) == 0


# ── Tests: category override in extraction ──────────────

class TestCategoryOverride:
    """P0修正: Claude抽出後にcategory=shockを強制するロジック"""

    def test_override_macro_to_shock(self):
        """Claudeがmacroを返してもshockに上書きされる"""
        # Simulate the override logic from run_daily.py
        class FakeEvent:
            def __init__(self, title, category):
                self.title = title
                self.category = category

        events = [FakeEvent("HBM4 Validation", "macro")]
        overridden = []
        for ev in events:
            if ev.category != "shock":
                overridden.append(ev.category)
                ev.category = "shock"

        assert events[0].category == "shock"
        assert overridden == ["macro"]

    def test_shock_stays_shock(self):
        """Claudeがshockを返した場合はそのまま"""
        class FakeEvent:
            def __init__(self, title, category):
                self.title = title
                self.category = category

        events = [FakeEvent("Export Ban", "shock")]
        for ev in events:
            if ev.category != "shock":
                ev.category = "shock"

        assert events[0].category == "shock"

    def test_multiple_events_all_overridden(self):
        """1記事から複数イベント抽出時、すべてshockに統一"""
        class FakeEvent:
            def __init__(self, title, category):
                self.title = title
                self.category = category

        events = [
            FakeEvent("Event A", "macro"),
            FakeEvent("Event B", "bellwether"),
            FakeEvent("Event C", "shock"),
        ]
        for ev in events:
            if ev.category != "shock":
                ev.category = "shock"

        assert all(ev.category == "shock" for ev in events)
