import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

from app.services.sector_feature_service import get_sector_feature_service
from app.services.sector_feature_builder import INDUSTRY_TO_ETFS

s = get_sector_feature_service()

missing = []
found = []
for sector, etfs in INDUSTRY_TO_ETFS.items():
    code = etfs[0]["code"]
    rows = s.get_latest_etf_flow(code)
    if rows:
        r = rows[0]
        found.append(f"  {sector}: {code} main={r['net_inflow_main']/1e4:.0f}万 ratio={r['net_inflow_ratio']:.1f}%")
    else:
        missing.append(f"  {sector}: {code} -- NO FLOW DATA")

print(f"ETFs WITH flow data: {len(found)}/29")
for f in found:
    print(f)
print(f"\nETFs MISSING flow data: {len(missing)}/29")
for m in missing:
    print(m)
