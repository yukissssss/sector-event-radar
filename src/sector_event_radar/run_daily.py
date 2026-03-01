#!/usr/bin/env python3
"""
MR-LS v9 デイリー運用ランチャー

日々の運用をワンコマンドで実行するラッパー。
市場ごとの個別スクリプトを呼び出す。

======================================
  日次運用フロー
======================================

  【米国市場 — 日本時間 朝6:00以降（US市場引け後）】

    Step 1: シグナル確認
      python run_daily.py us signal

    Step 2: 翌朝の約定記録（日本時間 翌日23:30以降、US市場寄付き後）
      python run_daily.py us fill

    Step 3: エグジット処理（K=3日後の引け）
      python run_daily.py us exit

  【日本市場 — 15:30以降（東証引け後）】

    Step 1: シグナル確認
      python run_daily.py jp signal

    Step 2: 翌朝の約定記録（翌日9:15以降、東証寄付き後）
      python run_daily.py jp fill

    Step 3: エグジット処理（K=3日後の引け）
      python run_daily.py jp exit

  【ステータス確認（いつでも）】
      python run_daily.py us status
      python run_daily.py jp status
      python run_daily.py us report
      python run_daily.py jp report
      python run_daily.py all status    ← US+JP両方

======================================
  v9パラメータ
======================================
  z_window:   2（2日間の相対リターン）
  z閾値:      -1.5
  K:          3営業日
  excl_1:     前日選定銘柄を翌日除外
  期待超過リターン: +39.7bp / トレード
  勝率:       58.0%

======================================
  必要ファイル
======================================
  mr_paper_trade.py      — US版ペーパートレード（v9）
  mr_paper_trade_jp.py   — JP版ペーパートレード（v9）
  run_daily.py           — このファイル（ランチャー）
"""

import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = Path(__file__).parent
US_SCRIPT = SCRIPT_DIR / "mr_paper_trade.py"
JP_SCRIPT = SCRIPT_DIR / "mr_paper_trade_jp.py"

# 為替レート（手動で更新、またはコマンドライン引数で指定）
DEFAULT_USD_JPY = 150.0
DEFAULT_CAPITAL_JPY = 10_000_000


# ============================================================
# Helpers
# ============================================================
def run_script(script_path, args=None, extra_args=None):
    """Run a paper trade script with given arguments."""
    if not script_path.exists():
        print(f"\n  ❌ スクリプトが見つかりません: {script_path}")
        print(f"     配置してください。")
        return False

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n  実行: {' '.join(cmd)}")
    print(f"  {'─' * 60}")

    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    return result.returncode == 0


def print_header(market, action):
    """Print a formatted header."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    market_label = {"us": "🇺🇸 US (S&P 500)", "jp": "🇯🇵 JP (日経225)", "all": "🌐 US + JP"}
    action_label = {
        "signal": "📊 シグナル確認",
        "fill": "✅ 約定記録",
        "exit": "🔚 エグジット処理",
        "status": "📋 ポートフォリオ現況",
        "report": "📈 累計P&Lレポート",
    }
    print(f"\n{'=' * 70}")
    print(f"  MR-LS v9  {market_label.get(market, market)}")
    print(f"  {action_label.get(action, action)}")
    print(f"  {now}")
    print(f"{'=' * 70}")


# ============================================================
# Commands
# ============================================================
def cmd_signal(market, extra_args):
    """Run signal check."""
    if market in ("us", "all"):
        print_header("us", "signal")
        run_script(US_SCRIPT, extra_args=extra_args)
    if market in ("jp", "all"):
        print_header("jp", "signal")
        run_script(JP_SCRIPT, extra_args=extra_args)


def cmd_fill(market, extra_args):
    """Record fill prices."""
    if market in ("us", "all"):
        print_header("us", "fill")
        run_script(US_SCRIPT, ["--fill"], extra_args)
    if market in ("jp", "all"):
        print_header("jp", "fill")
        run_script(JP_SCRIPT, ["--fill"], extra_args)


def cmd_exit(market, extra_args):
    """Process exits."""
    if market in ("us", "all"):
        print_header("us", "exit")
        run_script(US_SCRIPT, ["--exit"], extra_args)
    if market in ("jp", "all"):
        print_header("jp", "exit")
        run_script(JP_SCRIPT, ["--exit"], extra_args)


def cmd_status(market, extra_args):
    """Show portfolio status."""
    if market in ("us", "all"):
        print_header("us", "status")
        run_script(US_SCRIPT, ["--status"], extra_args)
    if market in ("jp", "all"):
        print_header("jp", "status")
        run_script(JP_SCRIPT, ["--status"], extra_args)


def cmd_report(market, extra_args):
    """Show P&L report."""
    if market in ("us", "all"):
        print_header("us", "report")
        run_script(US_SCRIPT, ["--report"], extra_args)
    if market in ("jp", "all"):
        print_header("jp", "report")
        run_script(JP_SCRIPT, ["--report"], extra_args)


def cmd_help():
    """Print usage guide."""
    print("""
╔══════════════════════════════════════════════════════════╗
║           MR-LS v9 デイリー運用ガイド                    ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  使い方:                                                 ║
║    python run_daily.py <market> <action> [options]        ║
║                                                          ║
║  market:  us / jp / all                                  ║
║  action:  signal / fill / exit / status / report          ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  【毎日のワークフロー】                                    ║
║                                                          ║
║  ● 日本市場（15:30以降）                                  ║
║    1. python run_daily.py jp signal                       ║
║    2. 翌朝 → python run_daily.py jp fill                  ║
║    3. 3日後 → python run_daily.py jp exit                 ║
║                                                          ║
║  ● 米国市場（翌朝6:00以降）                               ║
║    1. python run_daily.py us signal                       ║
║    2. 翌日23:30以降 → python run_daily.py us fill          ║
║    3. 3日後 → python run_daily.py us exit                 ║
║                                                          ║
║  ● 両市場一括                                             ║
║    python run_daily.py all status                         ║
║    python run_daily.py all report                         ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  オプション:                                              ║
║    --capital-jpy 10000000    運用資金（円）                 ║
║    --usd-jpy 150.0           為替レート（US用）             ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  v9パラメータ:                                            ║
║    z_window=2  K=3  excl_1=ON                            ║
║    期待: +39.7bp/trade  勝率: 58.0%                       ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")


# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 3:
        cmd_help()
        return

    market = sys.argv[1].lower()
    action = sys.argv[2].lower()
    extra_args = sys.argv[3:] if len(sys.argv) > 3 else []

    if market not in ("us", "jp", "all"):
        print(f"\n  ❌ 不明な市場: {market}")
        print(f"     us / jp / all を指定してください")
        return

    actions = {
        "signal": cmd_signal,
        "fill": cmd_fill,
        "exit": cmd_exit,
        "status": cmd_status,
        "report": cmd_report,
        "help": lambda m, e: cmd_help(),
    }

    if action not in actions:
        print(f"\n  ❌ 不明なアクション: {action}")
        print(f"     signal / fill / exit / status / report を指定してください")
        return

    actions[action](market, extra_args)


if __name__ == "__main__":
    main()
