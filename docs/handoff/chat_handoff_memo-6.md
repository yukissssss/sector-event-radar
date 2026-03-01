# Sector Event Radar — チャット引き継ぎメモ

> これ1枚を新しいClaude/GPTチャットに貼れば文脈が復元できる。
> 経緯の詳細は `project_progress_log.md`、GPTへの相談は `gpt_report_*.md` を参照。

---

## プロジェクト概要

MR-LS（Mean Reversion Long-Short、z2/K3/excl_1、日米両市場）の補助ツール。
半導体セクターのイベントを自動収集 → iPhoneカレンダーに表示。将来はイベント影響の統計分析も。

- GitHub: https://github.com/yukissssss/sector-event-radar (public)
- ローカル: ~/Documents/stock_analyzer/sector_event_radar/
- Python 3.13 / pydantic / SQLite / GitHub Actions

---

## 現在の状態（Session 16完了 2026-03-01）

### 稼働中 — 全4カテゴリ稼働、P0/P1/P2全完了

- **GitHub Actions**: 毎朝07:05 JST自動実行（DRY_RUN=false）
- **FMP Stable API bellwether**: 9銘柄の決算日（`/stable/earnings-calendar`）→ 7 events
- **OPEX**: 6ヶ月分の第3金曜 + 祝日調整 → 6 events
- **BLS static (macro)**: CPI/NFP/PPI — config.yaml静的日程（OMB公式PDF準拠）→ 18 events
- **BEA .ics (macro)**: GDP, PCE — 公式政府カレンダー自動取得 → 14 events
- **FOMC static (macro)**: 2026年8回 — config.yaml静的日程（FRB公式）→ 4 events
- **RSS→Claude抽出 (shock)**: SemiEngineering + EE Times + TrendForce → prefilter → Claude Haiku → 構造化イベント ✅
- **ICS配信**: GitHub Pages → iPhoneカレンダー購読中 ✅ iPhone実機表示確認済み
- **DB永続化**: GitHub Releases（db-latestタグ）
- **テスト**: 155本全通過

### 最新Actionsログ（Session 16 — 2026-03-01）

| カテゴリ | イベント数 | ソース |
|---------|-----------|--------|
| macro | 36 | BLS static 18 + BEA 14 + FOMC 4 |
| bellwether | 7 | FMP Stable |
| flows | 6 | OPEX計算 |
| shock | 1 | HBM4 Validation（Claude抽出→category強制→ポイントイベント化） |
| **ICS all** | **50** | |
| upsert | inserted=0, merged=49 | 安定運用 |
| errors | 0 | 完全クリーン |

### Session 15-16で解決した課題

| 課題 | Session | 対策 |
|------|---------|------|
| P0: shock ICS 0件 | 15 | override_shock_category() + migrate_shock_category() |
| P1: iPhone 3ヶ月表示ノイズ | 16 | 3層防御（SYSTEM_PROMPT + normalize_date_range + migrate_quarter_range） |
| P2: Seen filter確認 | 15 | 18本already-processed確認 |

### 3層防御（Session 16）

| 層 | 場所 | 機能 |
|---|------|------|
| 1. LLM制御 | claude_extract.py | SYSTEM_PROMPTルール10-12: 四半期/月/半期→end_at=null |
| 2. 防火扉 | run_daily.py | normalize_date_range(): 月初起点レンジをend_at=None矯正 |
| 3. DB修復 | run_daily.py | migrate_quarter_range(): 既存の四半期レンジをNULL修正 |

### コスト安全策（実績確認済み）

- **既出記事スキップ**: 18/30本がalready-processed → 無駄なClaude API呼び出しゼロ ✅
- **同一run内URL dedup**: 0 duplicate-in-run ✅
- **Claude投入上限**: max_articles_per_run: 10（config.yaml設定）
- **失敗時再試行**: Claude API例外時はseenにしない→翌日自動再試行

### RSSソース状況

| ソース | 状態 | 記事数 |
|--------|------|--------|
| SemiEngineering | ✅ | 10 |
| EE Times | ✅ | 10 |
| TrendForce Semiconductors | ✅ | 10 |
| BIS Press Releases | disabled | SSL証明書エラー |
| SIA Press Releases | disabled | XMLパースエラー |

### 既知の課題

| 課題 | 状態 | 対応 |
|------|------|------|
| prefilter Stage A全DROP | 観察中 | 新着12本が全てscore=0。半導体無関係記事のみの可能性。数日観察 |
| SIA RSS XMLエラー | disabled | フィード形式の調査が必要 |

### 未稼働

| 機能 | 状態 | 理由 |
|------|------|------|
| macro (FMP Economic Calendar) | ❌ 402 | 有料限定。コード準備済み、課金時にそのまま動く |
| macro (TE) | ❌ | Freeプラン制限 |
| impact.py / audit.py / notify.py | ⏸ | Phase 2スタブ |

### GitHub Secrets

| Secret | 状態 |
|--------|------|
| FMP_API_KEY | ✅ |
| ANTHROPIC_API_KEY | ✅ |
| TE_API_KEY | ❌ Freeプラン制限 |

---

## ファイル構成

