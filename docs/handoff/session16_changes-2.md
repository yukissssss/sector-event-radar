# Session 16 変更サマリ — 2026-03-01

## 概要
四半期イベントの3ヶ月表示問題の恒久修正。GPT助言に沿った3層防御。

## 原因分析

### 症状
TrendForce「HBM4 Validation Expected in 2Q26」→ Claude抽出で start=4/1, end=7/1。
iPhoneカレンダーに4/1〜7/1の3ヶ月間、毎日表示される。

### 根本原因
claude_extract.pyのSYSTEM_PROMPTに四半期/月/半期表現の扱いルールがなかった。
Claudeが「2Q26」を四半期の期間（4/1〜7/1）として解釈し、start_at/end_at両方を設定。

## 修正内容（3層防御）

### 層1: claude_extract.py — SYSTEM_PROMPTにルール10-12追加

- ルール10: 「Do NOT create multi-day range events for quarter/month/half-year only expressions」
- ルール11: 四半期 → start_at=初日T00:00:00Z, end_at=null, confidence=0.4-0.6
- ルール12: 月/半期 → 同上
- Tool Schema: end_at descriptionに「quarter/month/half-year は ALWAYS null」追記
- Tool Schema: confidence descriptionに「quarter/month → 0.4-0.6」追記

### 層2: run_daily.py — normalize_date_range() ポストプロセス

Claude抽出直後（override_shock_categoryの後）に呼び出す防火扉。
start_atが月初日かつend_atとの差が28〜190日のイベントをend_at=Noneに矯正。
_is_quarter_like_range() で判定。

### 層3: run_daily.py — migrate_quarter_range() DBマイグレーション

既存DBの「claude_extract」ソースでend_atがNOT NULLかつ四半期レンジのイベントをNULLに修正。
migrate_shock_category()と同じ流儀: try/exceptで保護、冪等、公式macroは温存。

## GPT助言の採用状況

| 助言 | 対応 |
|------|------|
| 恒久対策A: SYSTEM_PROMPTルール追加 | ✅ ルール10-12 |
| 恒久対策B: DBマイグレーション | ✅ migrate_quarter_range() |
| オプション: post-processの防火扉 | ✅ normalize_date_range() |
| confidence下げ | ✅ ルール11-12 + Tool Schema description |
| Tool Schema end_at説明追記 | ✅ |

## GPT第2回レビュー反映（9/10）

| 指摘 | 対応 |
|------|------|
| A) _is_quarter_like_range が広すぎる | ✅ end_at.day==1 + 月差{1,3,6}に精緻化。_QUARTER_STARTS死に定数削除 |
| B) migration が updated_at を更新していない | ✅ UPDATE時にupdated_atも更新 |
| C) ルール1と11-12の矛盾 | ✅ ルール1に「quarter/month/half-year with year are explicit」追記 |
| D) 誤爆テスト不足 | ✅ end_at.day!=1ケース + 4ヶ月差ケースの2本追加（計15本）|

## テスト追加

### test_quarter_range_fix.py（15本）

TestIsQuarterLikeRange（6本）:
1. test_quarter_range_detected — 91日=四半期
2. test_month_range_detected — 31日=月
3. test_short_range_not_detected — 1時間は対象外
4. test_non_first_day_not_detected — day!=1は対象外
5. test_end_not_first_day_not_detected — end_at.day!=1は対象外（2月末）
6. test_irregular_month_span_not_detected — 4ヶ月差は{1,3,6}外

TestNormalizeDateRange（5本）:
5. test_quarter_range_nullified — Q2→None
6. test_month_range_nullified — March→None
7. test_half_year_range_nullified — H1→None
8. test_exact_date_preserved — 1時間イベント温存
9. test_no_end_at_noop — None→None

TestMigrateQuarterRange（4本）:
10. test_fixes_existing_quarter_range — DB内レンジ→NULL
11. test_does_not_touch_non_claude — 公式macro温存
12. test_noop_when_no_end_at — NULL→何もしない
13. test_idempotent — 2回実行で冪等性

## リポジトリへの配置

```
cp claude_extract.py          → src/sector_event_radar/llm/claude_extract.py
cp run_daily.py               → src/sector_event_radar/run_daily.py
cp test_quarter_range_fix.py  → tests/test_quarter_range_fix.py
cp session16_changes.md       → docs/handoff/session16_changes.md
```

## push後の確認ポイント

1. pytest → 138本 + 15本 = 153本全通過
2. Actionsログで:
   - `Migration: 'HBM4 ...' end_at ... → NULL (quarter range, key=...)` が1回出る
   - 2回目以降はno-op
   - ICS shock: 1 events（変化なし、ただしDTENDなし）
3. iPhoneカレンダーで [SHOCK] HBM4 が4/1の1回だけ表示（4/2以降に出ない）

## DoD

- iPhoneで [SHOCK] HBM4 が4/1のポイントイベント（毎日表示されない）
- sector_events_shock.ics に該当イベントのDTEND行がない
- 既存DBの該当イベントのend_atがNULL
