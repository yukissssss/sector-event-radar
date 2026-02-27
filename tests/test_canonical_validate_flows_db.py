from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sector_event_radar.canonical import make_canonical_key
from sector_event_radar.config import AppConfig
from sector_event_radar.db import connect, init_db, upsert_event
from sector_event_radar.flows import generate_opex_events
from sector_event_radar.models import Event
from sector_event_radar.validate import validate_event


def test_canonical_macro_fomc(tmp_path: Path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        """
keywords: {}
prefilter: {stage_a_threshold: 6.0, stage_b_top_k: 30}
macro_title_map:
  '(?i)\\bFOMC\\b': { entity: "us", sub_type: "fomc" }
sources: {rss: []}
""",
        encoding="utf-8",
    )
    cfg = AppConfig.load(cfg_path)

    ev = Event(
        title="FOMC Statement Release",
        start_at=datetime(2026, 3, 18, 18, 0, tzinfo=timezone.utc),
        end_at=None,
        category="macro",
        sector_tags=[],
        risk_score=50,
        confidence=1.0,
        source_name="test",
        source_url=None,
        source_id="1",
        evidence="FOMC statement will be released on March 18, 2026.",
        action="add",
    )

    key = make_canonical_key(ev, cfg)
    assert key == "macro:us:fomc:2026-03-18"


def test_validate_timezone_required():
    ev = Event(
        title="CPI",
        start_at=datetime(2026, 3, 12, 8, 30),  # naive
        end_at=None,
        category="macro",
        sector_tags=[],
        risk_score=50,
        confidence=1.0,
        source_name="x",
        source_url=None,
        source_id="1",
        evidence="CPI will be released on March 12, 2026 at 8:30am ET.",
        action="add",
    )
    ok, reason = validate_event(ev, now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert not ok
    assert "timezone" in reason


def test_opex_good_friday_adjustment():
    # 2025-04-18 is Good Friday (3rd Friday of April 2025)
    # With exchange_calendars: should adjust to 2025-04-17 (Thursday)
    # Without exchange_calendars: returns 2025-04-18 as-is (no holiday adjustment)
    evs = generate_opex_events(2025, 4, months=1)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.start_at.tzinfo is not None

    try:
        import exchange_calendars
        # exchange_calendarsがある → Good Friday調整が効く
        assert ev.start_at.date().isoformat() == "2025-04-17", \
            f"Expected 2025-04-17 (adjusted), got {ev.start_at.date()}"
    except ImportError:
        # exchange_calendarsなし → 第3金曜そのまま（調整なし）
        assert ev.start_at.date().isoformat() == "2025-04-18", \
            f"Expected 2025-04-18 (no adjustment), got {ev.start_at.date()}"


def test_canonical_shock_disambiguate_by_source(tmp_path: Path):
    """同日同トピックでもソースが違えば別canonical_key、同ソースなら同一key"""
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "keywords: {}\nprefilter: {stage_a_threshold: 6.0, stage_b_top_k: 30}\n"
        "macro_title_map: {}\nsources: {rss: []}\n",
        encoding="utf-8",
    )
    cfg = AppConfig.load(cfg_path)

    base = dict(
        start_at=datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
        end_at=None,
        category="shock",
        sector_tags=[],
        risk_score=70,
        confidence=0.8,
        source_name="reuters",
        evidence="New export controls announced March 5, 2026.",
        action="add",
    )

    # 同ソース・タイトル表記揺れ → 同じhash（source_urlで決まるから）
    ev_a = Event(title="US Export Controls on AI Chips", source_url="https://reuters.com/article/123", source_id="r123", **base)
    ev_b = Event(title="New Export Restrictions for AI Semiconductors", source_url="https://reuters.com/article/123", source_id="r123", **base)
    key_a = make_canonical_key(ev_a, cfg)
    key_b = make_canonical_key(ev_b, cfg)
    # slugは違うがhash部分は同じ（同じsource_url）
    assert key_a.split(":")[-1] == key_b.split(":")[-1]  # 同じ日付
    # hashが同一source_urlから生成されることを確認
    assert key_a.endswith(key_b.split(":")[-1])

    # 別ソース → 別hash → 別canonical_key（衝突回避）
    ev_c = Event(title="US Export Controls on AI Chips", source_url="https://nytimes.com/article/456", source_id="n456", **base)
    key_c = make_canonical_key(ev_c, cfg)
    assert key_a != key_c  # 別ソースなら別key


def test_db_upsert_insert_update_merge(tmp_path: Path):
    db_path = tmp_path / "events.db"
    conn = connect(str(db_path))
    init_db(conn)

    tz = ZoneInfo("America/New_York")
    ev = Event(
        canonical_key="macro:us:cpi:2026-03-12",
        title="US CPI",
        start_at=datetime(2026, 3, 12, 8, 30, tzinfo=tz),
        end_at=None,
        category="macro",
        sector_tags=[],
        risk_score=60,
        confidence=0.9,
        source_name="reuters",
        source_url=None,
        source_id="a1",
        evidence="US CPI release is scheduled for March 12, 2026.",
        action="add",
    )

    r1 = upsert_event(conn, ev)
    assert r1 == "inserted"

    # same key, no change → merged
    ev2 = ev.model_copy(update={"source_name": "bloomberg", "source_id": "b1"})
    r2 = upsert_event(conn, ev2)
    assert r2 == "merged"

    # risk_score big change → updated
    ev3 = ev.model_copy(update={"risk_score": 90, "source_name": "fed", "source_id": "f1"})
    r3 = upsert_event(conn, ev3)
    assert r3 == "updated"
