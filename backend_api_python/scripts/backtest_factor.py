#!/usr/bin/env python3
"""CLI entry for factor backtesting.

Usage:
  python scripts/backtest_factor.py --help
"""
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader")

from app.services.factor_backtest import FactorBacktester, print_stats, run_is_oos_test, print_is_oos


def _run_multi_forward(factor_fn, name, tester, args):
    """Run factor across 1/3/5/10 day forward periods, print comparison table."""
    periods = [1, 3, 5, 10]
    results = []
    for d in periods:
        if args.is_oos:
            r = run_is_oos_test(
                factor_fn, name, d,
                is_range=(args.is_start, args.is_end),
                oos_range=(args.oos_start, args.oos_end),
            )
            r["forward"] = d
        else:
            trades, stats = tester.run(factor_fn, name, d)
            r = {
                "forward": d,
                "signals": stats.total_signals,
                "win_rate": stats.win_rate,
                "avg_return": stats.avg_return,
                "sharpe": stats.sharpe,
                "ann_return": stats.annualized_return,
                "max_dd": stats.max_drawdown,
            }
        results.append(r)

    # Print comparison table
    if args.is_oos:
        print(f"\n{'='*80}")
        print(f"  Factor: {name}  (IS/OOS Split)")
        print(f"  {'='*80}")
        # IS table
        print(f"\n  {'In-Sample':^70}")
        print(f"  {'─'*70}")
        print(f"  {'前向天数':>8} {'信号数':>8} {'胜率':>8} {'均收益':>8} {'夏普':>8} {'年化':>8} {'最大回撤':>8}")
        for r in results:
            print(f"  {r['forward']:>8}d {r['is_signals']:>8} {r['is_win_rate']*100:>7.1f}% {r['is_avg_return']:>7.2f}% {r['is_sharpe']:>7.3f} {r['is_ann_return']:>7.1f}% {r['is_max_dd']:>7.1f}%")
        # OOS table
        print(f"\n  {'Out-of-Sample':^70}")
        print(f"  {'─'*70}")
        print(f"  {'前向天数':>8} {'信号数':>8} {'胜率':>8} {'均收益':>8} {'夏普':>8} {'年化':>8} {'最大回撤':>8}")
        for r in results:
            print(f"  {r['forward']:>8}d {r['oos_signals']:>8} {r['oos_win_rate']*100:>7.1f}% {r['oos_avg_return']:>7.2f}% {r['oos_sharpe']:>7.3f} {r['oos_ann_return']:>7.1f}% {r['oos_max_dd']:>7.1f}%")
        # PBO summary
        print(f"\n  {'─'*70}")
        print(f"  {'前向天数':>8} {'Sharpe衰减':>10} {'PBO':>8} {'PBO判定':>30}")
        for r in results:
            print(f"  {r['forward']:>8}d {r['degradation']:>10.3f} {r['pbo']:>7.3f}  {r['pbo_warning']:<30}")
    else:
        print(f"\n{'='*80}")
        print(f"  Factor: {name}")
        print(f"  {'='*80}")
        print(f"  {'前向天数':>8} {'信号数':>8} {'胜率':>8} {'均收益':>8} {'夏普':>8} {'年化':>8} {'最大回撤':>8} {'盈亏比':>8}")
        print(f"  {'─'*80}")
        for r in results:
            print(f"  {r['forward']:>8}d {r['signals']:>8} {r['win_rate']*100:>7.1f}% {r['avg_return']:>7.2f}% {r['sharpe']:>7.3f} {r['ann_return']:>7.1f}% {r['max_dd']:>7.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Multi-factor ETF backtester")
    parser.add_argument("--factor", default="consolidation_breakout",
                       help="Factor name from factor_library")
    parser.add_argument("--forward", type=int, default=5,
                       help="Forward days to measure return")
    parser.add_argument("--forward-all", action="store_true",
                       help="Run 1/3/5/10 day forward periods and print comparison table")
    parser.add_argument("--limit", type=int, default=0,
                       help="Limit ETFs tested (0=all)")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")
    parser.add_argument("--is-oos", action="store_true",
                       help="Run in-sample/out-of-sample split test")
    parser.add_argument("--is-start", default="2024-01-01",
                       help="In-sample start date")
    parser.add_argument("--is-end", default="2025-12-31",
                       help="In-sample end date")
    parser.add_argument("--oos-start", default="2026-01-01",
                       help="Out-of-sample start date")
    parser.add_argument("--oos-end", default="2026-12-31",
                       help="Out-of-sample end date")
    args = parser.parse_args()

    import importlib
    try:
        lib = importlib.import_module("app.services.factor_library")
        factor_fn = getattr(lib, args.factor)
    except (ImportError, AttributeError) as e:
        print(f"Factor '{args.factor}' not found: {e}")
        print("Available factors will be in app/services/factor_library.py")
        return 1

    tester = FactorBacktester()
    if args.limit > 0:
        tester.etf_codes = tester._load_etf_list()[:args.limit]

    if args.forward_all:
        _run_multi_forward(factor_fn, args.factor, tester, args)
        return 0

    if args.is_oos:
        from app.services.factor_backtest import run_is_oos_test, print_is_oos
        result = run_is_oos_test(
            factor_fn, args.factor, args.forward,
            is_range=(args.is_start, args.is_end),
            oos_range=(args.oos_start, args.oos_end),
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_is_oos(result)
        return 0

    trades, stats = tester.run(factor_fn, args.factor, args.forward)

    if args.json:
        print(json.dumps({
            "factor": stats.factor_name,
            "signals": stats.total_signals,
            "etfs": stats.total_etfs,
            "win_rate": round(stats.win_rate, 4),
            "avg_return": round(stats.avg_return, 2),
            "sharpe": round(stats.sharpe, 3),
            "profit_factor": round(stats.profit_factor, 2),
            "monthly": stats.by_month,
        }, ensure_ascii=False, indent=2))
    else:
        print_stats(stats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
