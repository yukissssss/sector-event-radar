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

## 現在の状態（Session 14完了 2026-03-01）

### 稼働中 — 全4カテゴリ稼働、shock初イベント抽出成功

- **GitHub Actions**: 毎朝07:05 JST自動実行（DRY_RUN=false）
- **FMP Stable API bellwether**: 9銘柄の決算日（`/stable/earnings-calendar`）→ 7 events
- **OPEX**: 6ヶ月分の第3金曜 + 祝日調整 → 6 events
- **BLS static (macro)**: CPI/NFP/PPI — config.yaml静的日程（OMB公式PDF準拠）→ 18 events (cpi=6, nfp=6, ppi=6)
- **BEA .ics (macro)**: GDP, PCE(Personal Income and Outlays) — 公式政府カレンダー自動取得 → 14 events
- **FOMC static (macro)**: 2026年8回 — config.yaml静的日程（FRB公式）→ 4 events
- **RSS→Claude抽出 (shock)**: SemiEngineering + EE Times + TrendForce → prefilter → Claude Haiku → 構造化イベント ✅ **初イベント抽出成功**
- **ICS配信**: GitHub Pages → iPhoneカレンダー購読中
- **DB永続化**: GitHub Releases（db-latestタグ）
- **テスト**: 128本（113 + shock回帰3本 + ICS表示12本）

### 最新Actionsログ（Session 14 — 2026-03-01）

| カテゴリ | イベント数 | ソース |
|---------|-----------|--------|
| macro | 37 | BLS static 18 + BEA 14 + FOMC 4 + 1 |
| bellwether | 7 | FMP Stable |
| flows | 6 | OPEX計算 |
| shock | 0 (ICS) | inserted=1（HBM4）だがICSウィンドウ外の可能性 |
| **ICS all** | **50** | |
| unscheduled | 1 | TrendForce「HBM4 Validation Expected in 2Q26」 |
| upsert | inserted=1, merged=49 | shock初insert |
| errors | 0 | BIS/SIA disabled化で完全消滅 |

### RSSソース状況

| ソース | 状態 | 記事数 |
|--------|------|--------|
| SemiEngineering | ✅ | 10 |
| EE Times | ✅ | 10 |
| TrendForce Semiconductors | ✅ | 10 |
| BIS Press Releases | disabled | SSL証明書エラー |
| SIA Press Releases | disabled | XMLパースエラー |

### コスト安全策（Session 14で実装）

- **既出記事スキップ**: articlesテーブルで過去run処理済みをスキップ
- **同一run内URL dedup**: seen_in_run setで重複排除
- **Claude投入上限**: max_articles_per_run: 10（config.yaml設定）
- **失敗時再試行**: Claude API例外時はseenにしない→翌日自動再試行

### ICS表示改善（Session 14で実装）

- **タイトルプレフィックス**: `[MACRO]`/`[BW]`/`[FLOW]`/`[SHOCK]` — iPhone一覧で即座にカテゴリ判別
- **DESCRIPTION定型化**: Risk/Confidence、Tags、Source URL、Evidence構造化表示
- **DB→ICSでsource_url/evidence取得**: event_sources LEFT JOINで実データ表示

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

### 既知の課題

