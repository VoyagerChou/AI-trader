"""Backfill ETF fund flow history from 2024-09 via push2his API."""
import json, os, sys, time, requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

from app.services.sector_feature_service import get_sector_feature_service

# Load ETF universe
cache = json.loads((ROOT / "cache" / "etf_universe.json").read_text(encoding="utf-8"))
etfs = cache["etfs"]
print(f"ETFs: {len(etfs)}")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})

store = get_sector_feature_service()
url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
total_stored = 0
failed = 0
t0 = time.time()

for i, etf in enumerate(etfs):
    code = etf["code"]
    secid = f"1.{code}" if code.startswith(("6","51","56","58")) else f"0.{code}"
    
    try:
        stored = 0
        r = SESSION.get(url, params={
            "secid": secid, "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56",
            "lmt": "500", "klt": "101", "fqt": "0",
        }, timeout=12)
        
        if r.status_code != 200:
            failed += 1
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
                store.upsert_etf_flow("CNStock", code, etf.get("name",""), d, {
                    "net_inflow_main": m, "net_inflow_super_large": sl,
                    "net_inflow_large": lg, "net_inflow_medium": md,
                    "net_inflow_small": sm, "net_inflow_ratio": (m/t)*100,
                    "metadata": {"flow_bias": sl/t},
                })
                stored += 1
            except: pass
        
        total_stored += stored
    except Exception as e:
        failed += 1
    
    if (i+1) % 30 == 0:
        elapsed = time.time() - t0
        print(f"  [{i+1}/{len(etfs)}] {code}: {stored}d | total={total_stored} failed={failed} | {elapsed:.0f}s", flush=True)
    
    time.sleep(0.15)

print(f"\nDone in {time.time()-t0:.0f}s. Stored: {total_stored} Failed: {failed}")
