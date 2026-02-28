# Sector Event Radar — チャット引き継ぎメモ

> 新しいClaude/GPTチャットに貼り付けて文脈を復元する用。
> 詳細は project_progress_log.md と file_map_handoff.md を参照。

---

## プロジェクト概要

MR-LS（Mean Reversion Long-Short、日米株式）の補助ツール。
半導体セクターのイベント（CPI/FOMC/OPEX/決算/輸出規制等）を自動収集し、iPhoneカレンダーに表示する。
将来的にはイベント前後の株価影響を統計分析し、トレード判断を支援。

## リポジトリ

- GitHub: https://github.com/yukissssss/sector-event-radar (public)
- ローカル: ~/Documents/stock_analyzer/sector_event_radar/
- Python 3.13 / pydantic / SQLite / GitHub Actions

## 現在の状態（2026-02-28時点）

**稼働中:**
- GitHub Actions: 毎朝07:05 JST自動実行（DRY_RUN=false）
- FMP collector: bellwether 9銘柄の決算日取得 → DB → ICS
- OPEX: 6ヶ月分の第3金曜計算 + 祝日調整 → DB → ICS
- DB永続化: GitHub Releases方式（db-latestタグ）
- GitHub Pages: ICS配信中（`https://yukissssss.github.io/sector-event-radar/ics/`）
- iPhoneカレンダー購読: `sector_events_all.ics` を購読設定済み
- テスト: 22本全通過

**未稼働:**
- TE (Trading Economics): Freeプラン制限でAPI呼び出し不可。スキップ中
- RSS→Claude抽出: ANTHROPIC_API_KEY未登録
- FMP Economic Calendar (macro): 未実装（次の実装対象）

**スタブ（Phase 2以降）:**
- impact.py: イベント影響評価
- audit.py: 月次監査
- notify.py: 通知連携

## ファイル構成（要点のみ）

```
.github/workflows/daily.yml  ← Actions定義（毎朝自動実行）
src/sector_event_radar/
  run_daily.py       ← エントリポイント。3 collector → upsert → ICS。部分失敗設計
  collectors/
    scheduled.py     ← TE(スキップ中) + FMP bellwether(稼働中) + FMP macro(未実装)
    rss.py           ← RSSフィード取得
  llm/
    claude_extract.py ← Claude API抽出器（未稼働）
  canonical.py       ← canonical_key生成。shock系はsource_urlでhash
  config.py          ← AppConfig。bellwether_tickers等
  models.py          ← Event/Article Pydanticモデル
  db.py              ← SQLite upsert（冪等）
  ics.py             ← RFC5545 ICS生成。line folding+CRLF。0件カテゴリも空ICS出力
  flows.py           ← OPEX計算
  prefilter.py       ← RSS記事2段階フィルタ
  validate.py        ← イベント検証
  impact.py          ← スタブ
  audit.py           ← スタブ
  notify.py          ← スタブ
config.yaml          ← 本番設定（keywords/macro_title_map/RSS/bellwether）
docs/ics/            ← ICS出力先（Actions自動commit → GitHub Pagesで配信）
docs/handoff/        ← 引き継ぎ文書（以下4ファイル）
  project_progress_log.md   ← 累積型進捗ログ。セッションごとに先頭追記
  chat_handoff_memo.md      ← 本ファイル。新チャットにコピペで文脈復元用
  file_map_handoff.md       ← 全ファイルの役割・場所・実装状態一覧
  gpt_progress_report_*.md  ← GPTへの報告+相談（都度作成）
tests/               ← 22テスト（canonical/phase1/scheduled）
```

## GitHub Secrets

| Secret | 状態 |
|--------|------|
| FMP_API_KEY | ✅ 登録済み |
| TE_API_KEY | ❌ Freeプラン制限 |
| ANTHROPIC_API_KEY | ❌ 未登録 |

## 設計上の重要判断

- **4カテゴリ固定**: macro/bellwether/flows/shock。セクター差はsector_tagsで吸収
- **部分失敗設計**: collector間は独立try/except。どれが落ちてもICS生成まで到達
- **canonical_key**: `{category}:{entity}:{sub_type}:{YYYY-MM-DD}`。shock系は`short_hash(source_url)`
- **DB永続化**: GitHub Releases（Artifact=90日削除、Cache=不安定のため不採用）
- **0件ICS出力**: 全カテゴリのICSを常に出力（空でもVCALENDAR構造を維持）
- **リポジトリpublic化**: GitHub Pages Free plan利用のため。APIキーはSecretsで安全

## GPT回答済みの方針

- **Q1（macro指標）**: FMP Economic Calendar (`/v3/economic_calendar`) を第一候補。カバーできない分だけ静的YAMLで補完
- **Q2（優先順位）**: Pages ✅完了 → macro代替実装 → Claude抽出オン

## 次のアクション

1. **FMP Economic Calendar実装** — `scheduled.py` に `fetch_fmp_macro_events()` 追加。既存の `macro_title_map` でCPI/FOMC/NFP/PCE等をフィルタ → macroカテゴリ有効化
2. **ANTHROPIC_API_KEY登録 + RSSフィード追加** → Claude抽出E2Eテスト → shockカテゴリ有効化
3. **Phase 2**: impact.py実装（イベント影響評価）

## 関連プロジェクト

MR-LS最終パラメータ: z2/K3/excl_1（日米両市場共通、holdout両市場通過の唯一のパラメータ）
