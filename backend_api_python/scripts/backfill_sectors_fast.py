"""Backfill sector features for all July trading days."""
import time, sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader")

from app.services.sector_feature_builder import get_sector_feature_builder
from app.utils.trading_calendar import get_trading_days_between

builder = get_sector_feature_builder()
days = get_trading_days_between("2026-07-01", "2026-07-08")
print(f"Trading days: {days}", flush=True)

total = 0
for d in days:
    t0 = time.time()
    r = builder.build_daily_features(as_of_date=d)
    elapsed = time.time() - t0
    total += elapsed
    print(f"  {d}: {elapsed:.0f}s sectors={r['sector_rows']} etfs={r['etf_rows']} | total={total:.0f}s", flush=True)
print(f"DONE in {total:.0f}s", flush=True)
