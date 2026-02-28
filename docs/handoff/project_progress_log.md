# Sector Event Radar — プロジェクト進捗ログ

最終更新: 2026-02-28
リポジトリ: https://github.com/yukissssss/sector-event-radar (public)
ローカル: ~/Documents/stock_analyzer/sector_event_radar/

> このファイルはセッションごとに追記する累積ログ。
> 新しいエントリは先頭に追加する（最新が上）。
> GPTとの共同開発用、および新しいClaude/GPTチャットへの引き継ぎ用。
>
> **docs/handoff/ 内の4ファイルの役割:**
> | ファイル | 役割 |
> |---------|------|
> | project_progress_log.md | 本ファイル。累積型進捗ログ（セッションごとに先頭追記）|
> | chat_handoff_memo.md | 新チャットにコピペで文脈復元する凝縮版 |
> | file_map_handoff.md | 全ファイルの役割・場所・実装状態一覧 |
> | gpt_progress_report_*.md | GPTへの報告+相談メモ（都度作成）|

---

## Session 9 — 2026-02-28 ★現在★
### ICS 0件修正 + GitHub Pages有効化 + iPhoneカレンダー購読成功

**実施内容:**
- GPT回答を受領:
  - Q1→FMP Economic Calendar (`/v3/economic_calendar`) を第一候補、カバーできない分だけ静的YAMLで補完
  - Q2→Pages → macro代替実装 → Claude抽出オンの順
  - 追加指摘: 0件カテゴリのICSが出力されない問題
- ICS 0件問題修正: `run_daily.py` の `_generate_ics_files()` から `if not cat_events: continue` を削除
  - 空カテゴリでもVCALENDARヘッダ+フッタのみの有効なICSを出力するように変更
- commit + push（`git pull --rebase` でActions自動commitとの競合を解消）
- Actions手動実行 → `docs/ics/` に全5ファイル出力を確認
- GitHub Pages有効化を試行 → **privateリポジトリではFree planでPages利用不可**と判明
- リポジトリを**public化**して再度Pages設定 → Source: Deploy from a branch / main / /docs
- Pages配信確認: `https://yukissssss.github.io/sector-event-radar/ics/sector_events_all.ics` でICS取得成功
- **iPhoneカレンダー購読設定完了** → OPEX予定がカレンダーアプリに表示されることを確認

**決定事項:**
- GPT推奨に従い、macro指標は**FMP Economic Calendarを第一候補**、カバーできない分だけ静的YAMLで補完
- 優先順位: (1) GitHub Pages ✅完了 → (2) macro代替実装 → (3) Claude抽出オン
- リポジトリをpublic化（トレードロジックはMR-LS側、APIキーはSecretsで安全）

**ICS配信状態（GitHub Pages）:**
| ファイル | URL | 状態 |
|---------|-----|------|
| sector_events_all.ics | `https://yukissssss.github.io/sector-event-radar/ics/sector_events_all.ics` | ✅ 購読中 |
| sector_events_flows.ics | 同上パス | ✅ 配信中 |
| sector_events_bellwether.ics | 同上パス | ✅ 配信中 |
| sector_events_macro.ics | 同上パス | ✅ 配信中（空） |
| sector_events_shock.ics | 同上パス | ✅ 配信中（空） |

**変更ファイル:**
- `src/sector_event_radar/run_daily.py` — `_generate_ics_files()` から `if not cat_events: continue` を削除（2行削除のみ）

**次のアクション:**
1. FMP Economic Calendar実装（`scheduled.py` に `fetch_fmp_macro_events()` 追加）→ macroカテゴリ有効化
2. ANTHROPIC_API_KEY登録 + RSSフィード追加 + Claude抽出E2Eテスト → shockカテゴリ有効化
3. Phase 2: impact.py実装

---

## Session 8 — 2026-02-27 夜
### GitHub Actions本番稼働 + FMP collector実装

**実施内容:**
- GPT提案の選択肢C（ハイブリッド）を採用
- GitHub private リポジトリ作成 → initial commit (29ファイル)
- GitHub Actions dry-run初回実行 → ✅ 緑
- DB永続化: GitHub Releases方式で `db-latest` タグ確認
- TE/FMP collectors実装 → 22テスト全通過 → push
- FMP APIキー取得(Free plan) → Secret登録
- DRY_RUN=false に変更 → FMP collector本番稼働 → ✅ 緑
- TE: Freeプランでは**API呼び出し不可**と判明 → 当面スキップ

**決定事項:**
- DB永続化はGitHub Releases方式（Artifact=90日削除、Cache=保持不安定のため不採用）
- TEスキップ → macro指標は別手段で取得（GPTに相談中）
- bellwether 9銘柄: NVDA/TSM/ASML/AMD/AVGO/MSFT/GOOGL/AMZN/META

**現在の稼働状態:**
| Collector | 状態 | 内容 |
|-----------|------|------|
| OPEX (computed) | ✅ 稼働 | 6ヶ月分、第3金曜+祝日調整 |
| FMP (bellwether) | ✅ 稼働 | 9銘柄の決算日 |
| TE (macro) | ⏸ スキップ | Freeプラン制限 |
| RSS→Claude (shock) | ⏸ 未有効 | ANTHROPIC_API_KEY未登録 |

**GPTへの相談事項:**
- Q1: TEなしのmacro指標取得方針（FMP代替 / RSS→Claude / 静的YAML / ハイブリッド）
- Q2: 次の優先順位（GitHub Pages / Claude抽出オン / macro代替実装）

**変更ファイル:**
- `collectors/scheduled.py` — スタブ→TE/FMP完全実装
- `config.py` — bellwether_tickers, te_country, te_importance追加
- `run_daily.py` — collector呼び出しにconfig値渡し
- `config.yaml` — bellwether 9銘柄 + TE設定
- `tests/test_scheduled.py` — 新規7テスト
- `.github/workflows/daily.yml` — 新規（Actions定義）
- `.gitignore` — 新規
- `docs/handoff/` — 引き継ぎ文書2点

