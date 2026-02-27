# Sector Event Radar (skeleton)

このディレクトリは、添付仕様書「Sector Event Radar — Technical Spec v1.0」をベースにした実装スケルトンです。

目的:
- Scheduled/Unscheduled の2系統でイベントを収集
- canonical_keyで統合しSQLiteにupsert
- .ics生成
- 影響評価(統計はPython、文章化はLLM)
- Gmailで日次ブリーフィング、月次監査はGitHub Issue承認

注意:
- TE/FMP/Anthropic/yFinance など外部API部分は **実際のキーとエンドポイント** に合わせて埋めてください。
- ここでは「壊れにくい接続部(run_daily)」「イベントモデル」「canonical/validate/db/upsert」「OPEX計算」「ICS生成」を中心に実装しています。
