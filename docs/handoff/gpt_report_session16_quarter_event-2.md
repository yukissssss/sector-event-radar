# GPT相談: 四半期イベントの3ヶ月表示問題 — 解決済み

> Session 16で解決。このメモは経緯記録として保存。

---

## 問題

TrendForce「HBM4 Validation Expected in 2Q26」→ Claude抽出で start=4/1, end=6/30T23:59:59。
iPhoneカレンダーに3ヶ月間毎日表示されるノイズ問題。

## GPTに依頼した内容

1. SYSTEM_PROMPTの修正案レビュー
2. 既存DBのHBM4イベント修正方法
3. Tool Schema更新の要否
4. confidence値の扱い
5. 見落とし日付表現パターン

## GPT回答サマリ（3回）

### 第1回: 3層防御の提案
- 層1: SYSTEM_PROMPTルール10-12（四半期/月/半期→end_at=null）
- 層2: post-process防火扉（normalize_date_range）
- 層3: DBマイグレーション（migrate_quarter_range）
- confidence 0.4-0.6に下げ
- Tool Schema end_at descriptionも更新

### 第2回: コードレビュー（9/10）
- A) _is_quarter_like_range判定の精緻化
- B) migration updated_at更新
- C) ルール1と11-12の矛盾解消
- D) 誤爆テスト追加

### 第3回: 運用哲学チェック
- A) 設計思想の明示（思想A: ノイズ絶対殺す）
- B) 末日型レンジ検出（monthrange）— **実際の本番データが末日型だった**
- C) docstring整合

## 結果

GPT助言3回分（計12項目）を全反映。3層防御でDoD全達成。
実際のend_atが6/30T23:59:59（末日型）だったため、第3回の末日判定追加が決定打になった。
