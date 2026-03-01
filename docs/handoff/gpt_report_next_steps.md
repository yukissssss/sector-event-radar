# GPT相談: Session 16完了後の次ステップ

> このメモをGPTに貼ってレビュー+方針助言を依頼する。

---

## 現状サマリ

Sector Event Radar: 半導体セクターのイベントを自動収集 → iPhoneカレンダーに表示するツール。
GitHub Actions毎朝07:05 JST自動実行。Phase 1安定稼働中。

### 稼働実績（最新run 2026-03-01 21:13 JST）

| カテゴリ | イベント数 | ソース |
|---------|-----------|--------|
| macro | 36 | BLS static 18 + BEA .ics 14 + FOMC 4 |
| bellwether | 7 | FMP Stable API |
| flows | 6 | OPEX計算 |
| shock | 1+α | Claude Haiku抽出（最新runでinserted=1, rejected=3の過去イベント） |
| **合計** | **50+** | errors=0 |

### 直近の重要修正（Session 14-16）

1. **P0 shock ICS 0件**: Claude Haikuがcategory=macroと誤分類 → override_shock_category()で恒久修正
2. **P1 四半期3ヶ月表示**: 3層防御（SYSTEM_PROMPT + normalize_date_range + migrate_quarter_range）
3. **prefilter全DROP**: キーワード23→55語、threshold 4.0→3.0 → Stage A通過 0/12→**4/12**

### 運用哲学（絶対守る）
1. ノイズ絶対殺す（カレンダーが汚れるくらいならイベント減らす）
2. 幻覚ゼロ（本文に日時なければevents=[]）
3. 部分失敗OK（collectorが落ちてもICS生成まで到達）
4. コストガード（既出スキップ + run内dedup + max_articles=10）

### テスト: 163本全通過

---

## 相談1: rejected 3件の「now-7d」バリデーション

### 状況

TrendForce記事（2026-03-01公開）から抽出された3イベント:
- "Memory Price Outlook for 1Q26 – DRAM and NAND Flash Upgrades" → start_at=2026-01-01
- "PC DRAM Prices Expected to Double QoQ in 1Q26" → start_at=2026-01-01
- "Enterprise SSD Price Surge in 1Q26 Driven by CSP Demand" → start_at=2026-01-01

全てstart_at=2026-01-01（1Q26の初日）で、現在3/1から見て約60日前 → `start_at is older than now-7d for add/update` でrejected。

### 問題

これらは「1Q26の価格動向」という**四半期トレンド情報**。start_at=1/1は3層防御のルール11-12通り正しい（四半期→初日）。だが-7dルールで弾かれる。

### 質問

A) 現行の-7dルールはshockカテゴリにも適切か？macroのような定時発表と違い、shockは「過去の四半期に起きたことの報道」が多い。
B) shockだけ-30dや-90dに緩和する案はどうか？副作用は？
C) それとも「1Q26の記事は今さらカレンダーに入れても意味がない」と割り切るべきか？
D) 別のアプローチ: 四半期表現のstart_atを「四半期の初日」ではなく「記事の公開日」にする案はどうか？

---

## 相談2: disabled RSS（SIA / BIS）の復旧

### SIA Press Releases
- URL: https://www.semiconductors.org/feed/
- 症状: XMLパースエラーでdisabled
- 現行のrss.pyはElementTree直パース

**質問:**
A) feedparser導入（依存追加）vs ElementTreeサニタイズ（依存なし）、どちらが安定か？
B) SIAのRSSはAtom形式の可能性がある。namespace差分の吸収はどの程度の工数か？

### BIS Press Releases
- URL: https://www.bis.doc.gov/...
- 症状: GitHub ActionsからSSL証明書検証エラー
- verify=Falseは避けたい

**質問:**
C) GitHub Actions環境でのSSL証明書問題の一般的な解決策は？certifi更新？
D) BISの代替ソース候補はあるか？（連邦官報RSS、OFAC制裁リスト、Commerce Dept他）

---

## 相談3: Phase 2 impact.py の設計方針

### 目的
イベント前後の株価変動を統計分析し、「このイベントタイプは歴史的にどの程度の影響があるか」を定量化。

### 制約
- Phase 1（daily pipeline）を不安定化させない → 別コマンド/別スケジュール
- yfinance依存（レート制限あり）
- shockデータはまだ少ない（現時点で1-2件）。macro/bellwether/flowsは十分

### 最小スコープ案
1. DBからイベント日付リスト抽出ユーティリティ
2. yfinanceで対象ティッカーの日次リターン取得
3. イベント前後[-5d, +5d]のウィンドウでCAR(累積異常リターン)計算
4. JSON出力
5. CLIで実行: `python -m sector_event_radar.impact_cli --tickers NVDA,TSM --event-type opex`

### 質問
A) 最初に分析すべきイベントタイプはどれか？（OPEX/CPI/FOMC/bellwether決算）
B) ベンチマーク（異常リターン計算の基準）はSPY? SOX/SMH?
C) 統計的有意性の検定は何を使うべきか？（t検定? ブートストラップ?）
D) MR-LSの既存インフラ（yfinanceスナップショット等）と統合すべきか、完全分離か？

---

## 相談4: prefilterの継続改善

### 現状
55キーワード、threshold=3.0で4/12通過。しかし:
- Stage Bがsklearn未インストールのためスキップされている
- "eFPGA Hybrid Signal Processing"のような半導体製造寄りの記事はまだDROP

### 質問
A) sklearnをActions環境にインストールする価値はあるか？TF-IDFのStage Bは記事が4本程度なら効果薄い？
B) キーワードの追加ペースはどうすべきか？near-missログを見て週次で手動追加？それとも別のアプローチ？

---

## 優先順位の提案

現時点での優先順位案:
1. **観察** — 数日放置してshock蓄積を見る（コスト0）
2. **相談1のrejected対応** — 方針だけ決めて実装は小さい
3. **Task C: SIA/BIS復旧** — RSSソース増 → shock増加の確率UP
4. **Task D: Phase 2 impact.py** — shockが少ないうちはmacro/OPEXで始める

GPTの意見を聞きたい: この優先順位は妥当か？変更すべき点はあるか？

---

## 参考: 現行の主要コード

### validate.py のrejectedロジック（推定）
```python
# start_atがnow-7dより古いadd/updateは弾く
if event.start_at < now - timedelta(days=7) and event.action in ("add", "update"):
    reject(reason="start_at is older than now-7d for add/update")
```

### prefilter.py のスコアリング
```python
def _kw_score(text, keywords):
    score = sum(weight * min(3, text.lower().count(kw.lower())) for kw, weight in keywords.items())
    return score
```

### config.yaml キーワード（55語、4段階Tier）
```yaml
keywords:
  semiconductor: 3.0    # Tier 1
  foundry: 2.5          # Tier 2
  Intel: 2.0            # Tier 3
  DRAM: 1.5             # Tier 4
  # ... 計55語
prefilter:
  stage_a_threshold: 3.0
```
