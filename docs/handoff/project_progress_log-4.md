# Sector Event Radar — プロジェクト進捗ログ

> セッションごとに先頭追記する累積型の経緯ログ。
> 「何をやったか」のみ記録。現在の状態は `chat_handoff_memo.md` を参照。

---

## Session 14 — 2026-03-01

工程1（RSS拡充＋shockの実績作り）＋工程2（iPhoneでの見栄え改善）。GPTレビュー2回分（計7項目）全反映。**shock初イベント抽出成功**。

### 工程1: RSS拡充＋shock実績

**RSSソース拡充**: EE Times、TrendForce Semiconductors追加。SIA Press Releasesも追加したがXMLパースエラーで即disabled。BIS Press Releasesは`disabled: true`で無害化（SSLエラーログ消滅）。

**コスト安全策3重ガード**: (1)articlesテーブルで既出記事スキップ、(2)同一run内URL dedup（seen_in_run set）、(3)Claude投入記事数上限（max_articles_per_run: 10）。

**失敗時再試行**: `extract_succeeded`フラグで制御。Claude API例外時はseenにしない→翌日自動再試行。

**source_idユニーク化**: `claude:{url}#{hash(title:start_at)[:8]}`。1記事→複数イベント時のevent_sources主キー衝突を防止。

**観測ログ強化**: Seen filter（already-processed / duplicate-in-run分離）、Stage A/B通過率、LLM guard、Claude summary。

**shock初抽出**: TrendForce記事「HBM4 Validation Expected in 2Q26; Three Major Suppliers Pois」から1イベント抽出成功。`unscheduled: 1, inserted: 1`。

### 工程2: iPhoneでの見栄え改善

**ICSタイトル整形**: `CATEGORY_PREFIX`辞書で`[MACRO]`/`[BW]`/`[FLOW]`/`[SHOCK]`プレフィックス付与。

**DESCRIPTION定型化**: `_format_description()`でRisk/Confidence、Tags、Source URL、Evidenceを構造化表示。全イベントにDESCRIPTION必須出力。

**改行二重エスケープ修正**: GPT指摘。`"\\n".join`→`"\n".join`に修正。`_escape()`がICS仕様の`\n`に正しく変換。

**DB→ICSでsource_url/evidence取得**: `_list_events_from_db()`でevent_sourcesをLEFT JOIN。過去蓄積イベントの説明欄が実データで埋まるように。

### GPTレビュー反映

**第1回（8.8/10）**: A)同一run内URL dedup、B)content_hashコメント整合、C)失敗時seen回避、D)source_idユニーク化。

**第2回（9.2/10）**: A-2)ログカウンタ分離、B-2)INSERT OR IGNORE→ON CONFLICT DO UPDATE。ICS改行二重エスケープ修正。

### デプロイトラブル

- db.pyの`is_article_seen`/`mark_article_seen`がpush漏れ→ImportError→手動追加で解消
- モデル名`claude-haiku-4-5-20241022`が存在せず全10件404→`claude-haiku-4-5-20251001`に修正
- SIA RSS XMLパースエラー→`disabled: true`

### 最終Actionsログ

| カテゴリ | イベント数 | 変化 |
|---------|-----------|------|
| macro | 37 | +1（BEA新規マッチ？） |
| bellwether | 7 | 変化なし |
| flows | 6 | 変化なし |
| shock | 0（ICS） | inserted=1だがICSウィンドウ外の可能性 |
| **ICS all** | **50** | +1 |
| unscheduled | 1 | HBM4イベント |
| errors | 0 | BIS/SIA disabled化で完全消滅 |

変更: `config.py`, `config.yaml`, `db.py`, `run_daily.py`, `prefilter.py`, `claude_extract.py`, `ics.py`, `test_shock_pipeline.py`(新規3本), `test_ics_display.py`(新規12本)

---

## Session 13 — 2026-03-01

ANTHROPIC_API_KEY登録 → shock（Claude抽出）パイプライン稼働開始。全4カテゴリが稼働状態に到達。

**ScoredArticleバグ修正**: `run_daily.py`内で`article.title`→`article.article.title`等4箇所修正。ScoredArticleはArticleのラッパーなので`.article.`経由でアクセスが必要。

**Claude API課金**: 初回実行で「credit balance too low」→ $5チャージ → 再実行で成功。

**結果**: Claude: extracted 0 events from 6 articles（正常）。SemiEngineeringの技術解説記事は具体的イベント日がないため抽出対象外。輸出規制・決算サプライズ等のニュースが来ればshockイベントが生成される。

errors: 7→1に改善（BIS SSL証明書のみ残存）。ICS all: 49 events。

変更: `run_daily.py`(ScoredArticle accessor修正4箇所)

---

## Session 12 — 2026-02-28

BLS 403 Forbidden解決。Session 11の.icsがGitHub Actionsから403 → UA追加でも解消せず → GPT提案に沿いA(UA)→C(HTML fallback)→D(静的YAML)の順で実装。

**A: UA追加** → ❌ 403のまま。**C: HTMLパース fallback** → `fetch_bls_html_events()`実装、テスト13本追加 → push → HTMLページも403（bls.govがActionsのクラウドIPをドメインごとブロック）。**D: 静的YAML** → GPT相談でD採用決定。OMB公式PDF（ホワイトハウス発行）からCPI/NFP/PPI 2026年全36日程取得。`bls_mode: static`でHTTPを一切打たないモード実装。

結果: macro 18→36 events (+BLS 18)、ICS all 30→48 events。BLS向け403ログ完全消滅。テスト113本全通過。

変更: `official_calendars.py`(generate_bls_static_events+bls_mode分岐), `config.yaml`(bls_mode+bls_static 36日程), `config.py`(bls_mode/bls_static field), `test_bls_html_fallback.py`(新規→拡張30本), `test_official_calendars.py`(bls_mode=ics追加)

---

## Session 11 — 2026-02-28

BLS/BEA .ics + FOMC静的日程でmacroカテゴリ実装（FMP/TE有料の完全代替）。GPTレビュー5項目中4項目反映（#2 rulesキャッシュ化, #3 HHMM対応, #4 source_url設定, #5 matched=0警告）。#6 reconciliationは将来タスク。push → Actions確認 → BLS 403発覚（Session 12へ）。

変更: `official_calendars.py`(新規, BLS/BEA .icsパーサ+FOMC), `config.yaml`(macro_title_map 9→15パターン+fomc_dates 8回), `config.py`(fomc_datesフィールド), `run_daily.py`(official collector統合+空カテゴリ修正), `test_official_calendars.py`(新規45本)

---

## Session 10 — 2026-02-28

FMP macro collector実装 → GPTレビュー8項目(A〜H)全反映 → push → Secrets消失発覚(public化副作用) → 再登録 → FMP v3 Legacy廃止判明(2025-08-31〜) → Stable API移行 → bellwether復活(7 events) → FMP Economic Calendar有料限定(402)と確定 → GPT相談 → macro代替戦略確定: BLS(.ics)+BEA(.ics)+FOMC(公式) → BLS/BEA実データ取得確認済み

変更: `scheduled.py`(Stable API+macro collector+GPTレビュー), `run_daily.py`(macro呼び出し), `config.yaml`(FOMC拡張), `test_fmp_macro.py`(新規15本, 計47本全通過)

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
