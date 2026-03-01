# Sector Event Radar — チャット引き継ぎメモ

> これ1枚を新しいClaude/GPTチャットに貼れば文脈が復元できる。
> 経緯の詳細は `project_progress_log.md`、GPTへの相談は `gpt_report_*.md` を参照。

---

## プロジェクト概要

MR-LS（Mean Reversion Long-Short、z2/K3/excl_1、日米両市場）の補助ツール。
半導体セクターのイベントを自動収集 → iPhoneカレンダーに表示。将来はイベント影響の統計分析も。

- GitHub: https://github.com/yukissssss/sector-event-radar (public)
- ローカル: ~/Documents/stock_analyzer/sector_event_radar/
- Python 3.13 / pydantic / feedparser / SQLite / GitHub Actions

---

## 現在の状態（Session 16 全Task完了 2026-03-01）

### 稼働中 — 全4カテゴリ + Federal Register BIS

| ソース | タイプ | 状態 | イベント数 |
|--------|--------|------|-----------|
| BLS static | macro | ✅ | 18 |
| BEA .ics | macro | ✅ | 14 |
| FOMC static | macro | ✅ | 4 |
| FMP Stable | bellwether | ✅ | 7 |
| OPEX計算 | flows | ✅ | 6 |
| Federal Register BIS | shock | ✅ NEW | 4 |
| SemiEng/EETimes/TrendForce→Claude | shock | ✅ | 10+10+10 fetched |
| SIA RSS | shock | ⚠️ 0件 | SIA側XML破損。enabled放置(無害) |
| **ICS all** | | | **54 events** |

### 最新Actionsログ（2026-03-01 23:08 JST）

```
scheduled=47(macro36+bw7+FR_BIS4), computed=6, unscheduled=0
inserted=4, merged=49, rejected=0, errors=0
ICS: all=54, macro=36, bellwether=7, flows=6, shock=5
```

### Session 15-16で解決した全課題

| 課題 | 対策 |
|------|------|
| P0: shock ICS 0件 | override_shock_category() |
| P1: 四半期3ヶ月表示 | 3層防御(SYSTEM_PROMPT+normalize+migrate) |
| prefilter全DROP | キーワード23→55語, threshold 4.0→3.0 |
| SIA XMLエラー | feedparser導入(SIA側破損で0件だが無害) |
| BIS RSS死亡 | Federal Register API代替(4 events) |
| validate now-7d | GPT承認:現状維持(正常動作) |

### テスト: 181本全通過

---

## ファイル構成（主要）

```
src/sector_event_radar/
├── run_daily.py              ← エントリポイント + override/normalize/migrate
├── collectors/
│   ├── scheduled.py          ← FMP Stable bellwether
│   ├── official_calendars.py ← BLS/BEA/FOMC
│   ├── rss.py                ← feedparser優先 + ETフォールバック
│   └── federal_register.py   ← Federal Register BIS API (NEW)
├── llm/claude_extract.py     ← Claude Haiku + 3層防御層1
├── prefilter.py              ← 55kw/threshold3.0
├── validate.py               ← now-7dルール(変更不要)
└── impact.py                 ← Phase 2スタブ
```

---

## 運用哲学（絶対守る）
1. ノイズ絶対殺す
2. 幻覚ゼロ
3. 部分失敗OK
4. コストガード

---

## 次のアクション

1. **Task D: Phase 2 impact.py** — GPTに設計相談中
2. config.yaml旧BIS RSSエントリ削除（整理）
3. 観察継続: shock蓄積、prefilter通過率