| 課題 | 状態 | 対応 |
|------|------|------|
| shock ICS 0件 | 調査中 | inserted=1だがICS shock出力が0。start_atがICS生成ウィンドウ外か、category不一致の可能性 |
| SIA RSS XMLエラー | disabled | フィード形式の調査が必要 |
| テスト未実行 | push後 | ローカルpytest 128本の確認が必要 |

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
│       ├── session14_changes-4.md
│       └── gpt_report_*.md
├── src/sector_event_radar/
│   ├── run_daily.py              ← エントリポイント。4 collector独立try/except → upsert → ICS
│   ├── collectors/
│   │   ├── scheduled.py          ← FMP Stable bellwether(✅) + FMP macro(402) + TE(スキップ)
│   │   ├── official_calendars.py ← BLS static + BEA .ics + FOMC static + HTML fallback(残存)
│   │   └── rss.py                ← RSS/Atom取得
│   ├── llm/
│   │   └── claude_extract.py     ← Claude API抽出器 ✅ source_idユニーク化済み
│   ├── canonical.py              ← canonical_key: {category}:{entity}:{sub_type}:{YYYY-MM-DD}
│   ├── config.py                 ← AppConfig + RssSource.disabled + LlmConfig + macro_rules_compiled()
│   ├── models.py                 ← Event/Article Pydanticモデル
│   ├── db.py                     ← SQLite冪等upsert + is_article_seen + mark_article_seen(ON CONFLICT UPDATE)
│   ├── ics.py                    ← RFC5545 ICS生成（カテゴリprefix + DESCRIPTION定型化）
│   ├── flows.py                  ← OPEX計算（第3金曜+祝日調整）
│   ├── prefilter.py              ← RSS記事2段階フィルタ（Stage A/Bログ付き）
│   ├── validate.py               ← Event検証
│   └── impact.py / audit.py / notify.py  ← Phase 2スタブ
├── tests/
│   ├── test_canonical_validate_flows_db.py  (5本)
│   ├── test_phase1.py                       (10本)
│   ├── test_scheduled.py                    (7本)
│   ├── test_fmp_macro.py                    (15本)
│   ├── test_official_calendars.py           (46本)
│   ├── test_bls_html_fallback.py            (30本)
│   ├── test_shock_pipeline.py               (3本) ← Session 14新規
│   └── test_ics_display.py                  (12本) ← Session 14新規
├── config.yaml                   ← keywords(23), macro_title_map(15), RSS(5,うち2disabled), bellwether(9), fomc_dates(8), bls_mode, bls_static, llm
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
- **BLS static年次更新**: config.yaml `bls_static.years."2027"` を追加するPR。0件警告で更新忘れ検知
- **ScoredArticle wrapper**: prefilter.pyのScoredArticleはArticleをラップ。`article.article.title`でアクセス
- **shock抽出**: Claude Haiku 4.5使用。RSS title+summary → 構造化JSON。技術解説記事は抽出対象外
- **コスト3重ガード**: 既出スキップ + run内dedup + max_articles_per_run
- **失敗時再試行**: extract_succeededフラグ。API例外時はseenにしない
- **source_idユニーク化**: `claude:{url}#{hash(title:start_at)[:8]}`。1記事複数イベント対応
- **ICSタイトルprefix**: `[MACRO]`/`[BW]`/`[FLOW]`/`[SHOCK]` — iPhone一覧でカテゴリ即判別
- **DESCRIPTION定型化**: Risk/Confidence + Tags + Source URL + Evidence。改行は`\n`→`_escape()`でICS仕様変換

---

## データフロー

```
毎朝07:05 JST (GitHub Actions)
  │
  ├─ FMP Stable /stable/earnings-calendar → bellwether 7 events ─┐
  ├─ OPEX計算 → 6 events ───────────────────────────────────────┤
  ├─ BLS static (config.yaml) → CPI/NFP/PPI 18 events ─────────┤
  ├─ BEA .ics → GDP/PCE 14 events ─────────────────────────────┤
  ├─ FOMC static → 4 events ───────────────────────────────────┤
  └─ RSS(SemiEng+EETimes+TrendForce) → prefilter(Stage A/B) ──┤
       → Seen filter(DB既出+run内dedup) → LLM guard(max 10)    │
       → Claude Haiku 4.5 → shock events ──────────────────────┤
                                                                 │
              canonical_key → validate → upsert (SQLite)
                               │
              events_to_ics ([PREFIX] title + 定型DESCRIPTION)
                               │
    all(50) / macro(37) / bellwether(7) / flows(6) / shock(0)
                               │
         docs/ics/ → GitHub Pages → iPhoneカレンダー
```

---

## 次のアクション

1. **shock ICS 0件調査**: inserted=1なのにICS shock出力が0。start_atウィンドウ or category確認
2. **データ蓄積**: 数日放置してshockイベントの蓄積を観察。Seen filterの効果確認
3. **iPhoneで見栄え確認**: [MACRO] prefix + DESCRIPTION改行が正しく表示されるか
4. **Phase 2**: impact.py（イベント影響の統計分析）— shockデータが溜まったら着手