---

## Session 7 — 2026-02-27 午後
### Phase 1実装完了 + ローカル環境構築

**実施内容:**
- GPT提案の着手順（③→②→④→⑤→⑥）で全修正を実装
- setup_sector_event_radar.py で ~/Documents/stock_analyzer/ に展開
- venv作成 → pip install → pytest 15テスト全通過

**修正内容（Phase 1 DoD）:**
| 順 | 項目 | 内容 |
|-:|------|------|
| ③ | canonical.py | shock系hash: `short_hash(title)` → `short_hash(source_url or source_id)` |
| ② | claude_extract.py | 完全書き直し: x-api-key認証、tool schema全定義、_parse_tool_output()、429/529対応、幻覚防止9ルール |
| ④ | run_daily.py | 3 collector独立try/except、部分失敗→ICS生成必ず到達、`--ics-dir`（複数ICS） |
| ⑤ | ics.py | RFC5545 line folding `_fold_line()`、マルチバイト安全、CRLF、evidence→DESCRIPTION |
| ⑥ | テスト | OPEX年ズレ分岐、shock hash検証、新テスト11本 |

**成果物:**
- sector_event_radar_phase1.zip（26ファイル）
- phase1_changelog.md
- setup_sector_event_radar.py（セルフコンテインド展開スクリプト）

---

## Session 6 — 2026-02-27 午後
### GPT Handoff準備

**実施内容:**
- GPTに渡す10章構成のハンドオフメモ作成（gpt_handoff_memo_phase1.md）
- 3点セット: メモ + 設計書docx + スケルトンzip をGPTに送信
- GPT回答: 着手順は③→②→④→⑤→⑥、①ticker_mapは別枠早期検証

**GPT提案の着手順:**
1. ③ canonical.py shock系hash修正（最小・自己完結）
2. ② claude_extract.py 書き直し（API仕様が明確）
3. ④ run_daily.py 全体フロー（②③に依存）
4. ⑤ ics.py RFC5545対応（独立タスク）
5. ⑥ テスト調整（全修正後に一括）
6. ① ticker_map 実データ検証（別枠、Phase 2前）

---

## Session 5 — 2026-02-27 午前〜午後
### Phase 1方針決定 + OPEX深掘り

**実施内容:**
- Phase 1の範囲を「イベント収集→DB→.ics生成が毎朝自動実行」に確定
- 影響評価・ブリーフィング・月次監査は後フェーズ
- 最初に固める3点: ticker_map実データ検証、canonical.py shock系hash修正、run_daily部分失敗設計

**OPEX教育セッション:**
- マーケットメーカーのデルタヘッジ解消メカニズム
- 第3金曜の建玉集中理由、put/call ratio活用、Max Pain理論
- オプション基礎（株vs権利、発行メカニズム、満期構造、売り手構成）
- 可視化: market_maker_opex.jsx + market_maker_explained.jsx

---

## Session 4 — 2026-02-27 午前
### 設計書v3 + 成果物マッピング + カテゴリ設計

**実施内容:**
- 設計書v3完成（アイコン付き表紙）
- deliverable_map.jsx: 3台iPhoneモックアップで6成果物の表示先マッピング
- system_architecture.jsx: 2系統データフロー、LLM使用3箇所のみ

**設計判断:**
- 4カテゴリ（macro/bellwether/flows/shock）は「イベント性質」による汎用分類 → 増やさない
- セクター区別はsector_tagsで吸収
- マルチセクター拡張時にdata_mappingsが線形増加 → Phase 4で対策

---

## Session 3 — 2026-02-27 午前
### GPTスケルトンコード精読

**実施内容:**
- GPT生成のPythonスケルトン（22ファイル）を全ファイル精読
- 流用OK: validate/utils/config/notify/prefilter/db
- 修正必要: canonical/flows/ics/impact/claude_extract
- 具体的バグ5件特定（canonical.py hashロジック、ics.py line folding未実装等）

---

## Session 2 — 2026-02-27 早朝
### GPT peer review用仕様書作成

**実施内容:**
- sector_event_radar_spec_for_gpt.docx 作成（AI-to-AI技術仕様書）
- モジュール契約書、受入基準、既知問題開示、レビューチェックリスト
- GPT回答: 82/100スコア、14項目評価（R1-R14）、優先修正3点

**GPT指摘の優先修正3点:**
1. canonical_key衝突回避（shock系）
2. ticker alias仕様化
3. run_daily部分失敗契約

---

## Session 1 — 2026-02-27 早朝
### 設計書初版作成

**実施内容:**
- Sector Event Radar の初期設計議論
- アーキテクチャ決定: Claude API統合、イベント影響評価、マッピング自動調整、通知フロー
- 設計書ドキュメント生成

**背景:**
- ゆうきのMR-LS（Mean Reversion Long-Short）トレーディングシステムが稼働中
- 半導体セクターのイベント（CPI/FOMC/OPEX/決算/輸出規制等）を自動収集してカレンダーに載せたい
- 最終的にはイベント前後の株価影響を統計分析し、トレード判断の補助にする

---

## 経緯（このプロジェクトの位置づけ）

Sector Event Radar は、ゆうきのMR-LSトレーディングシステムの補助ツール。
MR-LS最終パラメータ: z2/K3/excl_1（日米両市場共通、holdout両市場通過の唯一のパラメータ）。
MR-LSが日次の統計的売買判断を行う一方、Sector Event Radarは「いつ何が起きるか」をカレンダーで可視化し、イベント前後のポジション管理を支援する。
