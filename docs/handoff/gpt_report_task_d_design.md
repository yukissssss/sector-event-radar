# GPT経過報告 + Task D（Phase 2 impact.py）進め方の相談

---

## 経過報告: Task C 完了

### Task C-1: SIA RSS復旧
- feedparser>=6.0 を導入（pyproject.toml依存追加）
- rss.py改修: feedparser優先 → ElementTreeフォールバック
- **結果**: feedparser正常動作だがSIA側のXMLが根本的に壊れている（line 19, column 42に不正トークン）
- **判断**: enabled放置（0 articles fetched だが errors=0、パイプライン無害）
- テスト7本追加、全通過

### Task C-2: Federal Register BIS（GPT推奨案を採用）
- GPTの「上手い案その1」を実装: Federal Register APIからBIS規制イベントを構造化データで取得
- APIキー不要、LLM不要（幻覚ゼロ）
- publication_dateは過去90日を検索 → effective_on/comments_close_onが未来のものだけイベント化
- **結果**: 
  - 18 documents fetched → **4 events created → 4 inserted**
  - ICS shock: 1 → **5 events**
  - ICS all: 50 → **54 events**
  - errors: []
- テスト11本追加、全テスト181本全通過

### config.yaml の BIS Press Releases
- 旧RSS URL（bis.doc.gov）はまだ config.yaml に `disabled: true` で残っている
- Federal Registerで代替済みなので、旧BIS RSSエントリの削除は次セッションで整理予定

---

## 現在のパイプライン全体像

| ソース | タイプ | 状態 | イベント数 |
|--------|--------|------|-----------|
| BLS static | macro | ✅ | 18 |
| BEA ICS | macro | ✅ | 14 |
| FOMC | macro | ✅ | 4 |
| FMP earnings | bellwether | ✅ | 7 |
| OPEX | flows | ✅ | 6 |
| **Federal Register BIS** | **shock** | **✅ NEW** | **4** |
| SemiEngineering RSS | shock (via Claude) | ✅ | 10 fetched |
| EE Times RSS | shock (via Claude) | ✅ | 10 fetched |
| TrendForce RSS | shock (via Claude) | ✅ | 10 fetched |
| SIA RSS | shock (via Claude) | ⚠️ XML破損 | 0 fetched |
| BIS RSS (旧) | disabled | ❌ 死亡 | - |

合計: **54 ICSイベント**（macro 36 + bellwether 7 + flows 6 + shock 5）

---

## Task D: Phase 2 impact.py — 相談

### 目的
イベント前後の株価変動を統計化し、「このイベントタイプはどれくらい効くか」を定量化。

### 前回GPT指示（再掲）
> - `impact_cli` を新設して、DBからイベント日を取り、yfinanceで価格→[-5,+5] CAR を計算して JSON 出力する最小版を設計して。
> - 初手のイベントタイプ候補（OPEX/CPI/FOMC/決算）から「最小で価値が出る」順を提案して。
> - ベンチ（SPY/SMH/SOXなど）と検定（t/ブートストラップ）も、最初は "やり過ぎない最小" を提案。

### 制約
- Phase 1 を不安定化させない（別コマンド/別スケジュール）
- yfinance のレート制限配慮
- MR-LS既存インフラ（z2/K3/excl_1パラメータ）との将来統合を意識

### 現在DBにあるイベントデータ
- macro: CPI/NFP/PPI各6回 + BEA 14 + FOMC 4 = 計36件（日付が確定した公式データ）
- bellwether: 決算7件（NVDA/TSM/INTC/ASML/MU/AMAT/LRCX）
- flows: OPEX 6件
- shock: 5件（Micron fab買収1 + Federal Register BIS規制4）

### GPTへの質問

1. **最小MVP設計**: impact_cliの最小構成は？
   - CLI引数（--db, --category, --ticker/benchmark, --window）
   - 出力形式（JSON? CSV? 両方?）
   - ファイル構成（impact.py 1ファイル? それとも impact/ パッケージ?）

2. **初手イベントタイプの優先順位**: データ量と分析価値を考慮して、どのカテゴリから始めるべきか？
   - macro（CPI/NFP/PPI）: 各6回×過去データをyfinanceで遡及取得可能
   - bellwether（決算）: 7件だが、過去の決算日もyfinanceから遡及可能
   - flows（OPEX）: 毎月のパターン分析
   - shock: まだ5件で統計的に不十分

3. **ベンチマーク**: SPY（市場全体）vs SMH/SOXX（半導体セクター）
   - CARの計算: 個別銘柄のリターン − ベンチマークリターン？
   - それとも半導体ETFのイベント前後リターンだけで十分？

4. **統計検定の最小版**: 
   - 最初はt検定だけで十分？
   - サンプル数が少ない（6回のCPIなど）場合の扱いは？

5. **yfinanceレート制限への対処**:
   - Phase 1のMR-LSデータスナップショット（472 US / 212 JP）と共有可能？
   - それとも別途キャッシュ機構が必要？

6. **MR-LSとの将来統合**:
   - impact.pyの出力をMR-LSのシグナル生成に使うビジョンはあるか？
   - 今の段階で意識すべきインターフェースは？

### 求める回答
- 最小MVP設計（ファイル構成 + CLI + 出力形式）
- 実装順序（Step 1→2→3）
- 「やり過ぎない」ための明確なスコープ制限
