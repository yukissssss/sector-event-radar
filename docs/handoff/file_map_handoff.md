# Sector Event Radar — ファイルマップ（引き継ぎ用）

日付: 2026-02-27
リポジトリ: https://github.com/yukissssss/sector-event-radar (private)
ローカル: ~/Documents/stock_analyzer/sector_event_radar/

---

## プロジェクト構成（全体図）

```
sector-event-radar/
├── .github/workflows/
│   └── daily.yml              ← GitHub Actions定義
├── docs/ics/                  ← ICS出力先（Actionsが自動commit）
├── src/sector_event_radar/    ← メインコード
│   ├── collectors/            ← データ収集モジュール
│   │   ├── rss.py
│   │   └── scheduled.py
│   ├── llm/                   ← LLM関連
│   │   └── claude_extract.py
│   ├── run_daily.py           ← エントリポイント（日次バッチ）
│   ├── canonical.py           ← canonical_key生成
│   ├── config.py              ← 設定読み込み
│   ├── models.py              ← データモデル定義
│   ├── db.py                  ← SQLite操作
│   ├── ics.py                 ← ICSファイル生成
│   ├── validate.py            ← イベント検証
│   ├── prefilter.py           ← RSS記事スコアリング
│   ├── flows.py               ← OPEX計算
│   ├── utils.py               ← ユーティリティ
│   ├── impact.py              ← Phase 2（スタブ）
│   ├── audit.py               ← Phase 2（スタブ）
│   └── notify.py              ← Phase 2（スタブ）
├── tests/                     ← テスト（22本）
├── config.yaml                ← 本番設定
├── config.example.yaml        ← 設定テンプレート
├── pyproject.toml             ← パッケージ定義
└── requirements.txt           ← 依存パッケージ
```

---

## ファイル別 詳細

### インフラ・設定

| ファイル | 役割 | 状態 |
|---------|------|------|
| `.github/workflows/daily.yml` | GitHub Actions定義。毎朝22:05 UTC(07:05 JST)に自動実行。workflow_dispatchで手動実行も可。DB復元→バッチ実行→DB保存→ICS commit の4ステップ | ✅ 稼働中 |
| `config.yaml` | 本番設定。keywords(23個), prefilter閾値, macro_title_map(9パターン), RSSフィード(2本), bellwether_tickers(9銘柄), TE設定 | ✅ |
| `config.example.yaml` | GPTスケルトン由来のサンプル設定。config.yamlの雛形 | ✅ |
| `pyproject.toml` | Pythonパッケージ定義。`pip install -e .` で使う | ✅ |
| `requirements.txt` | pip依存リスト（pydantic, pyyaml, requests） | ✅ |
| `.gitignore` | .venv, __pycache__, events.sqlite, output等を除外 | ✅ |
| `docs/ics/` | ICS出力先。Actionsが自動commitする。GitHub Pages公開候補 | ✅ |

### コア（日次バッチ）

| ファイル | 役割 | 状態 |
|---------|------|------|
| `run_daily.py` | **エントリポイント**。3つのcollector(scheduled/computed/unscheduled)を独立try/exceptで実行→upsert→ICS生成。部分失敗設計：どのcollectorが落ちてもICS生成まで到達する。`--dry-run`でClaude抽出スキップ | ✅ Phase 1書き直し済み |
| `config.py` | AppConfigクラス。config.yamlを読み込んでPydanticモデルに変換。`bellwether_tickers`, `te_country`, `te_importance`もここで管理 | ✅ |
| `models.py` | Event / Article / ImpactSummary等のPydanticモデル定義。Eventが全モジュール共通のデータ構造 | ✅ GPTスケルトン流用 |

### 収集（Collectors）

| ファイル | 役割 | 状態 |
|---------|------|------|
| `collectors/scheduled.py` | **TE + FMP API実装**。`fetch_tradingeconomics_events()`: TE Economic Calendar→macroイベント。`fetch_fmp_earnings_events()`: FMP Earnings Calendar→bellwetherイベント。TEカテゴリフィルタ(30+指標)、FMP 3ヶ月チャンク分割、bellwetherティッカーフィルタ | ✅ 本セッションで実装 |
| `collectors/rss.py` | RSS/Atomフィード取得。feedparser不要の軽量XMLパーサー。RSS2 + Atom両対応 | ✅ GPTスケルトン流用 |

### 処理パイプライン

