# GPT相談: 四半期イベントの3ヶ月表示問題

> このメモをGPTに貼ってレビュー+修正案を依頼する。

---

## 背景

Sector Event Radar: 半導体セクターのイベントを自動収集 → iPhoneカレンダーに表示するツール。
RSS記事 → Claude Haiku 4.5で構造化イベント抽出 → ICS配信 → iPhone購読。

## 発生した問題

### 症状

TrendForce記事「HBM4 Validation Expected in 2Q26」から抽出されたイベント:
- start_at: 2026-04-01T09:00:00（2Q26の初日）
- end_at: 2026-07-01T08:59:00（2Q26の最終日翌日）

iPhoneカレンダーで4/1〜7/1の**3ヶ月間**、毎日このイベントが表示される。
カレンダーがノイズだらけになり、他のイベントが埋もれる。

### 根本原因

claude_extract.pyのSYSTEM_PROMPTに「四半期/月のみの日付表現の扱い」ルールがない。
Claudeが「2Q26」を素直に四半期の期間（4/1〜7/1）として解釈し、start_at/end_atの両方を設定した。

### 望ましい動作

「2Q26」「Q2 2026」「2026年第2四半期」等 → start_at=2026-04-01T00:00:00Z, end_at=null
iPhoneカレンダーでは4/1にポイントイベントとして1日だけ表示。

同様に「March 2026」等の月表現 → start_at=2026-03-01T00:00:00Z, end_at=null

## 現行コード（修正対象）

### claude_extract.py — SYSTEM_PROMPT（現行・抜粋）

```
RULES (strictly follow all):
1. Extract ONLY events with an EXPLICIT date or datetime in the article text.
2. If no explicit date/time is found, you MUST return events=[].
3. Vague expressions like "soon", "later this year", "in the coming weeks" are NOT explicit dates. Return events=[] for these.
4. The "evidence" field MUST be a verbatim quote from the article that contains the date/time.
5. Do NOT predict, guess, or infer dates that are not stated in the text.
6. Category rules: ...
7. risk_score: ...
8. Use ISO8601 format with timezone for start_at. If only a date is given (no time), use T00:00:00Z.
9. source_name and source_url will be added by the caller. Do not include them.
```

### Tool Schema（現行・start_at/end_at部分）

```json
"start_at": {
    "type": "string",
    "description": "ISO8601 datetime with timezone, e.g. 2026-03-12T08:30:00-05:00"
},
"end_at": {
    "type": ["string", "null"],
    "description": "ISO8601 end time or null"
}
```

## 修正案（叩き台）

SYSTEM_PROMPTにルール追加:

```
10. For quarter-only expressions (e.g. "2Q26", "Q2 2026", "second quarter of 2026"):
    - start_at = first day of the quarter at T00:00:00Z (e.g. 2026-04-01T00:00:00Z for Q2)
    - end_at = null (do NOT set end_at to the last day of the quarter)
    - These are point-in-time events, not ranges.
11. For month-only expressions (e.g. "March 2026"):
    - start_at = first day of the month at T00:00:00Z
    - end_at = null
12. For year-half expressions (e.g. "1H26", "second half of 2026"):
    - start_at = first day of the half at T00:00:00Z (H1=Jan 1, H2=Jul 1)
    - end_at = null
```

## GPTへの質問

1. **SYSTEM_PROMPTの修正案は妥当か？** 抜け漏れや副作用はあるか？
2. **既存DBのHBM4イベント修正方法**: end_atをNULLに更新するmigrationを入れるか、放置で翌日以降のrunでmerge時に自動修正されるか？
3. **Tool Schemaのend_at descriptionも変更すべきか？** 例: `"ISO8601 end time or null. For quarter/month/half-year expressions, always use null."`
4. **confidence値の扱い**: 四半期のみの日付は具体的な日付より不確実。confidence=0.5等に下げるルールを追加すべきか？
5. **他に見落としている日付表現パターンはあるか？** （"by Q2 2026", "starting Q2", "end of Q1"等の変形）

## 参考: 現行の全ファイル構成

```
src/sector_event_radar/
├── llm/claude_extract.py     ← 今回の修正対象（SYSTEM_PROMPT + Tool Schema）
├── run_daily.py              ← override_shock_category()でcategory強制済み
├── ics.py                    ← end_at=null時はDTENDを出力しない（既に対応済み）
├── db.py                     ← upsert_event: start/end変更でupdateトリガー
└── models.py                 ← Event: end_at: Optional[datetime] = None
```

ics.pyはend_at=nullの場合DTENDを出力しないので、claude_extract側でnullにするだけでiPhone表示は1日ポイントイベントになる。DB/ICS側の変更は不要のはず。
