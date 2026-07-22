"""Extend ETF K-line data back to 2024-09-01 using Tencent fqkline API."""
import json, os, sys, time, requests
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

from app.services.sector_feature_service import get_sector_feature_service

# Load ETF universe
cache = json.loads((ROOT / "cache" / "etf_universe.json").read_text(encoding="utf-8"))
etfs = cache["etfs"]
print(f"ETFs: {len(etfs)}")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})

def fetch_bars(code, count=500):
    prefix = "sh" if code.startswith(("6","51","56","58")) else "sz"
    params = {"param": f"{prefix}{code},day,,,{count},qfq"}
    r = SESSION.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get", params=params, timeout=15)
    data = r.json()
    root = (data.get("data") or {}).get(f"{prefix}{code}")
    if root:
        return root.get("qfqday") or root.get("day") or []
    return []

def safe_float(v):
    try: return float(v or 0)
    except: return 0

store = get_sector_feature_service()
start_date = "2024-01-01"
end_date = "2024-08-31"

total_stored = 0
t0 = time.time()

for i, etf in enumerate(etfs):
    code = etf["code"]
    bars = fetch_bars(code, 500)
    if len(bars) < 2:
        continue
    
    stored = 0
    for b in bars:
        date_str = b[0]
        if date_str < start_date or date_str > end_date:
            continue
        close = safe_float(b[2])
        if close <= 0:
            continue
        try:
            store.upsert_etf_market_bar(market="CNStock", etf_code=code, as_of_date=date_str, payload={
                "close_price": close,
                "open_price": safe_float(b[1]),
                "high_price": safe_float(b[3]),
                "low_price": safe_float(b[4]),
                "volume": safe_float(b[5]),
                "turnover_amount": safe_float(b[5]),
            })
            stored += 1
            total_stored += 1
        except Exception:
            pass
    
    if (i+1) % 40 == 0:
        elapsed = time.time() - t0
        print(f"  [{i+1}/{len(etfs)}] {code}: {stored} bars | total={total_stored} | {elapsed:.0f}s", flush=True)
    time.sleep(0.05)

print(f"\nDone in {time.time()-t0:.0f}s. Total bars: {total_stored}")