| ファイル | 役割 | 状態 |
|---------|------|------|
| `canonical.py` | canonical_key生成。`{category}:{entity}:{sub_type}:{YYYY-MM-DD}` 形式。shock系は`short_hash(source_url or source_id)`で衝突回避（Phase 1で修正済み） | ✅ Phase 1修正済み |
| `prefilter.py` | RSS記事の2段階フィルタ。Stage A: キーワードスコアリング(閾値超えのみ通過)、Stage B: スコア上位K件に絞り込み | ✅ GPTスケルトン流用 |
| `validate.py` | Eventの検証。timezone必須、start_at未来チェック、risk_score範囲等 | ✅ GPTスケルトン流用 |
| `db.py` | SQLite操作。`init_db()`: テーブル作成、`upsert_event()`: 冪等upsert(insert/update/merge/cancel判定)。eventsテーブル + event_historyテーブル | ✅ GPTスケルトン流用 |
| `utils.py` | `slugify_ascii()`: ASCII安全スラグ生成、`short_hash()`: SHA256短縮ハッシュ | ✅ GPTスケルトン流用 |

### LLM

| ファイル | 役割 | 状態 |
|---------|------|------|
| `llm/claude_extract.py` | **Claude API抽出器**。RSS記事→構造化イベントJSON。x-api-key認証、strict tool schema(全プロパティ定義)、`_parse_tool_output()`でtool_useブロック解析。SYSTEM_PROMPTに幻覚防止9ルール。429/529リトライ。受入基準:「日時なし記事→events=[]」 | ✅ Phase 1書き直し済み（ANTHROPIC_API_KEY未設定のため未稼働）|

### 出力

| ファイル | 役割 | 状態 |
|---------|------|------|
| `ics.py` | ICSファイル生成。RFC5545準拠。`_fold_line()`: 75オクテットline folding（マルチバイト安全）。CRLF改行。evidenceをDESCRIPTIONに出力。全体ICS + カテゴリ別4ファイル | ✅ Phase 1修正済み |
| `flows.py` | OPEX計算。第3金曜→exchange_calendarsで祝日調整→前営業日にずらす。exchange_calendarsなし環境でもフォールバック動作 | ✅ GPTスケルトン流用 |

### Phase 2以降（スタブ）

| ファイル | 役割 | 状態 |
|---------|------|------|
| `impact.py` | イベント影響評価。過去の同種イベント時の株価変動を統計分析。ticker_mapでyFinance記号に変換。3シナリオ(up/flat/down)生成 | ⏸ スタブ（Phase 2） |
| `audit.py` | 月次監査レポート。予測 vs 実績の精度評価 | ⏸ スタブ（Phase 2+） |
| `notify.py` | 通知。メール/Slack/iPhone通知連携 | ⏸ スタブ（Phase 2+） |

### テスト

| ファイル | テスト数 | カバー範囲 |
|---------|---------|-----------|
| `test_canonical_validate_flows_db.py` | 5本 | canonical_key生成(macro FOMC)、timezone必須検証、OPEX祝日調整(exchange_calendars有無分岐)、shock系hash衝突回避、db upsert 3パターン遷移 |
| `test_phase1.py` | 10本 | ICS line folding(short/long ASCII/multibyte)、CRLF準拠、長文evidence folding、Claude tool output parser(正常/empty/no block/wrong name)、run_daily部分失敗統合テスト |
| `test_scheduled.py` | 7本 | TE mock応答→filter(CPI+FOMC抽出/Crude Oil除外)、TE空応答、TE APIエラー伝播、FMP mock応答→bellwetherフィルタ(NVDA+MSFT抽出/WMT除外)、FMP空応答、FMP長期間チャンク分割、TEカテゴリフィルタ内容検証 |

---

## GitHub Secrets

| Secret名 | 用途 | 状態 |
|----------|------|------|
| `GITHUB_TOKEN` | Actions→Releases/commit用（自動提供） | ✅ 自動 |
| `FMP_API_KEY` | FMP Earnings Calendar API | ✅ 登録済み |
| `TE_API_KEY` | TE Economic Calendar API | ❌ Freeプラン制限で未登録 |
| `ANTHROPIC_API_KEY` | Claude抽出器 | ❌ 未登録（Phase 2で追加）|

---

## データフロー（現在稼働中）

```
毎朝07:05 JST (GitHub Actions)
  │
  ├─ FMP API ──→ bellwether決算日(9銘柄) ──┐
  ├─ OPEX計算 ──→ 第3金曜(6ヶ月分) ───────┤
  ├─ TE API ──→ (スキップ中) ──────────────┤
  └─ RSS→Claude ──→ (未有効) ──────────────┤
                                            │
                    canonical_key生成 ←──────┘
                         │
                    validate_event
                         │
                    upsert_event (SQLite)
                         │
                    events_to_ics
                         │
              ┌──────────┼──────────┐
              │          │          │
         all.ics    flows.ics  bellwether.ics
              │
         docs/ics/ にcommit
              │
         GitHub Releases に events.sqlite 保存
```

---

*このファイルマップはClaude（Anthropic）が作成。GPTへの引き継ぎ・共同開発用。*
