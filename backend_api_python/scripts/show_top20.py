import csv

rows = []
with open(r"D:\Quant\AI-Trader\backend_api_python\reports\grid_search_full.csv", "r", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append(r)

vol = [r for r in rows if r["factor_type"] == "volatility"]
r2v = [r for r in rows if r["factor_type"] == "R2"]

def show(title, data, key, n=20):
    s = sorted(data, key=lambda x: -float(x[key]))
    print(f"\n=== {title} ===")
    h = f"  {'Rank':<4} {'Params':<26} {'IS_sig':>6} {'IS_win':>6} {'IS_avg':>7} {'IS_sh':>6} {'IS_ann':>7} {'IS_dd':>6} | {'OOS_sig':>7} {'OOS_win':>6} {'OOS_avg':>7} {'OOS_sh':>6} {'OOS_ann':>7} {'OOS_dd':>6} {'Decay':>6}"
    print(h)
    print("  " + "-" * 145)
    for i, r in enumerate(s[:n], 1):
        label = f"MA{r['ma_period']}_V{r['vol_mult']}x_{r['fourth_param']}"
        print(f"  {i:<4} {label:<26} {r['is_signals']:>6} {float(r['is_win_rate'])*100:>5.1f}% {float(r['is_avg_return']):>6.2f}% {float(r['is_sharpe']):>5.3f} {float(r['is_ann_return']):>6.1f}% {float(r['is_max_dd']):>5.1f}% | {r['oos_signals']:>7} {float(r['oos_win_rate'])*100:>5.1f}% {float(r['oos_avg_return']):>6.2f}% {float(r['oos_sharpe']):>5.3f} {float(r['oos_ann_return']):>6.1f}% {float(r['oos_max_dd']):>5.1f}% {float(r['decay']):>5.2f}")

show("VOLATILITY - IS Sharpe Top 20", vol, "is_sharpe", 20)
show("R2 - IS Sharpe Top 20", r2v, "is_sharpe", 20)
show("VOLATILITY - OOS Sharpe Top 20", vol, "oos_sharpe", 20)
show("R2 - OOS Sharpe Top 20", r2v, "oos_sharpe", 20)
