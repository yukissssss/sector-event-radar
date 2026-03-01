# Session 14 変更サマリ — 2026-03-01

## 概要
工程1（RSS拡充＋shockの実績作り）＋工程2（iPhoneでの見栄え改善）。
BISノイズ除去、EE Times追加、コスト安全策、観測ログ強化、ICSタイトル/DESCRIPTION整形。
GPTレビュー4項目(A〜D)を全反映済み。

## 変更ファイル一覧

### config.py
- `RssSource` に `disabled: bool = False` フィールド追加
- `LlmConfig` クラス新規追加（`max_articles_per_run`, `model`）
- `AppConfig` に `llm: LlmConfig` フィールド追加

### config.yaml
- BIS Press Releases: `disabled: true` 追加 → 毎日のSSLエラーログ消滅
- EE Times (`https://www.eetimes.com/feed/`) 追加 — 半導体専門、イベント性高い記事が多い
- TrendForce Semiconductors (`https://www.trendforce.com/feed/Semiconductors.html`) 追加 — 量産時期・四半期業績・価格改定など日付付き情報が豊富
- SIA Press Releases (`https://www.semiconductors.org/feed/`) 追加 — 業界団体公式。月次売上・政策声明に明示日付
- `llm:` セクション新規追加（`max_articles_per_run: 10`, `model: claude-haiku-4-5-20241022`）

### db.py
- `is_article_seen(conn, url)` 関数追加 — 既存articlesテーブルを活用
- `mark_article_seen(conn, url, content_hash, relevance_score)` 関数追加

### ics.py（工程2: iPhoneでの見栄え改善）
- **タイトル整形**: `CATEGORY_PREFIX`辞書で`[MACRO] US CPI`, `[BW] NVDA Earnings`, `[FLOW] OPEX`, `[SHOCK] Export Controls`形式に統一
- **DESCRIPTION定型化**: `_format_description()`で`Risk: 50/100 | Confidence: 0.80` / `Tags:` / `Source:` / `Evidence:` を構造化表示
- 全イベントにDESCRIPTIONを必ず出力（evidence="from database"の場合はRisk/Tags/Sourceのみ）
- **[GPT指摘] 改行二重エスケープ修正**: `"\\n".join` → `"\n".join`。`_escape()`がICS仕様の`\n`に正しく変換する

### run_daily.py（工程1 + 工程2）
- `_collect_unscheduled()` にconn引数追加（seen_articlesチェック用）
- `_list_events_from_db()`: event_sourcesテーブルをLEFT JOINしてsource_url/evidenceを取得。ICSのDESCRIPTIONとURLが実データで埋まるように
- **disabled対応**: `src.disabled` なRSSソースをスキップ（ログ出力）
- **既出記事フィルタ**: RSS取得後、articlesテーブルで既出チェック → 既処理記事をスキップ
- **[A] 同一run内URL dedup**: `seen_in_run` setで複数RSSソースからの重複URLを排除。二重課金防止
- **LLM上限**: `cfg.llm.max_articles_per_run` で1回あたりのClaude API呼び出し数を制限
- **[B] content_hashコメント整合**: 現状URL単位で既出判定（コスト優先）であることをdocstringに明記
- **[C] 失敗時はseenにしない**: `extract_succeeded`フラグで制御。Claude APIが正常応答した場合のみmark_seen。API例外時は翌日自動再試行される
- **観測ログ強化**: Seen filter / LLM guard / Claude extract / Claude summary

### claude_extract.py
- **[D] source_idイベント単位ユニーク化**: `claude:{url}#{hash(title:start_at)[:8]}`
  - 1記事→複数イベント時にevent_sources主キー(source_name, source_id)衝突で最後のイベントだけ残る事故を防止
- `hashlib` import追加

### prefilter.py
- `logger` 追加（`logging.getLogger(__name__)`）
- Stage A/Bの観測ログ追加

## リポジトリへの配置
```
cp config.py            → src/sector_event_radar/config.py
cp config.yaml          → config.yaml (ルート)
cp db.py                → src/sector_event_radar/db.py
cp ics.py               → src/sector_event_radar/ics.py
cp run_daily.py         → src/sector_event_radar/run_daily.py
cp prefilter.py         → src/sector_event_radar/prefilter.py
cp claude_extract.py    → src/sector_event_radar/llm/claude_extract.py
cp test_shock_pipeline.py → tests/test_shock_pipeline.py
cp test_ics_display.py    → tests/test_ics_display.py
```

## GPTレビュー反映状況（初回 + 第2回）
| 指摘 | 対応 |
|------|------|
| A) 同一run内URL重複で二重課金 | ✅ `seen_in_run` setでdedup |
| A-2) seen_countが重複と既出を混同 | ✅ `skipped_db_seen` / `skipped_dup_in_run` に分離 |
| B) content_hash作ってるのに判定に使ってない | ✅ コメント整合（コスト優先でURL判定を明記） |
| B-2) INSERT OR IGNOREでメタデータ更新されない | ✅ ON CONFLICT DO UPDATEに変更 |
| C) 失敗時もseenにすると取りこぼし | ✅ 成功時のみmark_seen |
| D) source_idが記事URL固定でevent_sources上書き | ✅ hash(title:start_at)でユニーク化 |
| 追加テスト3本 | ✅ test_shock_pipeline.py 新規作成 |

## 追加テスト
### test_shock_pipeline.py → tests/test_shock_pipeline.py（3本）
1. `test_dedup_same_url_in_run` — 同一URL2回入力で1回だけ処理される
2. `test_failed_extraction_not_marked_seen` — 失敗記事はseenにならず翌日再試行可能
3. `test_multi_event_from_single_article_unique_source_ids` — 1記事2イベントでevent_sources2行

### test_ics_display.py → tests/test_ics_display.py（9本）
1. `test_summary_has_category_prefix` ×4 — 各カテゴリのプレフィックス確認
2. `test_summary_prefix_in_ics_output` — ICS全体出力でSUMMARY行にプレフィックス
3. `test_description_always_present` — evidence="from database"でもDESCRIPTION出力
4. `test_description_contains_risk_and_confidence` — Risk/Confidence表示
5. `test_description_contains_tags` — Tags表示
6. `test_description_contains_source_url` — Source URL表示
7. `test_description_contains_evidence` — Evidence表示
8. `test_description_newline_escape_not_doubled` — 改行が二重エスケープしない
9. `test_ics_description_line_has_correct_newlines` — ICS出力全体で正しい改行

## push後の確認ポイント
1. `pytest` → 113本 + 3本 + 12本 = 128本全通過（test_ics_displayのparametrize×4含む）
2. Actions実行 → BISが `SKIPPED (disabled)` と出る
3. EE Times / TrendForce / SIA がそれぞれ `X articles fetched` と出る
   - 403/SSL等で失敗するソースがあれば `disabled: true` に戻す
4. `Seen filter:` ログで `already-processed` と `duplicate-in-run` が分離表示
5. 2回目以降のActionsで同じ記事がスキップされる
6. 失敗記事は翌日再試行される
7. shockイベントが1件でも出れば工程1のDoD達成
8. iPhoneカレンダーで `[MACRO] US CPI` `[BW] NVDA Earnings` 等のプレフィックス表示を確認（工程2 DoD）
9. イベント詳細タップでRisk/Tags/Source/Evidenceが構造化表示・改行が正しいこと
