"""Grid search: low_ma parameters × volume × volatility. IS first, then OOS top 5."""
import os, sys
from pathlib import Path
from itertools import product

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader")

from app.services.factor_backtest import FactorBacktester, factor_and
from app.services.factor_library import low_ma, volume_surge, strong_up_slope, trend_r2

tester = FactorBacktester()
is_range = ("2024-11-01", "2025-12-31")  # excluding 2024 Sep-Oct (special market conditions)
oos_range = ("2026-01-01", "2026-12-31")

ma_periods = [20, 40, 60, 120]
vol_mults = [1.2, 1.5, 2.0]
r2_lookback = 20
r2_thresholds = [0.5, 0.6, 0.7, 0.8]

results = []
total = len(ma_periods) * len(vol_mults) * len(r2_thresholds)
n = 0

print(f"Grid search: {total} combinations...")
print(f"  MA periods: {ma_periods}")
print(f"  Vol mults: {vol_mults}")
print(f"  R2 thresholds: {r2_thresholds}")
print()

for ma_p, vm, r2t in product(ma_periods, vol_mults, r2_thresholds):
    n += 1
    combo = factor_and(
        low_ma(ma_p),
        volume_surge(5, vm),
        strong_up_slope(5, 3),
        trend_r2(r2_lookback, r2t),
    )
    name = f"MA{ma_p}_V{vm}x_R2_{r2t}"
    
    trades_is, stats_is = tester.run(combo, name, forward_days=5, date_range=is_range)
    
    results.append({
        "name": name, "ma": ma_p, "vol_mult": vm, "r2_thresh": r2t,
        "is_signals": stats_is.total_signals,
        "is_win": stats_is.win_rate,
        "is_avg": stats_is.avg_return,
        "is_sharpe": stats_is.sharpe,
        "is_ann": stats_is.annualized_return,
        "is_dd": stats_is.max_drawdown,
    })
    
    if n % 12 == 0:
        print(f"  [{n}/{total}] done", flush=True)

# Sort by IS sharpe, take top 5
results.sort(key=lambda x: -x["is_sharpe"])
top5 = results[:5]

print(f"\n{'='*90}")
print(f"  IS Top 5 (sorted by IS Sharpe)")
print(f"  {'='*90}")
print(f"  {'Rank':<5} {'Params':<25} {'Signals':>8} {'Win':>7} {'Avg':>8} {'Sharpe':>7} {'Ann':>8} {'MaxDD':>7}")
print(f"  {'─'*85}")
for i, r in enumerate(top5, 1):
    print(f"  {i:<5} {r['name']:<25} {r['is_signals']:>8} {r['is_win']*100:>6.1f}% {r['is_avg']:>7.2f}% {r['is_sharpe']:>6.3f} {r['is_ann']:>7.1f}% {r['is_dd']:>7.1f}%")

# Now OOS for top 5
print(f"\n{'='*90}")
print(f"  OOS Top 5 (same params, tested on 2026)")
print(f"  {'='*90}")
print(f"  {'Rank':<5} {'Params':<25} {'Signals':>8} {'Win':>7} {'Avg':>8} {'Sharpe':>7} {'Ann':>8} {'MaxDD':>7} {'Decay':>7}")
print(f"  {'─'*95}")
for i, r in enumerate(top5, 1):
    combo = factor_and(
        low_ma(r["ma"]),
        volume_surge(5, r["vol_mult"]),
        strong_up_slope(5, 3),
        trend_r2(r2_lookback, r["r2_thresh"]),
    )
    trades_oos, stats_oos = tester.run(combo, r["name"], forward_days=5, date_range=oos_range)
    decay = (r["is_sharpe"] - stats_oos.sharpe) / max(abs(r["is_sharpe"]), 0.01)
    print(f"  {i:<5} {r['name']:<25} {stats_oos.total_signals:>8} {stats_oos.win_rate*100:>6.1f}% {stats_oos.avg_return:>7.2f}% {stats_oos.sharpe:>6.3f} {stats_oos.annualized_return:>7.1f}% {stats_oos.max_drawdown:>7.1f}% {decay:>6.3f}")
