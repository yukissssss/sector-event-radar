# GPT経過報告 — GitHub Actions本番稼働 & FMP collector実装完了

日付: 2026-02-27
前回: GPTからハイブリッド（選択肢C）+ DB永続化はGitHub Releases方式の提案を受領

---

## 1. 実施結果サマリ

GPT提案の選択肢C（ハイブリッド）に従い、本日中に以下を全て完了。

| ステップ | 状態 | 備考 |
|---------|------|------|
| GitHub リポジトリ作成 (private) | ✅ | https://github.com/yukissssss/sector-event-radar |
| git init + initial commit (29ファイル) | ✅ | Phase 1コード + daily.yml + .gitignore + config.yaml |
| GitHub Actions dry-run 初回実行 | ✅ 緑 | OPEX→DB→ICS生成成功 |
| DB永続化 (GitHub Releases) | ✅ | `db-latest` タグで events.sqlite 自動保存確認 |
| TE/FMP collectors 実装 | ✅ | 22テスト全通過 → push |
| FMP_API_KEY Secret 登録 | ✅ | Free plan (250 calls/day) |
| DRY_RUN=false に変更 | ✅ | FMP collector 有効化 |
| Actions本番実行（FMP有効） | ✅ 緑 | bellwether決算日がDB→ICSに反映 |

---

## 2. TE (Trading Economics) の状況

### 結論: TEは当面スキップ

Free（Developer）プランでアカウント作成したが、以下のメッセージが表示された：

> "The API requests and row status is not offered for API Free, Google Free or Trial plans."

**Freeプランでは API呼び出し不可**。有料プランのみ。`guest:guest` でサンプルデータは取れるが、本番運用には不適。

### macro指標の代替方針

CPI/FOMC/NFP等のmacro指標日程は以下で代替可能：
1. **RSS→Claude抽出** — ニュース記事から日程を構造化抽出（Phase 2で有効化）
2. **手動/静的カレンダー** — FOMCは年8回、CPI/NFPは毎月固定日程でほぼ予測可能。config.yamlにハードコードする選択肢もある
3. **FMP Economic Calendar** — FMPにもeconomic calendarエンドポイントがある（要調査、Free planで使えるか未確認）

GPTの意見を聞きたい: **TEなしでmacro指標をどう確保するか、最も効率的な方法は？**

---

## 3. 現在のシステム状態

### GitHub Actions（毎朝07:05 JST自動実行）
```
Collectors:
  ✅ OPEX (computed)      — 6ヶ月分、第3金曜計算 + 祝日調整
  ✅ FMP (bellwether)     — NVDA/TSM/ASML/AMD/AVGO/MSFT/GOOGL/AMZN/META
  ⏸ TE (macro)           — Freeプラン制限によりスキップ
  ⏸ RSS→Claude (shock)   — ANTHROPIC_API_KEY未設定

Pipeline:
  収集 → canonical_key生成 → validate → upsert(冪等) → ICS生成(全体+カテゴリ別)

ICS出力:
  docs/ics/sector_events_all.ics
  docs/ics/sector_events_flows.ics
  docs/ics/sector_events_bellwether.ics
  docs/ics/sector_events_macro.ics (TEスキップ中は空)
  docs/ics/sector_events_shock.ics (Claude未有効のため空)
```

### テスト: 22本全通過
```
tests/test_canonical_validate_flows_db.py  5本（canonical/validate/OPEX/shock hash/db upsert）
tests/test_phase1.py                      10本（ICS folding/CRLF/Claude parser/部分失敗）
tests/test_scheduled.py                    7本（TE mock/FMP mock/filter/chunk/error）
```

### Secrets登録状況
| Secret | 状態 |
|--------|------|
| FMP_API_KEY | ✅ 登録済み |
| TE_API_KEY | ❌ Freeプラン制限で未登録 |
| ANTHROPIC_API_KEY | ❌ 未登録（Phase 2で追加予定）|

---

## 4. 残タスク

### 即座に実行可能
- [ ] GitHub Pages有効化 → ICSをiPhoneカレンダーから購読可能にする
- [ ] ANTHROPIC_API_KEY登録 → RSS→Claude抽出をオン（shockカテゴリ有効化）

### 設計判断が必要（GPTに相談）
- [ ] **TEなしのmacro指標取得方針** — 上記3案のどれを採用するか
- [ ] **FMP Economic Calendar の活用** — bellwether以外にmacro指標も取れるか調査
- [ ] **RSSフィード追加** — 現在BIS + SemiEngineeringの2本のみ。shock検出力を上げるには追加が必要

### Phase 2以降
- [ ] impact.py 実装（イベント影響評価）
- [ ] ticker_map 実データ検証（yFinance記号の確定）
- [ ] 月次監査レポート
- [ ] iPhone通知連携

---

## 5. GPTへの相談事項

### Q1: TEなしのmacro指標取得

TEが使えないため、以下の選択肢から推奨を聞きたい。

**A) FMP Economic Calendar で代替**
- FMPに `/v3/economic_calendar` エンドポイントがある
- Free planで使えるか未確認
- 使えれば、TEと同等のデータが1つのAPI契約で済む

**B) RSS→Claude抽出に頼る**
- 日程が記事に明記されていれば抽出可能
- ただし「CPI発表日」を専門的に報じるRSSフィードの選定が必要
- 漏れのリスクがある（RSSに載らない or prefilterで落ちる）

**C) 静的カレンダー（config.yaml にハードコード）**
- FOMC: 年8回、日程は1月に公開される
- CPI/NFP: 毎月ほぼ固定日程（BLS公開スケジュールを年1回取り込み）
- 最も確実だが手動メンテナンスが必要
- `scheduled.py` に「YAML読み込み → Event生成」のローカルcollectorを追加する形

**D) ハイブリッド（C + B）**
- 年初にFOMC/CPI/NFPの年間日程をconfigに入れる（確実）
- RSSからの抽出で「予定変更」「臨時FOMC」等を補完する

### Q2: 次の優先順位

以下のどれを先に進めるべきか：
1. GitHub Pages有効化（iPhoneで実際にカレンダー確認）
2. ANTHROPIC_API_KEY登録 + Claude抽出E2Eテスト
3. macro指標の代替実装

---

*このメモはClaude（Anthropic）が作成。GitHub Actions本番稼働報告とTE代替方針の相談を目的とする。*
