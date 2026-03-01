# Sector Event Radar — プロジェクト進捗ログ

> セッションごとに先頭追記する累積型の経緯ログ。
> 「何をやったか」のみ記録。現在の状態は `chat_handoff_memo.md` を参照。

---

## Session 16 Part 2 — 2026-03-01

Task A（ログ診断）→ Task B（prefilterチューニング）→ Task C-1（SIA feedparser）→ Task C-2（Federal Register BIS）。

### Task A: ログ診断

今朝のActions実績分析。Stage A: 0/12 passed（threshold=4.0, dropped=12）。near-miss 5本全てscore=0.0（半導体無関係）。Claude API calls: 0。診断: (i)新着が半導体無関係 + (ii)キーワード狭すぎ（23語）の複合。

### Task B: prefilter Stage Aチューニング

キーワード23→55語（4段階Tier: Tier1=3.0, Tier2=2.5, Tier3=2.0, Tier4=1.5）。threshold 4.0→3.0。テスト8本追加。Actions手動実行: Stage A 0/12→**4/12通過**、Claude API 4 calls、extracted 4、inserted 1。

### validate now-7d ルール調査

GPT指示に沿いvalidate.py Rule 3を調査。選択肢A〜D比較。ICS窓(now-1d)との二重フィルタでvalidate緩和してもiPhoneに表示されないことを発見。**方針A（現状維持）でGPT承認**。rejected 3件は正常動作。

### Task C-1: SIA RSS復旧

feedparser>=6.0導入。rss.py改修（feedparser優先、ElementTreeフォールバック）。pyproject.toml依存追加。テスト7本。**結果**: feedparser正常動作だがSIA側XMLが根本的に壊れている（bozo error, 0 entries）。enabled放置（無害）。

### Task C-2: Federal Register BIS（GPT推奨案採用）

GPT分析: 旧BIS RSS死亡（リダイレクトでHTMLのみ）。SSL修復は無意味。Federal Register APIが一次ソース。

federal_register.py新規実装:
- Federal Register API（APIキー不要、JSON）からBIS規制文書を取得
- effective_on → 施行日イベント、comments_close_on → パブコメ締切イベント
- 構造化データから直接生成 → **LLM不要 = 幻覚ゼロ**
- publication_dateは過去90日を検索、イベント日が未来のもののみ生成

初回バグ修正: publication_date検索範囲が未来だったため0件 → 過去90日に修正。

**結果**: 18 documents fetched → **4 events created → 4 inserted**。ICS shock 1→**5**、ICS all 50→**54**。errors=0。

テスト11本追加。全テスト181本全通過。

変更ファイル:
- `src/sector_event_radar/collectors/rss.py` — feedparser統合
- `src/sector_event_radar/collectors/federal_register.py` — 新規
- `src/sector_event_radar/run_daily.py` — FR BISコレクター統合
- `config.yaml` — SIA enabled化、keywords 55語、threshold 3.0
- `pyproject.toml` — feedparser>=6.0依存追加
- `tests/test_rss_feedparser.py` (7本)
- `tests/test_federal_register.py` (11本)
- `tests/test_prefilter_tuning.py` (8本)

---

## Session 16 Part 1 — 2026-03-01

四半期イベント3ヶ月表示問題の恒久修正。GPTレビュー3回分（計12項目）全反映。**iPhone実機でDoD全達成**。

### 3層防御の実装

**層1: SYSTEM_PROMPTルール追加**: ルール10-12（四半期/月/半期→end_at=null, confidence=0.4-0.6）。ルール1に「with year are explicit」追記で矛盾解消。Tool Schema end_at/confidence descriptionも更新。

**層2: normalize_date_range()**: Claude抽出直後の防火扉。_is_quarter_like_range()で月初起点のレンジを検出しend_at=None矯正。パターンa（月初→月初、月差{1,3,6}）とパターンb（月初→月末、月差{0,2,5}）。

**層3: migrate_quarter_range()**: 既存DBの四半期レンジをNULL修正。claude_extractソースのみ対象。

### GPTレビュー3回分

**第1回**: 3層防御の構成提案。
**第2回（9/10）**: 判定精緻化、updated_at修正、ルール矛盾解消、誤爆テスト追加。
**第3回（運用哲学チェック）**: 末日型レンジ追加（本番データ6/30T23:59:59を捕捉）。

テスト: 17本新規。iPhone実機: 4/1ポイントイベント表示、4/2以降ノイズなし。

---

## Session 15 — 2026-03-01

P0: shock ICS 0件の恒久修正。override_shock_category() + migrate_shock_category()。テスト10本。P2: Seen filter確認（18本already-processed）。

---

## Session 14 — 2026-03-01

RSS拡充（EETimes/TrendForce追加）+ ICS見栄え改善。コスト3重ガード実装。shock初抽出成功（HBM4）。GPTレビュー2回。テスト128本。

---

## Session 13 — 2026-03-01

ANTHROPIC_API_KEY登録。shock Claude抽出パイプライン初稼働。ScoredArticleバグ修正。

---

## Session 12 — 2026-02-28

BLS 403解決。静的YAML（OMB公式PDF準拠）。macro 18→36 events。

---

## Session 11 — 2026-02-28

BLS/BEA/FOMC公式カレンダーでmacro実装。

---

## Session 10 — 2026-02-28

FMP v3 Legacy廃止→Stable API移行。bellwether復活。macro代替戦略確定。

---

## Session 9 — 2026-02-28

ICS 0件修正。GitHub Pages有効化。iPhoneカレンダー購読設定完了。

---

## Session 8 — 2026-02-27

GitHub Actions、DB永続化、TE/FMP collectors、FMP bellwether本番稼働。

---

## Session 7 以前

Phase 1実装、GPTハンドオフ、設計書、OPEXメカニズム教育、スケルトン精読、仕様書作成。
