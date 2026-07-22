"""Backfill ETF features for a single date (post-close overwrite)."""
import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader"

import requests, json
from datetime import datetime, timedelta
from app.services.sector_feature_service import get_sector_feature_service

# Load ETF list
cache = json.loads((ROOT / "cache" / "etf_universe.json").read_text(encoding="utf-8"))
etfs = cache["etfs"]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})

def fetch_bars(code, count=60):
    prefix = "sh" if code.startswith(("6","51","56","58")) else "sz"
    params = {"param": f"{prefix}{code},day,,,{count},qfq"}
    r = SESSION.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get", params=params, timeout=10)
    data = r.json()
    root = (data.get("data") or {}).get(f"{prefix}{code}")
    if root:
        return root.get("qfqday") or root.get("day") or []
    return []

def safe_float(v):
    try: return float(v or 0)
    except: return 0

def pct_change(a, b):
    return ((a - b) / b * 100) if b != 0 else 0

store = get_sector_feature_service()
from datetime import datetime
d = datetime.now().strftime("%Y-%m-%d")
t0 = time.time()
stored = 0

for i, etf in enumerate(etfs):
    code = etf["code"]
    name = etf["name"]
    bars = fetch_bars(code)
    if len(bars) < 2:
        continue
    
    parsed = []
    for b in bars:
        cv = safe_float(b[2])
        if cv <= 0: continue
        parsed.append({"date": b[0], "open": safe_float(b[1]), "close": cv,
                       "high": safe_float(b[3]), "low": safe_float(b[4]), "vol": safe_float(b[5])})
    
    # Find today's bar
    today_bar = None
    for p in parsed:
        if p["date"] == d:
            today_bar = p
            break
    if not today_bar:
        continue
    
    # Store bar
    store.upsert_etf_market_bar(market="CNStock", etf_code=code, as_of_date=d, payload={
        "close_price": today_bar["close"], "open_price": today_bar["open"],
        "high_price": today_bar["high"], "low_price": today_bar["low"],
        "volume": today_bar["vol"], "turnover_amount": today_bar["vol"],
    })
    
    # Compute features (use closes up to today)
    closes = [p["close"] for p in parsed if p["date"] <= d]
    amounts = [p["vol"] for p in parsed if p["date"] <= d]
    
    adj_idx = 0
    for j in range(1, len(closes)):
        if abs(pct_change(closes[j], closes[j-1])) > 20:
            adj_idx = j; break
    
    eff_c = closes[adj_idx:] if adj_idx else closes
    eff_a = amounts[adj_idx:] if adj_idx else amounts
    n = len(eff_c)
    
    feature = {"close_price": eff_c[-1] if eff_c else 0}
    if n >= 2: feature["return_1d"] = pct_change(eff_c[-1], eff_c[-2])
    if n >= 6: feature["return_5d"] = pct_change(eff_c[-1], eff_c[-6])
    if n >= 21: feature["return_20d"] = pct_change(eff_c[-1], eff_c[-21])
    feature["turnover_amount"] = eff_a[-1] if eff_a else 0
    avg5 = sum(eff_a[-5:]) / max(1, len(eff_a[-5:]))
    feature["amount_ratio_5d"] = (eff_a[-1] / avg5) if avg5 > 0 else 0
    if adj_idx: feature["adj_event_detected"] = True
    
    store.upsert_etf_feature(market="CNStock", etf_code=code, etf_name=name, linked_sector="", as_of_date=d, payload=feature)
    stored += 1

print(f"Updated {stored} ETFs in {time.time()-t0:.0f}s")
