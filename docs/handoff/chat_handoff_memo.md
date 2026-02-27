# Sector Event Radar — チャット引き継ぎメモ

> 新しいClaude/GPTチャットに貼り付けて文脈を復元する用。
> 詳細は project_progress_log.md と file_map_handoff.md を参照。

---

## プロジェクト概要

MR-LS（Mean Reversion Long-Short、日米株式）の補助ツール。
半導体セクターのイベント（CPI/FOMC/OPEX/決算/輸出規制等）を自動収集し、iPhoneカレンダーに表示する。
将来的にはイベント前後の株価影響を統計分析し、トレード判断を支援。

## リポジトリ

- GitHub: https://github.com/yukissssss/sector-event-radar (private)
- ローカル: ~/Documents/stock_analyzer/sector_event_radar/
- Python 3.13 / pydantic / SQLite / GitHub Actions

## 現在の状態（2026-02-27時点）

**稼働中:**
- GitHub Actions: 毎朝07:05 JST自動実行（DRY_RUN=false）
- FMP collector: bellwether 9銘柄の決算日取得 → DB → ICS
- OPEX: 6ヶ月分の第3金曜計算 + 祝日調整 → DB → ICS
- DB永続化: GitHub Releases方式（db-latestタグ）
- テスト: 22本全通過

**未稼働:**
- TE (Trading Economics): Freeプラン制限でAPI呼び出し不可。スキップ中
- RSS→Claude抽出: ANTHROPIC_API_KEY未登録
- GitHub Pages: 未有効化（ICSのiPhone購読未設定）

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
    scheduled.py     ← TE(スキップ中) + FMP(稼働中)
    rss.py           ← RSSフィード取得
  llm/
    claude_extract.py ← Claude API抽出器（未稼働）
  canonical.py       ← canonical_key生成。shock系はsource_urlでhash
  config.py          ← AppConfig。bellwether_tickers等
  models.py          ← Event/Article Pydanticモデル
  db.py              ← SQLite upsert（冪等）
  ics.py             ← RFC5545 ICS生成。line folding+CRLF
  flows.py           ← OPEX計算
  prefilter.py       ← RSS記事2段階フィルタ
  validate.py        ← イベント検証
  impact.py          ← スタブ
  audit.py           ← スタブ
  notify.py          ← スタブ
config.yaml          ← 本番設定（keywords/macro_title_map/RSS/bellwether）
docs/ics/            ← ICS出力先（Actions自動commit）
docs/handoff/        ← 引き継ぎ文書
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

## 未解決の相談事項（GPTに投げた）

1. TEなしのmacro指標取得方針（FMP代替 / RSS→Claude / 静的YAML / ハイブリッド）
2. 次の優先順位（GitHub Pages / Claude抽出オン / macro代替実装）

## 関連プロジェクト

MR-LS最終パラメータ: z2/K3/excl_1（日米両市場共通、holdout両市場通過の唯一のパラメータ）
