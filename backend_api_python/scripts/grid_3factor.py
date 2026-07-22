"""3-factor resonance (no strong_up_slope): low_ma + volume_surge + fourth."""
import os, sys, csv
from pathlib import Path
from itertools import product

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader")

from app.services.factor_backtest import FactorBacktester, factor_and
from app.services.factor_library import low_ma, volume_surge, low_volatility, trend_r2

tester = FactorBacktester()
IS = ("2024-11-01", "2025-12-31")
OOS = ("2026-01-01", "2026-12-31")

headers = ["factor_type","ma_period","vol_mult","fourth_param",
    "is_signals","is_win_rate","is_avg_return","is_sharpe","is_ann_return","is_max_dd",
    "oos_signals","oos_win_rate","oos_avg_return","oos_sharpe","oos_ann_return","oos_max_dd","decay"]

out = ROOT / "reports" / "grid_3factor.csv"
f = open(out, "w", newline="", encoding="utf-8-sig")
w = csv.writer(f)
w.writerow(headers)

total = 36 + 48
n = 0

for ma_p, vm, vt in product([20,40,60,120], [1.2,1.5,2.0], [1.0,1.5,2.0]):
    n += 1
    c = factor_and(low_ma(ma_p), volume_surge(5, vm), low_volatility(20, vt))
    _, si = tester.run(c, "", 5, date_range=IS)
    _, so = tester.run(c, "", 5, date_range=OOS)
    d = (si.sharpe-so.sharpe)/max(abs(si.sharpe),0.01)
    w.writerow(["volatility",ma_p,vm,f"VOL<{vt}%",si.total_signals,round(si.win_rate,4),round(si.avg_return,4),round(si.sharpe,4),round(si.annualized_return,2),round(si.max_drawdown,2),so.total_signals,round(so.win_rate,4),round(so.avg_return,4),round(so.sharpe,4),round(so.annualized_return,2),round(so.max_drawdown,2),round(d,4)])
    f.flush()
    print(f"  [{n}/{total}] VOL MA{ma_p}_V{vm}x_VOL<{vt}%  IS_sig={si.total_signals} OOS_sig={so.total_signals}", flush=True)

for ma_p, vm, r2t in product([20,40,60,120], [1.2,1.5,2.0], [0.5,0.6,0.7,0.8]):
    n += 1
    c = factor_and(low_ma(ma_p), volume_surge(5, vm), trend_r2(20, r2t))
    _, si = tester.run(c, "", 5, date_range=IS)
    _, so = tester.run(c, "", 5, date_range=OOS)
    d = (si.sharpe-so.sharpe)/max(abs(si.sharpe),0.01)
    w.writerow(["R2",ma_p,vm,f"R2>{r2t}",si.total_signals,round(si.win_rate,4),round(si.avg_return,4),round(si.sharpe,4),round(si.annualized_return,2),round(si.max_drawdown,2),so.total_signals,round(so.win_rate,4),round(so.avg_return,4),round(so.sharpe,4),round(so.annualized_return,2),round(so.max_drawdown,2),round(d,4)])
    f.flush()
    print(f"  [{n}/{total}] R2 MA{ma_p}_V{vm}x_R2>{r2t}  IS_sig={si.total_signals} OOS_sig={so.total_signals}", flush=True)

f.close()
print(f"\nSaved to {out}")
