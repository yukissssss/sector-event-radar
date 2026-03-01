# Sector Event Radar — プロジェクト進捗ログ

> セッションごとに先頭追記する累積型の経緯ログ。
> 「何をやったか」のみ記録。現在の状態は `chat_handoff_memo.md` を参照。

---

## Session 16 — 2026-03-01

四半期イベント3ヶ月表示問題の恒久修正。GPTレビュー3回分（計12項目）全反映。**iPhone実機でDoD全達成**。

### 3層防御の実装

**層1: SYSTEM_PROMPTルール追加**: ルール10-12（四半期/月/半期→end_at=null, confidence=0.4-0.6）。ルール1に「with year are explicit」追記で矛盾解消。Tool Schema end_at/confidence descriptionも更新。

**層2: normalize_date_range()**: Claude抽出直後の防火扉。_is_quarter_like_range()で月初起点のレンジを検出しend_at=None矯正。パターンa（月初→月初、月差{1,3,6}）とパターンb（月初→月末、月差{0,2,5}）の2パターン。

**層3: migrate_quarter_range()**: 既存DBの四半期レンジをNULL修正。claude_extractソースのみ対象、updated_at更新、try/except保護、冪等。

### GPTレビュー3回分

**第1回**: 3層防御の構成提案。SYSTEM_PROMPT + migration + post-process + confidence + Tool Schema。

**第2回（9/10）**: A)判定が広すぎる→月差精緻化、B)updated_at未更新→修正、C)ルール矛盾→追記、D)誤爆テスト→2本追加。

**第3回（運用哲学チェック）**: A)コメントズレ→思想A統一、B)末日型レンジ→パターンb追加（monthrange）、C)docstring旧表現→修正。**末日型が実際の本番データ（6/30T23:59:59）だった — 第3回なしでは防火扉空振り。**

### Actionsログ（実績）

Migration: 'HBM4...' end_at 2026-06-30T23:59:59 → NULL。ICS shock: 1 events。errors: 0。

### iPhone実機確認

4/1にポイントイベント表示。4/2以降に出ない（ノイズ消滅）。DESCRIPTION正常。

テスト: 155本全通過（138 + 17本新規）。

変更: `claude_extract.py`(SYSTEM_PROMPT+Tool Schema), `run_daily.py`(normalize+migrate), `test_quarter_range_fix.py`(新規17本)

---

## Session 15 — 2026-03-01

工程3-P0: shock ICS 0件問題の恒久修正。P0/P1/P2全確認完了。

### P0: shock category強制（恒久修正）

**根本原因特定**: Session 14でClaude HaikuがHBM4イベントをcategory="macro"と分類 → macroが+1、shockは0のまま。ICSフィルタはevents.categoryで判定するためshockに1件も出なかった。

**override_shock_category()**: Claude抽出直後にcategory=shockを強制する公開関数。

**migrate_shock_category()**: 既存DBの誤分類をcategoryのみ更新。canonical_keyは変更しない安全設計。try/exceptで保護。

**テスト10本**: Override 4本 + Migrate 6本（冪等性・混在ソース・空リスト等カバー）。

### P0確認: Actionsログ

`ICS shock: 1 events` — P0 DoD達成。Migration no-op（前回runで修正済み）。errors: 0。

### P1: iPhone実機表示QA（→Session 16で完了）

[SHOCK]プレフィックス表示OK、DESCRIPTION改行OK、URL表示OK。ただし3ヶ月レンジ表示問題を発見。

### P2: Seen filter確認

`18 already-processed, 0 duplicate-in-run` — コスト3重ガード機能確認。prefilter通過0 → Claude API呼び出し0回。

テスト: 138本全通過（128 + 10本新規）。

変更: `run_daily.py`(override+migrate), `test_shock_category_fix.py`(新規10本)

---

## Session 14 — 2026-03-01

工程1（RSS拡充＋shockの実績作り）＋工程2（iPhoneでの見栄え改善）。GPTレビュー2回分（計7項目）全反映。**shock初イベント抽出成功**。

### 工程1: RSS拡充＋shock実績

**RSSソース拡充**: EE Times、TrendForce Semiconductors追加。SIA Press Releasesも追加したがXMLパースエラーで即disabled。BIS Press Releasesは`disabled: true`で無害化。

**コスト安全策3重ガード**: (1)articlesテーブルで既出記事スキップ、(2)同一run内URL dedup、(3)Claude投入記事数上限（max_articles_per_run: 10）。

**失敗時再試行**: `extract_succeeded`フラグ。API例外時はseenにしない→翌日自動再試行。

**source_idユニーク化**: `claude:{url}#{hash(title:start_at)[:8]}`。1記事→複数イベント時のPK衝突防止。

**shock初抽出**: TrendForce記事「HBM4 Validation Expected in 2Q26」から1イベント抽出成功。

### 工程2: iPhoneでの見栄え改善

