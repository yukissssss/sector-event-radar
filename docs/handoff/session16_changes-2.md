# Session 16 変更サマリ — 2026-03-01

## 概要
四半期イベントの3ヶ月表示問題の恒久修正。GPT助言3回分を全反映した3層防御。
**DoD全達成**: iPhoneで4/1ポイントイベント確認済み。

## 原因分析

### 症状
TrendForce「HBM4 Validation Expected in 2Q26」→ Claude抽出で start=4/1, end=6/30T23:59:59。
iPhoneカレンダーに4/1〜6/30の3ヶ月間、毎日表示される。

### 根本原因
claude_extract.pyのSYSTEM_PROMPTに四半期/月/半期表現の扱いルールがなかった。
Claudeが「2Q26」を四半期の期間として解釈し、start_at/end_at両方を設定。

## 修正内容（3層防御）

### 層1: claude_extract.py — SYSTEM_PROMPTにルール10-12追加

- ルール1に「quarter/month/half-year with year are explicit time references」追記（矛盾解消）
- ルール10: 「Do NOT create multi-day range events for quarter/month/half-year only expressions」
- ルール11: 四半期 → start_at=初日T00:00:00Z, end_at=null, confidence=0.4-0.6
- ルール12: 月/半期 → 同上
- Tool Schema: end_at descriptionに「quarter/month/half-year は ALWAYS null」追記
- Tool Schema: confidence descriptionに「quarter/month → 0.4-0.6」追記

### 層2: run_daily.py — normalize_date_range() ポストプロセス

Claude抽出直後（override_shock_categoryの後）に呼び出す防火扉。
_is_quarter_like_range() で判定:
- パターンa: start_at.day==1 & end_at.day==1 & 月差{1,3,6}（月初→次の月初）
- パターンb: start_at.day==1 & end_at=月末日 & 月差{0,2,5}（月初→月末）
設計思想: ノイズ絶対殺す（思想A）。

### 層3: run_daily.py — migrate_quarter_range() DBマイグレーション

既存DBの「claude_extract」ソースでend_atがNOT NULLかつ四半期レンジのイベントをNULLに修正。
updated_atも更新。try/exceptで保護、冪等、公式macroは温存。

## GPTレビュー3回分の反映

### 第1回（修正案レビュー）
| 助言 | 対応 |
|------|------|
| 恒久対策A: SYSTEM_PROMPTルール追加 | ✅ ルール10-12 |
| 恒久対策B: DBマイグレーション | ✅ migrate_quarter_range() |
| オプション: post-processの防火扉 | ✅ normalize_date_range() |
| confidence下げ | ✅ ルール11-12 + Tool Schema |
| Tool Schema end_at説明追記 | ✅ |

### 第2回（9/10 コードレビュー）
| 指摘 | 対応 |
|------|------|
| A) _is_quarter_like_range が広すぎる | ✅ end_at.day==1 + 月差{1,3,6}に精緻化 |
| B) migration が updated_at を更新していない | ✅ UPDATE時にupdated_atも更新 |
| C) ルール1と11-12の矛盾 | ✅ ルール1に「with year are explicit」追記 |
| D) 誤爆テスト不足 | ✅ 2本追加 |

### 第3回（運用哲学チェック）
| 指摘 | 対応 |
|------|------|
| A) コメントと実装のズレ | ✅ 思想A「ノイズ絶対殺す」に統一 |
| B) 末日型レンジ（4/1→6/30）を拾えない | ✅ パターンb追加（monthrange末日判定 + 月差{0,2,5}）|
| C) docstringに旧ロジック残り | ✅ 「28〜190日」→月差判定に修正 |

**→ 末日型が実際の本番データ（end_at=6/30T23:59:59）だった。第3回で追加しなければ防火扉が空振りしていた。**

## テスト: test_quarter_range_fix.py（17本）

TestIsQuarterLikeRange（8本）:
1. test_quarter_range_detected — 4/1→7/1 四半期
2. test_month_range_detected — 3/1→4/1 月
3. test_short_range_not_detected — 1時間は対象外
4. test_non_first_day_not_detected — start day!=1は対象外
5. test_month_end_detected — 2/1→2/28 月末閉じ
6. test_quarter_end_detected — 4/1→6/30 四半期末閉じ
7. test_irregular_month_span_not_detected — 4ヶ月差は{1,3,6}外
8. test_mid_month_end_not_detected — 6/15は月末でも月初でもない

TestNormalizeDateRange（5本）:
9. test_quarter_range_nullified — Q2→None
10. test_month_range_nullified — March→None
11. test_half_year_range_nullified — H1→None
12. test_exact_date_preserved — 1時間イベント温存
13. test_no_end_at_noop — None→None

TestMigrateQuarterRange（4本）:
14. test_fixes_existing_quarter_range — DB内レンジ→NULL
15. test_does_not_touch_non_claude — 公式macro温存
16. test_noop_when_no_end_at — NULL→何もしない
17. test_idempotent — 2回実行で冪等性

## Actionsログ（実績）

```
Migration: 'HBM4 Validation Completion Expected' end_at 2026-06-30T23:59:59+00:00 → NULL (quarter range)
Migration: fixed 1 quarter-range events
ICS all: 50 events (macro 36, bellwether 7, flows 6, shock 1)
errors: []
upsert: inserted=0, merged=49
```

## iPhone実機確認

- 4/1: [SHOCK] HBM4 Validation Completion Expected — ポイントイベント ✅
- 4/2: 表示なし（ノイズ消滅）✅
- DESCRIPTION: Risk/Confidence/Tags/Source URL/Evidence 正常 ✅

## DoD — 全達成

- ✅ iPhoneで [SHOCK] HBM4 が4/1のポイントイベント（毎日表示されない）
- ✅ sector_events_shock.ics に該当イベントのDTEND行がない
- ✅ 既存DBの該当イベントのend_atがNULL
- ✅ pytest 155本全通過（138 + 17本）

## 変更ファイル

- `src/sector_event_radar/llm/claude_extract.py` — SYSTEM_PROMPT + Tool Schema
- `src/sector_event_radar/run_daily.py` — normalize_date_range() + migrate_quarter_range()
- `tests/test_quarter_range_fix.py` — 新規17本
- `docs/handoff/session16_changes.md` — 本ファイル
