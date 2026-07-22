"""Batch fund flow backfill via push2his — 10 ETFs per batch, 30s intervals."""
import json, os, sys, time, requests
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

from app.services.sector_feature_service import get_sector_feature_service

# Load ETF universe
cache = json.loads((ROOT / "cache" / "etf_universe.json").read_text(encoding="utf-8"))
all_etfs = cache["etfs"]

# Priority: industry ETFs first, then rest
from app.services.sector_feature_builder import INDUSTRY_TO_ETFS
industry_codes = set()
for etf_list in INDUSTRY_TO_ETFS.values():
    for e in etf_list:
        industry_codes.add(e["code"])

priority = [e for e in all_etfs if e["code"] in industry_codes]
rest = [e for e in all_etfs if e["code"] not in industry_codes]
etfs_to_fetch = priority + rest
# Remove duplicates while preserving order
seen = set()
etfs_to_fetch = [e for e in etfs_to_fetch if not (e["code"] in seen or seen.add(e["code"]))]

# Filter: only ETFs without historical data (less than 10 days)
store = get_sector_feature_service()
pending = []
for e in etfs_to_fetch:
    existing = store.get_latest_etf_flow(etf_code=e["code"], limit=50)
    if len(existing) < 10:
        pending.append(e)

print(f"Total ETFs: {len(all_etfs)}")
print(f"Industry ETFs: {len(priority)}")
print(f"Need backfill: {len(pending)}")
print(f"Batches: {len(pending)//10 + 1}")
print()

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

BATCH_SIZE = 10
PAUSE_SEC = 30
total_stored = 0
failed = 0
t0 = time.time()

for batch_start in range(0, len(pending), BATCH_SIZE):
    batch = pending[batch_start:batch_start + BATCH_SIZE]
    batch_num = batch_start // BATCH_SIZE + 1
    total_batches = len(pending) // BATCH_SIZE + 1
    
    batch_stored = 0
    for e in batch:
        code = e["code"]
        secid = f"1.{code}" if code.startswith(("6","51","56","58")) else f"0.{code}"
        try:
            r = SESSION.get(url, params={
                "secid": secid, "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56",
                "lmt": "300", "klt": "101", "fqt": "0",
            }, timeout=15)
            if r.status_code != 200:
                continue
            
            klines = (r.json().get("data") or {}).get("klines") or []
            stored = 0
            for line in klines:
                parts = line.split(",")
                if len(parts) < 6: continue
                d = parts[0]
                if not d or d == "-" or d < "2024-09-01": continue
                m = float(parts[1] or 0); sm = float(parts[2] or 0)
                md = float(parts[3] or 0); lg = float(parts[4] or 0); sl = float(parts[5] or 0)
                t = abs(m) if abs(m) > 0 else 1
                try:
                    store.upsert_etf_flow("CNStock", code, e.get("name",""), d, {
                        "net_inflow_main": m, "net_inflow_super_large": sl,
                        "net_inflow_large": lg, "net_inflow_medium": md,
                        "net_inflow_small": sm, "net_inflow_ratio": (m/t)*100,
                        "metadata": {"flow_bias": sl/t},
                    })
                    stored += 1
                except: pass
            
            batch_stored += stored
            total_stored += stored
        except Exception:
            failed += 1
    
    elapsed = time.time() - t0
    eta = (elapsed / max(1, batch_num)) * (total_batches - batch_num)
    print(f"  Batch {batch_num}/{total_batches}: {batch_stored}d | total={total_stored} failed={failed} | {elapsed:.0f}s ETA {eta/60:.0f}m", flush=True)
    
    if batch_start + BATCH_SIZE < len(pending):
        time.sleep(PAUSE_SEC)

print(f"\nDone in {time.time()-t0:.0f}s. Total stored: {total_stored} Failed: {failed}")