**ICSタイトル整形**: `[MACRO]`/`[BW]`/`[FLOW]`/`[SHOCK]`プレフィックス付与。
**DESCRIPTION定型化**: Risk/Confidence、Tags、Source URL、Evidence構造化表示。
**改行二重エスケープ修正**: GPT指摘。`"\\n".join`→`"\n".join`。
**DB→ICSでsource_url/evidence取得**: event_sourcesをLEFT JOIN。

### GPTレビュー反映

**第1回（8.8/10）**: URL dedup、content_hashコメント、失敗時seen回避、source_idユニーク化。
**第2回（9.2/10）**: ログカウンタ分離、ON CONFLICT DO UPDATE、ICS改行修正。

テスト: 128本全通過（113 + shock回帰3本 + ICS表示12本）。

変更: `config.py`, `config.yaml`, `db.py`, `run_daily.py`, `prefilter.py`, `claude_extract.py`, `ics.py`, `test_shock_pipeline.py`(3本), `test_ics_display.py`(12本)

---

## Session 13 — 2026-03-01

ANTHROPIC_API_KEY登録 → shock（Claude抽出）パイプライン稼働開始。全4カテゴリが稼働状態に到達。

**ScoredArticleバグ修正**: `article.title`→`article.article.title`等4箇所修正。

**Claude API課金**: 初回「credit balance too low」→ $5チャージ → 成功。

**結果**: Claude: extracted 0 events from 6 articles（正常）。技術解説記事のため抽出対象外。

変更: `run_daily.py`(ScoredArticle accessor修正4箇所)

---

## Session 12 — 2026-02-28

BLS 403 Forbidden解決。UA追加→❌ → HTMLパース fallback→❌（クラウドIP全ブロック）→ 静的YAML（OMB公式PDF準拠）→✅。

`bls_mode: static`でHTTPを一切打たないモード。CPI/NFP/PPI 2026年全36日程。macro 18→36 events。テスト113本全通過。

変更: `official_calendars.py`, `config.yaml`, `config.py`, `test_bls_html_fallback.py`(30本), `test_official_calendars.py`

---

## Session 11 — 2026-02-28

BLS/BEA .ics + FOMC静的日程でmacroカテゴリ実装（FMP/TE有料の完全代替）。GPTレビュー5項目中4項目反映。BLS 403発覚（Session 12へ）。

変更: `official_calendars.py`(新規), `config.yaml`, `config.py`, `run_daily.py`, `test_official_calendars.py`(45本)

---

## Session 10 — 2026-02-28

FMP macro collector実装 → GPTレビュー8項目全反映 → FMP v3 Legacy廃止判明 → Stable API移行 → bellwether復活(7 events) → FMP Economic Calendar有料限定(402)確定 → macro代替戦略確定: BLS+BEA+FOMC

変更: `scheduled.py`, `run_daily.py`, `config.yaml`, `test_fmp_macro.py`(15本)

---

## Session 9 — 2026-02-28

ICS 0件問題修正(`if not cat_events: continue`削除) → GitHub Pages有効化(private不可→public化) → iPhoneカレンダー購読設定完了(OPEX表示確認)

変更: `run_daily.py`(2行削除)

---

## Session 8 — 2026-02-27 夜

GitHub privateリポジトリ作成 → Actions dry-run緑 → DB永続化(Releases方式) → TE/FMP collectors実装(22テスト全通過) → FMP bellwether本番稼働 → TE Freeプラン制限でスキップ

変更: `scheduled.py`, `config.py`, `run_daily.py`, `config.yaml`, `test_scheduled.py`, `daily.yml`, `.gitignore`

---

## Session 7 — 2026-02-27 午後

Phase 1実装完了。GPT提案順(③→②→④→⑤→⑥)で全修正。canonical.py shock hash修正, claude_extract.py書き直し, run_daily.py部分失敗設計, ics.py RFC5545 folding, テスト15本全通過。ローカル環境構築完了。

---

## Session 6 — 2026-02-27 午後

GPT Handoff準備。10章ハンドオフメモ+設計書+スケルトンzipをGPTに送信。着手順決定。

---

## Session 5 — 2026-02-27 午前〜午後

Phase 1範囲確定。OPEXメカニズム教育セッション(デルタヘッジ, Max Pain, オプション基礎)。

---

## Session 4 — 2026-02-27 午前

設計書v3完成。4カテゴリ(macro/bellwether/flows/shock)固定の設計判断。

---

## Session 3 — 2026-02-27 午前

GPTスケルトン22ファイル精読。流用OK/修正必要を分類。バグ5件特定。

---

## Session 2 — 2026-02-27 早朝

GPT peer review用仕様書作成。GPT回答: 82/100, 優先修正3点(canonical衝突, ticker alias, 部分失敗)。

---

## Session 1 — 2026-02-27 早朝

設計書初版。MR-LS補助ツールとしてのSector Event Radar構想。
