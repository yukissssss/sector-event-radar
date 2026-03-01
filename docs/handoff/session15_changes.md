# Session 15 変更サマリ — 2026-03-01

## 概要
工程3-P0: **shock ICS 0件問題の原因特定と恒久修正**。
GPTレビューの優先順位に従い、最優先のshock ICS問題を解決。

## 原因分析

### shock ICS 0件の根本原因: **カテゴリ誤分類**

Session 14のActionsログを精査:
- `inserted=1` → DBにはイベントが入っている
- `macro: 37`（前回36から+1）、`shock: 0`（変化なし）
- ICS all: 50（前回49から+1）

**結論**: Claudeが HBM4イベントを `category="macro"` と分類 → macroが+1、shockは0のまま。

コード上の原因箇所:
1. `claude_extract.py` L45: schemaで `"enum": ["macro", "bellwether", "flows", "shock"]` — Claudeが自由にカテゴリを選べる状態
2. `run_daily.py` L298: `events.extend(extracted)` — Claude返却のcategoryをそのままupsert
3. `_generate_ics_files` L383: `if e.category == category` — categoryでICSフィルタ

## 修正内容

### run_daily.py — 2箇所

**1. category="shock" 強制（恒久修正）**

`_collect_unscheduled()` 内、Claude抽出直後にcategoryを強制上書き:

```python
# RSS→Claude抽出パイプラインは設計上すべてshockカテゴリ。
# macro/bellwether/flowsは専用collectorが担当するため、
# Claudeの分類に依存せずコード側で強制する。
for ev in extracted:
    if ev.category != "shock":
        logger.info("Category override: '%s' %s → shock", ev.title[:50], ev.category)
        ev.category = "shock"
```

設計根拠:
- RSS→Claude抽出パイプラインは「unscheduled = shock」専用
- macro/bellwether/flowsはそれぞれ専用collector（BLS/BEA/FOMC、FMP、OPEX）が担当
- LLMの分類判断に依存しない方が堅牢

**2. _migrate_shock_category() — 既存データ修正**

DB init直後に実行。`event_sources.source_name = 'claude_extract'` かつ `category != 'shock'` のイベントを検出し、category + canonical_key を一括修正。

- canonical_key先頭の `{旧category}:` → `shock:` に置換
- event_sourcesテーブルのcanonical_keyも連動更新
- FMPやBLS等の他ソースイベントには影響なし（source_nameで判別）
- 対象イベントがなければno-op（毎回走っても安全）

## テスト追加

### test_shock_category_fix.py（6本）

**TestMigrateShockCategory（3本）**
1. `test_fixes_miscategorized_claude_event` — macro→shock修正、canonical_key更新
2. `test_does_not_touch_non_claude_events` — BLS等の他ソースmacroは変更なし
3. `test_no_op_when_already_shock` — 既にshockなら何もしない

**TestCategoryOverride（3本）**
4. `test_override_macro_to_shock` — macro→shock上書き確認
5. `test_shock_stays_shock` — shockはそのまま
6. `test_multiple_events_all_overridden` — 複数イベント全てshockに統一

## リポジトリへの配置
```
cp run_daily.py              → src/sector_event_radar/run_daily.py
cp test_shock_category_fix.py → tests/test_shock_category_fix.py
```

## push後の確認ポイント

1. `pytest` → 128本 + 6本 = 134本全通過
2. Actionsログで:
   - `Migration: 'HBM4 Validation...' category macro → shock` が1回出る（2回目以降はno-op）
   - `ICS shock: ... (>=1 events)` が出る ← **これが工程3-P0のDoD**
3. 新しいClaude抽出イベントで `Category override: ... macro → shock` ログが出る
4. iPhoneカレンダーのshock購読に `[SHOCK] HBM4 Validation...` が表示される

## 次のアクション（P1〜P2）

- **P1: iPhone表示QA** — `[MACRO]/[BW]/[FLOW]/[SHOCK]` プレフィックス + DESCRIPTION改行の実機確認
- **P2: Seen filter動作確認** — 2回目Actions実行で `already-processed` が出ることを確認
