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

## 現在の状態（Session 13完了 2026-03-01）

### 稼働中 — 全4カテゴリ稼働

- **GitHub Actions**: 毎朝07:05 JST自動実行（DRY_RUN=false）
- **FMP Stable API bellwether**: 9銘柄の決算日（`/stable/earnings-calendar`）→ 7 events
- **OPEX**: 6ヶ月分の第3金曜 + 祝日調整 → 6 events
- **BLS static (macro)**: CPI/NFP/PPI — config.yaml静的日程（OMB公式PDF準拠）→ 18 events (cpi=6, nfp=6, ppi=6)
- **BEA .ics (macro)**: GDP, PCE(Personal Income and Outlays) — 公式政府カレンダー自動取得 → 14 events
- **FOMC static (macro)**: 2026年8回 — config.yaml静的日程（FRB公式）→ 4 events
- **RSS→Claude抽出 (shock)**: SemiEngineering RSS → prefilter → Claude Haiku → 構造化イベント ✅ 稼働開始
- **ICS配信**: GitHub Pages → iPhoneカレンダー購読中
- **DB永続化**: GitHub Releases（db-latestタグ）
- **テスト**: 113本全通過

### 最新Actionsログ（Session 13 — 2026-03-01）

| カテゴリ | イベント数 | ソース |
|---------|-----------|--------|
| macro | 36 | BLS static 18 + BEA 14 + FOMC 4 |
| bellwether | 7 | FMP Stable |
| flows | 6 | OPEX計算 |
| shock | 0 | Claude抽出稼働中（抽出対象記事なしで0）|
| **ICS all** | **49** | |
| upsert | inserted=0, merged=49 | 安定運用 |
| errors | 1 | BIS RSS SSL証明書のみ |

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
| ANTHROPIC_API_KEY | ✅ Session 13で登録 |
| TE_API_KEY | ❌ Freeプラン制限 |

### 既知のerrors（対応不要）

| エラー | 原因 | 対応 |
|--------|------|------|
| RSS BIS Press Releases failed: SSL CERTIFICATE_VERIFY_FAILED | bis.doc.govのSSL証明書がGitHub Actionsから検証不可 | RSS拡充時に代替ソース検討 |

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
│       └── gpt_report_*.md
├── src/sector_event_radar/
│   ├── run_daily.py              ← エントリポイント。4 collector独立try/except → upsert → ICS
│   ├── collectors/
│   │   ├── scheduled.py          ← FMP Stable bellwether(✅) + FMP macro(402) + TE(スキップ)
│   │   ├── official_calendars.py ← BLS static + BEA .ics + FOMC static + HTML fallback(残存)
│   │   └── rss.py                ← RSS/Atom取得
│   ├── llm/
│   │   └── claude_extract.py     ← Claude API抽出器 ✅ Session 13で稼働開始
│   ├── canonical.py              ← canonical_key: {category}:{entity}:{sub_type}:{YYYY-MM-DD}
│   ├── config.py                 ← AppConfig + macro_rules_compiled() + fomc_dates + bls_mode + bls_static
│   ├── models.py                 ← Event/Article Pydanticモデル
│   ├── db.py                     ← SQLite冪等upsert
│   ├── ics.py                    ← RFC5545 ICS生成（0件でも出力）
│   ├── flows.py                  ← OPEX計算（第3金曜+祝日調整）
│   ├── prefilter.py              ← RSS記事2段階フィルタ（ScoredArticle wrapper）
│   ├── validate.py               ← Event検証
│   └── impact.py / audit.py / notify.py  ← Phase 2スタブ
├── tests/
│   ├── test_canonical_validate_flows_db.py  (5本)
│   ├── test_phase1.py                       (10本)
│   ├── test_scheduled.py                    (7本)
│   ├── test_fmp_macro.py                    (15本)
│   ├── test_official_calendars.py           (46本)
│   └── test_bls_html_fallback.py            (30本)
├── config.yaml                   ← keywords(23), macro_title_map(15), RSS(2), bellwether(9), fomc_dates(8), bls_mode, bls_static(CPI/NFP/PPI 2026全36日程)
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
- **BLS 3段フォールバック**: bls_mode=static(デフォルト) → ics時: .ics → HTML → static。bls.govはGitHub ActionsのIPをドメインごとブロック(403)
- **BLS static年次更新**: config.yaml `bls_static.years."2027"` を追加するPR。0件警告で更新忘れ検知
- **BLS APIは別ホスト**: api.bls.gov はwww.bls.govとインフラが別。将来API利用時はActions上で疎通プローブ推奨
- **ScoredArticle wrapper**: prefilter.pyのScoredArticleはArticleをラップ。`article.article.title`でアクセス
- **shock抽出**: Claude Haiku使用。RSS title+summary → 構造化JSON。技術解説記事は抽出対象外（0 events正常）
- **macro_rules_compiled()**: 呼び出し元で1回コンパイル、引数で渡す
- **matched=0警告**: config不整合を即座に検知

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
  └─ RSS(SemiEngineering) → prefilter → Claude Haiku → shock ──┤
                                                                 │
              canonical_key → validate → upsert (SQLite)
                               │
              events_to_ics (全5カテゴリ)
                               │
    all(49) / macro(36) / bellwether(7) / flows(6) / shock(0)
                               │
         docs/ics/ → GitHub Pages → iPhoneカレンダー
```

---

## 次のアクション

1. **RSS拡充**（BIS代替 — SSL証明書問題回避、他の半導体ニュースソース追加）
2. **Phase 2**: impact.py（イベント影響の統計分析）
