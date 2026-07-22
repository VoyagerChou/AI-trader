#!/usr/bin/env python3
"""Fast ETF universe backfill using Tencent fqkline API (one call per ETF for full history).

Each ETF gets 300 daily qfq bars in a single HTTP request.
232 ETFs × ~1 call each = ~2-3 minutes total (vs 28,000 calls previously).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader",
)

import requests
from app.services.sector_feature_service import get_sector_feature_service
from app.utils.trading_calendar import get_trading_days_between

TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://gu.qq.com/",
})


def _safe_float(v):
    try:
        return float(v or 0)
    except:
        return 0


def _pct_change(current, previous):
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def fetch_etf_kline(code: str, count: int = 300) -> list:
    """Fetch up to `count` daily qfq-adjusted bars for an ETF from Tencent."""
    # Determine prefix: 51/56/58xxxx → SH, 15/16xxxx → SZ
    if code.startswith(("51", "56", "58")):
        tcode = f"sh{code}"
    else:
        tcode = f"sz{code}"

    params = {"param": f"{tcode},day,,,{count},qfq"}
    try:
        resp = SESSION.get(TENCENT_URL, params=params, timeout=12)
        data = resp.json()
        root = (data.get("data") or {}).get(tcode)
        if not root:
            return []
        bars = root.get("qfqday") or root.get("day") or []
        return bars
    except Exception:
        return []


def backfill_etf(code: str, name: str, store, trading_days_set: set) -> int:
    """Backfill one ETF's full history. Returns number of days stored."""
    bars = fetch_etf_kline(code)
    if not bars or len(bars) < 2:
        return 0

    # Parse bars
    parsed = []
    for b in bars:
        date_str = str(b[0]).strip()  # YYYY-MM-DD
        close = _safe_float(b[2])
        if close <= 0:
            continue
        parsed.append({
            "date": date_str,
            "open": _safe_float(b[1]),
            "close": close,
            "high": _safe_float(b[3]),
            "low": _safe_float(b[4]),
            "volume": _safe_float(b[5]),
        })

    if len(parsed) < 2:
        return 0

    # Filter to only trading days in our range  
    closes = [p["close"] for p in parsed]
    amounts = [p["volume"] for p in parsed]  # Tencent returns 成交量 not 成交额
    
    count = 0
    for i, p in enumerate(parsed):
        if p["date"] not in trading_days_set:
            continue

        # Store bar
        bar_payload = {
            "close_price": p["close"],
            "open_price": p["open"],
            "high_price": p["high"],
            "low_price": p["low"],
            "volume": p["volume"],
            "turnover_amount": p["volume"],  # Tencent gives volume, not amount
        }
        store.upsert_etf_market_bar(
            market="CNStock", etf_code=code, as_of_date=p["date"], payload=bar_payload,
        )

        # Compute features (need enough history)
        if i < 1:
            continue

        # Use closes up to and including this bar
        hist_closes = closes[: i + 1]
        hist_amounts = amounts[: i + 1]

        # Detect adj events
        adj_idx = 0
        for j in range(1, len(hist_closes)):
            if abs(_pct_change(hist_closes[j], hist_closes[j - 1])) > 20:
                adj_idx = j
                break
        
        eff_c = hist_closes[adj_idx:] if adj_idx else hist_closes
        eff_a = hist_amounts[adj_idx:] if adj_idx else hist_amounts

        feature = {}
        n = len(eff_c)
        if n >= 2:
            feature["return_1d"] = _pct_change(eff_c[-1], eff_c[-2])
        if n >= 6:
            feature["return_5d"] = _pct_change(eff_c[-1], eff_c[-6])
        if n >= 21:
            feature["return_20d"] = _pct_change(eff_c[-1], eff_c[-21])
        feature["close_price"] = eff_c[-1]
        feature["turnover_amount"] = eff_a[-1] if eff_a else 0

        avg5 = sum(eff_a[-5:]) / max(1, len(eff_a[-5:]))
        feature["amount_ratio_5d"] = (eff_a[-1] / avg5) if avg5 > 0 else 0

        if adj_idx:
            feature["adj_event_detected"] = True
            feature["adj_event_date"] = parsed[adj_idx]["date"]

        store.upsert_etf_feature(
            market="CNStock", etf_code=code, etf_name=name,
            linked_sector="", as_of_date=p["date"], payload=feature,
        )
        count += 1

    return count


def main():
    # Load ETF universe from cache
    cache_path = ROOT / "cache" / "etf_universe.json"
    if not cache_path.exists():
        print("ERROR: etf_universe.json not found. Run refresh first.")
        return 1

    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    etfs = cache.get("etfs", [])

    # Trading days from 2026-01-01
    trading_days = get_trading_days_between("2026-01-01", datetime.now().strftime("%Y-%m-%d"))
    trading_days_set = set(trading_days)

    store = get_sector_feature_service()

    print(f"ETFs to process: {len(etfs)}")
    print(f"Trading days: {len(trading_days)}")
    print(f"Estimated time: {len(etfs) * 0.8:.0f}s (~{len(etfs) * 0.8 / 60:.0f}m)")
    print()

    total_features = 0
    total_bars = 0
    failed = 0
    t0 = time.time()

    for i, etf in enumerate(etfs):
        code = etf["code"]
        name = etf["name"]
        n = backfill_etf(code, name, store, trading_days_set)
        if n == 0:
            failed += 1
        else:
            total_features += n
            total_bars += n  # approximate

        if (i + 1) % 20 == 0 or i == len(etfs) - 1:
            elapsed = time.time() - t0
            eta = (elapsed / max(1, i + 1)) * (len(etfs) - i - 1)
            print(
                f"  [{i + 1}/{len(etfs)}] {code} {name}: {n} days | "
                f"total={total_features} failed={failed} | "
                f"{elapsed / 60:.0f}m elapsed, ETA {eta / 60:.0f}m",
                flush=True,
            )

        time.sleep(0.1)  # gentle rate limit

    total_time = time.time() - t0
    print(f"\nDONE in {total_time / 60:.0f}m. Features={total_features} Failed={failed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
