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

## 現在の状態（Session 11完了 2026-02-28）

### 稼働中

- **GitHub Actions**: 毎朝07:05 JST自動実行（DRY_RUN=false）
- **FMP Stable API bellwether**: 9銘柄の決算日（`/stable/earnings-calendar`）→ 7 events
- **OPEX**: 6ヶ月分の第3金曜 + 祝日調整 → 5 events
- **BLS .ics (macro)**: CPI, NFP(Employment Situation), PPI — 公式政府カレンダー自動取得
- **BEA .ics (macro)**: GDP, PCE(Personal Income and Outlays) — 公式政府カレンダー自動取得
- **FOMC static (macro)**: 2026年8回 — config.yaml静的日程（FRB公式）
- **ICS配信**: GitHub Pages → iPhoneカレンダー購読中
- **DB永続化**: GitHub Releases（db-latestタグ）
- **テスト**: 47本(既存) + 45本(official_calendars) = 92本

### 未稼働

| 機能 | 状態 | 理由 |
|------|------|------|
| macro (FMP Economic Calendar) | ❌ 402 | 有料限定。コード準備済み、課金時にそのまま動く |
| macro (TE) | ❌ | Freeプラン制限 |
| shock (RSS→Claude) | ⏸ | ANTHROPIC_API_KEY未登録 |
| impact.py / audit.py / notify.py | ⏸ | Phase 2スタブ |

### GitHub Secrets

| Secret | 状態 |
|--------|------|
| FMP_API_KEY | ✅（public化で消失→再登録済み）|
| TE_API_KEY | ❌ Freeプラン制限 |
| ANTHROPIC_API_KEY | ❌ 未登録 |

---

## ファイル構成

```
sector-event-radar/
├── .github/workflows/
│   └── daily.yml                 ← Actions定義（07:05 JST）
├── docs/
│   ├── ics/                      ← ICS出力先（GitHub Pages配信）
│   └── handoff/                  ← 引き継ぎ文書
│       ├── project_progress_log.md   ← 経緯ログ（時系列）
│       ├── chat_handoff_memo.md      ← 本ファイル（状態+構造）
│       └── gpt_report_*.md          ← GPT相談（都度作成）
├── src/sector_event_radar/
│   ├── run_daily.py              ← エントリポイント。4 collector独立try/except → upsert → ICS
│   ├── collectors/
│   │   ├── scheduled.py          ← FMP Stable bellwether(✅) + FMP macro(402) + TE(スキップ)
│   │   ├── official_calendars.py ← 🆕 BLS/BEA .icsパーサ + FOMC静的日程
│   │   └── rss.py                ← RSS/Atom取得
│   ├── llm/
│   │   └── claude_extract.py     ← Claude API抽出器（コード準備済み、未稼働）
│   ├── canonical.py              ← canonical_key: {category}:{entity}:{sub_type}:{YYYY-MM-DD}
│   ├── config.py                 ← AppConfig + macro_rules_compiled() + fomc_dates
│   ├── models.py                 ← Event/Article Pydanticモデル
│   ├── db.py                     ← SQLite冪等upsert
│   ├── ics.py                    ← RFC5545 ICS生成（0件でも出力）
│   ├── flows.py                  ← OPEX計算（第3金曜+祝日調整）
│   ├── prefilter.py              ← RSS記事2段階フィルタ
│   ├── validate.py               ← Event検証
│   └── impact.py / audit.py / notify.py  ← Phase 2スタブ
├── tests/
│   ├── test_canonical_validate_flows_db.py  (5本)
│   ├── test_phase1.py                       (10本)
│   ├── test_scheduled.py                    (7本)
│   ├── test_fmp_macro.py                    (15本)
│   └── test_official_calendars.py           (45本) ← 🆕 Session 11
├── config.yaml                   ← keywords(23), macro_title_map(15パターン), RSS(2本), bellwether(9銘柄), fomc_dates(8回)
└── pyproject.toml
```

---

## 設計上の重要判断