```
sector-event-radar/
├── .github/workflows/
│   └── daily.yml                 ← Actions定義（07:05 JST）
├── docs/
│   ├── ics/                      ← ICS出力先（GitHub Pages配信）
│   └── handoff/                  ← 引き継ぎ文書
│       ├── project_progress_log.md
│       ├── chat_handoff_memo.md
│       ├── session15_changes.md
│       ├── session16_changes.md
│       └── gpt_report_*.md
├── src/sector_event_radar/
│   ├── run_daily.py              ← エントリポイント。4 collector独立try/except → upsert → ICS
│   │                               + override/normalize/migrate 関数群
│   ├── collectors/
│   │   ├── scheduled.py          ← FMP Stable bellwether(✅) + FMP macro(402) + TE(スキップ)
│   │   ├── official_calendars.py ← BLS static + BEA .ics + FOMC static
│   │   └── rss.py                ← RSS/Atom取得
│   ├── llm/
│   │   └── claude_extract.py     ← Claude API抽出器 ✅ ルール12本 + 3層防御層1
│   ├── canonical.py              ← canonical_key生成
│   ├── config.py                 ← AppConfig
│   ├── models.py                 ← Event/Article Pydanticモデル
│   ├── db.py                     ← SQLite冪等upsert + article seen管理
│   ├── ics.py                    ← RFC5545 ICS生成（カテゴリprefix + DESCRIPTION定型化）
│   ├── flows.py                  ← OPEX計算
│   ├── prefilter.py              ← RSS記事2段階フィルタ
│   ├── validate.py               ← Event検証
│   └── impact.py / audit.py / notify.py  ← Phase 2スタブ
├── tests/                        ← 155本
│   ├── test_canonical_validate_flows_db.py  (5本)
│   ├── test_phase1.py                       (10本)
│   ├── test_scheduled.py                    (7本)
│   ├── test_fmp_macro.py                    (15本)
│   ├── test_official_calendars.py           (46本)
│   ├── test_bls_html_fallback.py            (30本)
│   ├── test_shock_pipeline.py               (3本)
│   ├── test_ics_display.py                  (12本)
│   ├── test_shock_category_fix.py           (10本) ← Session 15
│   └── test_quarter_range_fix.py            (17本) ← Session 16
├── config.yaml
└── pyproject.toml
```

---

## 設計上の重要判断

- **4カテゴリ固定**: macro/bellwether/flows/shock。セクター差はsector_tagsで吸収
- **部分失敗設計**: collector間は独立try/except。どれが落ちてもICS生成まで到達
- **canonical_key**: `{category}:{entity}:{sub_type}:{YYYY-MM-DD}`。shock系は`short_hash(source_url)`
- **0件ICS出力**: 全カテゴリのICSを常に出力（空でもVCALENDAR構造維持）
- **FMP Stable API**: v3 Legacyは2025-08-31廃止。`/stable/earnings-calendar`のみ無料
- **macro公式ソース**: BLS static(OMB) + BEA .ics自動取得 + FOMC静的日程
- **BLS 3段フォールバック**: bls_mode=static(デフォルト) → ics時: .ics → HTML → static
- **shock抽出**: Claude Haiku 4.5使用。RSS title+summary → 構造化JSON
- **shock category強制**: override_shock_category()でcategory=shock固定。Claudeの分類に依存しない
- **3層防御（四半期レンジ）**: SYSTEM_PROMPT + normalize_date_range() + migrate_quarter_range()
- **レンジ判定 思想A**: ノイズ絶対殺す。月初起点→月初or月末のレンジは全て潰す
- **コスト3重ガード**: 既出スキップ + run内dedup + max_articles_per_run
- **ICSタイトルprefix**: `[MACRO]`/`[BW]`/`[FLOW]`/`[SHOCK]`
- **DESCRIPTION定型化**: Risk/Confidence + Tags + Source URL + Evidence

---

## データフロー

```
毎朝07:05 JST (GitHub Actions)
  │
  ├─ migrate_shock_category()  — 既存誤分類修正（try/except保護）
  ├─ migrate_quarter_range()   — 既存四半期レンジ修正（try/except保護）
  │
  ├─ FMP Stable → bellwether 7 events ──────────────────────────┐
  ├─ OPEX計算 → 6 events ──────────────────────────────────────┤
  ├─ BLS static → CPI/NFP/PPI 18 events ───────────────────────┤
  ├─ BEA .ics → GDP/PCE 14 events ─────────────────────────────┤
  ├─ FOMC static → 4 events ───────────────────────────────────┤
  └─ RSS(SemiEng+EETimes+TrendForce) → prefilter(Stage A/B) ──┤
       → Seen filter(DB既出+run内dedup) → LLM guard(max 10)    │
       → Claude Haiku 4.5                                       │
       → override_shock_category()                              │
       → normalize_date_range()     ← 防火扉                   │
       → shock events ─────────────────────────────────────────┤
                                                                 │
              canonical_key → validate → upsert (SQLite)
                               │
              events_to_ics ([PREFIX] title + 定型DESCRIPTION)
                               │
    all(50) / macro(36) / bellwether(7) / flows(6) / shock(1)
                               │
         docs/ics/ → GitHub Pages → iPhoneカレンダー
```

---

## 次のアクション

1. **データ蓄積観察**: 数日放置してshockイベントの蓄積・Seen filterの効果を継続確認
2. **prefilter Stage Aチューニング**: 新着記事が全DROP（score=0）の日が続く場合、閾値やキーワード調整
3. **Phase 2**: impact.py（イベント影響の統計分析）— shockデータが溜まったら着手
