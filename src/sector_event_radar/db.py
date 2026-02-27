from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from .models import Event


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
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

CREATE TABLE IF NOT EXISTS event_sources (
  canonical_key TEXT NOT NULL REFERENCES events(canonical_key),
  source_name TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_url TEXT,
  evidence TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  PRIMARY KEY (source_name, source_id)
);

CREATE TABLE IF NOT EXISTS event_history (
  canonical_key TEXT NOT NULL,
  actual_value REAL,
  forecast_value REAL,
  surprise_direction TEXT,
  surprise_pct REAL
);

CREATE TABLE IF NOT EXISTS data_mappings (
  pattern_key TEXT PRIMARY KEY,
  primary_tickers TEXT NOT NULL,
  secondary_tickers TEXT NOT NULL,
  context_fields TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  approved_at TEXT,
  change_log TEXT
);

CREATE TABLE IF NOT EXISTS articles (
  url TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  relevance_score REAL NOT NULL,
  fetched_at TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    # よく使う検索向けのインデックス（壊さない範囲で追加）
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_start_at ON events(start_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);")
    conn.commit()


def _iso(dt: datetime) -> str:
    # ISO8601 with timezone
    return dt.isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_event_row(conn: sqlite3.Connection, canonical_key: str):
    cur = conn.execute("SELECT * FROM events WHERE canonical_key = ?", (canonical_key,))
    return cur.fetchone()


def upsert_event(conn: sqlite3.Connection, event: Event) -> str:
    """Spec M6:
    return 'inserted'|'updated'|'merged'|'cancelled'|'ignored'
    """
    if not event.canonical_key:
        raise ValueError("event.canonical_key is required before upsert")

    if event.action == "ignore":
        return "ignored"

    key = event.canonical_key
    existing = get_event_row(conn, key)
    now_iso = _now_iso()

    # status決定
    new_status = "cancelled" if event.action == "cancel" else "active"

    # eventsテーブル upsert判定
    if existing is None:
        conn.execute(
            """
            INSERT INTO events (canonical_key, title, start_at, end_at, category, sector_tags, risk_score, confidence, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                event.title,
                _iso(event.start_at),
                _iso(event.end_at) if event.end_at else None,
                event.category,
                json.dumps(event.sector_tags, ensure_ascii=False),
                int(event.risk_score),
                float(event.confidence),
                new_status,
                now_iso,
            ),
        )
        _upsert_event_source(conn, event, now_iso)
        conn.commit()
        return "cancelled" if event.action == "cancel" else "inserted"

    # 既存あり
    # cancelはstatus update
    if event.action == "cancel":
        conn.execute(
            "UPDATE events SET status = ?, updated_at = ? WHERE canonical_key = ?",
            ("cancelled", now_iso, key),
        )
        _upsert_event_source(conn, event, now_iso)
        conn.commit()
        return "cancelled"

    # updateトリガー: start/end変更 or risk_score±20以上
    old_start = existing["start_at"]
    old_end = existing["end_at"]
    old_risk = int(existing["risk_score"])

    start_changed = old_start != _iso(event.start_at)
    end_changed = (old_end or None) != (_iso(event.end_at) if event.end_at else None)
    risk_big_change = abs(old_risk - int(event.risk_score)) >= 20

    if start_changed or end_changed or risk_big_change:
        conn.execute(
            """
            UPDATE events
               SET title = ?, start_at = ?, end_at = ?, category = ?, sector_tags = ?,
                   risk_score = ?, confidence = ?, status = ?, updated_at = ?
             WHERE canonical_key = ?
            """,
            (
                event.title,
                _iso(event.start_at),
                _iso(event.end_at) if event.end_at else None,
                event.category,
                json.dumps(event.sector_tags, ensure_ascii=False),
                int(event.risk_score),
                float(event.confidence),
                "active",
                now_iso,
                key,
            ),
        )
        _upsert_event_source(conn, event, now_iso)
        conn.commit()
        return "updated"

    # merge (source追加のみ)
    _upsert_event_source(conn, event, now_iso)
    conn.commit()
    return "merged"


def _upsert_event_source(conn: sqlite3.Connection, event: Event, now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO event_sources (canonical_key, source_name, source_id, source_url, evidence, seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_name, source_id)
        DO UPDATE SET canonical_key=excluded.canonical_key,
                      source_url=excluded.source_url,
                      evidence=excluded.evidence,
                      seen_at=excluded.seen_at
        """,
        (
            event.canonical_key,
            event.source_name,
            event.source_id,
            str(event.source_url) if event.source_url else None,
            event.evidence,
            now_iso,
        ),
    )
