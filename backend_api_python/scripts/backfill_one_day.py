import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

from app.services.sector_feature_builder import get_sector_feature_builder
from app.utils.trading_calendar import is_trading_day

from datetime import datetime
d = datetime.now().strftime("%Y-%m-%d")
if not is_trading_day(d):
    print(f"{d} is NOT a trading day, skipped")
else:
    b = get_sector_feature_builder()
    t = time.time()
    r = b.build_daily_features(as_of_date=d)
    elapsed = time.time() - t
    print(f"{d}: success={r['success']} sectors={r['sector_rows']} etfs={r['etf_rows']} ({elapsed:.0f}s)", flush=True)