- **4カテゴリ固定**: macro/bellwether/flows/shock。セクター差はsector_tagsで吸収
- **部分失敗設計**: collector間は独立try/except。どれが落ちてもICS生成まで到達
- **canonical_key**: `{category}:{entity}:{sub_type}:{YYYY-MM-DD}`。shock系は`short_hash(source_url)`
- **0件ICS出力**: 全カテゴリのICSを常に出力（空でもVCALENDAR構造維持）
- **FMP Stable API**: v3 Legacyは2025-08-31廃止。`/stable/earnings-calendar`のみ無料。`time`(bmo/amc)フィールド消失
- **macro公式ソース**: BLS/BEA .ics自動取得 + FOMC静的日程。FMP/TE有料を完全代替
- **ICSパーサ**: RFC5545最小限（VEVENT/DTSTART/SUMMARY）のみ依存。HHMMSS+HHMM両対応
- **macro_rules_compiled()**: 呼び出し元で1回コンパイル、引数で渡す（毎イベント再コンパイルしない）
- **matched=0警告**: config不整合を即座に検知（vevents>0 && matched==0 → warning）

---

## データフロー

```
毎朝07:05 JST (GitHub Actions)
  │
  ├─ FMP Stable /stable/earnings-calendar → bellwether 7 events ─┐
  ├─ OPEX計算 → 5 events ───────────────────────────────────────┤
  ├─ 🆕 BLS .ics → CPI/NFP/PPI ────────────────────────────────┤
  ├─ 🆕 BEA .ics → GDP/PCE ────────────────────────────────────┤
  ├─ 🆕 FOMC static → 8 meetings/year ─────────────────────────┤
  ├─ FMP /stable/economic-calendar → ❌ 402 ────────────────────┤
  └─ RSS→Claude → ⏸ API_KEY未登録 ─────────────────────────────┤
                                                                 │
              canonical_key → validate → upsert (SQLite)
                               │
              events_to_ics (全5カテゴリ)
                               │
    all / flows(5) / bellwether(7) / macro(CPI+NFP+PPI+GDP+PCE+FOMC) / shock(0)
                               │
         docs/ics/ → GitHub Pages → iPhoneカレンダー
```

---

## Session 11で未適用の作業

### pytest + push が必要

以下のファイルはローカルに配置済みだが、pytest未実行・未push：

```bash
# 配置済み
src/sector_event_radar/collectors/official_calendars.py   ← 新規
src/sector_event_radar/config.py                          ← 上書き（fomc_dates追加）
src/sector_event_radar/run_daily.py                       ← 上書き（official collector統合 + 空カテゴリ修正）
tests/test_official_calendars.py                          ← 新規
config.yaml                                               ← 上書き（フルスペル15パターン + fomc_dates 8回）

# 次のチャットでやること
cd ~/Documents/stock_analyzer/sector_event_radar
pytest tests/ -v                 # 92本全通過を確認
git add -A
git commit -m "feat: official government macro collectors (BLS/BEA/FOMC) with GPT review fixes"
git push
# → Actions実行 → macro.ics にCPI/NFP/PPI/GDP/PCE/FOMC が入ることを確認
# → iPhoneカレンダーでmacro表示確認
```

---

## GPTレビュー指摘（Session 11で反映済み）

| # | 指摘 | 対応 |
|---|------|------|
| 2 | macro_rules毎回再コンパイル | fetch_ics_macro_events冒頭で1回コンパイル→引数渡し |
| 3 | DTSTART秒なし(HHMM)で全部None | _parse_datetime_flexible()でHHMMSS/HHMM両対応 |
| 4 | source_url=Noneでソースに飛べない | BLS/BEA→ics_url、FOMC→FRB_FOMC_URL設定 |
| 5 | matched=0でも静かに進む | vevents>0&&matched==0でwarning |

### GPT指摘で未対応（将来タスク）

| # | 指摘 | 方針 |
|---|------|------|
| 6 | スケジュール変更時に古い予定が残る | reconciliation処理（cancel/archived）を将来実装 |

---

## 次のアクション

1. **pytest + push** — 92本全通過→commit→push
2. **Actions実行確認** — `Official macro: collected N` ログ + macro.icsに中身
3. **iPhoneカレンダー確認** — CPI/FOMC等が実際に表示されるか
4. **ANTHROPIC_API_KEY登録** → shock有効化
5. **Phase 2**: impact.py
