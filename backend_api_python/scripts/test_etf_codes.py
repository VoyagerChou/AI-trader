"""Test all new ETF codes return valid K-line data."""
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.sector_feature_builder import INDUSTRY_TO_ETFS
from app.data_sources.cn_stock import CNStockDataSource

ds = CNStockDataSource()
d = "2026-07-08"
bt = int((datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).timestamp())

seen = set()
for sector, etfs in INDUSTRY_TO_ETFS.items():
    for etf in etfs:
        code = etf["code"]
        if code in seen:
            continue
        seen.add(code)
        rows = ds.get_kline(symbol=code, timeframe="1D", limit=5, before_time=bt)
        if rows:
            close = rows[-1].get("close", 0)
            print(f"  {code} ({etf['name']}) -> {len(rows)} bars, latest close={close}")
        else:
            print(f"  {code} ({etf['name']}) -> NO DATA")
