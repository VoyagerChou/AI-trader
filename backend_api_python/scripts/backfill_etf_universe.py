#!/usr/bin/env python3
"""Backfill daily K-line data for ALL ETFs in the universe (turnover >= 1亿).

This script refreshes the ETF universe list, then for each ETF fetches
daily OHLCV bars and stores ETF-level features.

Usage:
  python scripts/backfill_etf_universe.py [--start-date 2026-01-01] [--end-date 2026-07-08]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ETF universe daily features")
    parser.add_argument("--start-date", default="2026-01-05")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--sleep-ms", type=int, default=100,
                        help="Sleep between ETF kline calls to avoid rate limiting")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list ETFs and estimated time, don't fetch data")
    args = parser.parse_args()

    # Setup
    import os
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader",
    )

    from app.services.etf_universe import get_etf_universe_service
    from app.services.kline import KlineService
    from app.services.sector_feature_service import get_sector_feature_service
    from app.utils.trading_calendar import get_trading_days_between

    # Step 1: refresh ETF universe
    print("=== STEP 1: Refresh ETF Universe ===", flush=True)
    universe = get_etf_universe_service()
    etfs = universe.refresh(force=True)
    codes = [e["code"] for e in etfs]
    print(f"  ETFs with turnover >= 1亿: {len(codes)}", flush=True)
    if len(codes) > 5:
        print(f"  Top 5: {[(e['code'], e['name']) for e in etfs[:5]]}", flush=True)

    if args.dry_run:
        days = get_trading_days_between(args.start_date, args.end_date or datetime.now().strftime("%Y-%m-%d"))
        est_seconds = len(codes) * len(days) * 1.2  # ~1.2s per ETF per day
        print(f"\n  Dry run: {len(codes)} ETFs × {len(days)} days ≈ {est_seconds / 3600:.1f} hours", flush=True)
        return 0

    # Step 2: determine trading days
    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    trading_days = get_trading_days_between(args.start_date, end_date)
    print(f"\n=== STEP 2: Backfill {len(codes)} ETFs × {len(trading_days)} days ===", flush=True)
    print(f"  Date range: {trading_days[0] if trading_days else 'N/A'} → {end_date}", flush=True)

    kline = KlineService()
    store = get_sector_feature_service()

    total_etf_days = 0
    success_days = 0
    start_time = time.time()

    for day_idx, as_of_date in enumerate(trading_days):
        bt = int((datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)).timestamp())

        for etf in etfs:
            code = etf["code"]
            name = etf["name"]
            try:
                rows = kline.get_kline(
                    market="CNStock", symbol=code,
                    timeframe="1D", limit=60, before_time=bt,
                )
                if not rows or len(rows) < 2:
                    continue

                # Store raw bars
                for row in rows:
                    close_v = _safe_float(row.get("close"))
                    if close_v <= 0:
                        continue
                    time_v = int(row.get("time") or 0)
                    bar_date = datetime.fromtimestamp(time_v).strftime("%Y-%m-%d") if time_v else as_of_date
                    bar_payload = {
                        "close_price": close_v,
                        "open_price": _safe_float(row.get("open")),
                        "high_price": _safe_float(row.get("high")),
                        "low_price": _safe_float(row.get("low")),
                        "volume": _safe_float(row.get("volume")),
                        "turnover_amount": _safe_float(row.get("amount") or row.get("volume") or 0),
                    }
                    store.upsert_etf_market_bar(
                        market="CNStock", etf_code=code,
                        as_of_date=bar_date, payload=bar_payload,
                    )

                # Compute ETF features (returns, vol, drawdown)
                normalized = _normalize_bars(rows, as_of_date)
                if len(normalized) >= 2:
                    from app.services.sector_feature_builder import _pct_change, _safe_float as _sf

                    closes = [b["close_price"] for b in normalized]
                    amounts = [b["turnover_amount"] for b in normalized]

                    # Detect ETF adjustment events (single-day >20% jump)
                    adj_idx = 0
                    for i in range(1, len(closes)):
                        pct = _pct_change(closes[i], closes[i - 1])
                        if abs(pct) > 20:
                            adj_idx = i
                            break

                    eff_closes = closes[adj_idx:] if adj_idx else closes
                    eff_amounts = amounts[adj_idx:] if adj_idx else amounts

                    feature = {
                        "close_price": eff_closes[-1] if eff_closes else 0,
                        "return_1d": _pct_change(eff_closes[-1], eff_closes[-2]) if len(eff_closes) >= 2 else 0,
                        "return_3d": _pct_change(eff_closes[-1], eff_closes[-4]) if len(eff_closes) >= 4 else 0,
                        "return_5d": _pct_change(eff_closes[-1], eff_closes[-6]) if len(eff_closes) >= 6 else 0,
                        "return_10d": _pct_change(eff_closes[-1], eff_closes[-11]) if len(eff_closes) >= 11 else 0,
                        "return_20d": _pct_change(eff_closes[-1], eff_closes[-21]) if len(eff_closes) >= 21 else 0,
                        "turnover_amount": eff_amounts[-1] if eff_amounts else 0,
                        "etf_avg_amount_5d": sum(eff_amounts[-5:]) / max(1, len(eff_amounts[-5:])),
                        "etf_avg_amount_20d": sum(eff_amounts[-20:]) / max(1, len(eff_amounts[-20:])),
                        "drawdown_from_20d_high": _pct_change(eff_closes[-1], max(eff_closes[-20:])) if len(eff_closes) >= 20 else 0,
                    }

                    avg5 = feature["etf_avg_amount_5d"]
                    avg20 = feature["etf_avg_amount_20d"]
                    feature["amount_ratio_5d"] = (feature["turnover_amount"] / avg5) if avg5 > 0 else 0
                    feature["amount_ratio_20d"] = (feature["turnover_amount"] / avg20) if avg20 > 0 else 0
                    returns_5 = [_pct_change(eff_closes[j], eff_closes[j - 1]) for j in range(max(1, len(eff_closes) - 5), len(eff_closes))]
                    feature["volatility_5d"] = sum(abs(x) for x in returns_5) / max(1, len(returns_5))
                    feature["etf_liquidity_score"] = min(100.0, avg5 / 1_000_000.0)

                    if adj_idx:
                        feature["adj_event_detected"] = True
                        feature["adj_event_date"] = normalized[adj_idx].get("as_of_date", "") if adj_idx < len(normalized) else ""
                        feature["adj_event_pct"] = _pct_change(closes[adj_idx], closes[adj_idx - 1])

                    store.upsert_etf_feature(
                        market="CNStock", etf_code=code, etf_name=name,
                        linked_sector="", as_of_date=as_of_date, payload=feature,
                    )
                    success_days += 1

            except Exception as exc:
                pass  # Individual ETF failure is non-fatal

            total_etf_days += 1

        # Progress per day
        elapsed = time.time() - start_time
        eta = (elapsed / max(1, day_idx + 1)) * (len(trading_days) - day_idx - 1)
        print(
            f"  [{day_idx + 1}/{len(trading_days)}] {as_of_date}: {success_days}/{total_etf_days} ok "
            f"({elapsed / 60:.0f}m elapsed, ETA {eta / 60:.0f}m)",
            flush=True,
        )
        
        if args.sleep_ms:
            time.sleep(args.sleep_ms / 1000.0)

    total_time = time.time() - start_time
    print(f"\n=== DONE in {total_time / 60:.0f}m ===", flush=True)
    print(f"  ETF-days: {success_days}/{total_etf_days}", flush=True)
    return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0


def _normalize_bars(rows: List[Dict[str, Any]], fallback_date: str) -> List[Dict[str, Any]]:
    """Normalize kline rows, filtering zero-close bars."""
    out = []
    for row in rows:
        close_v = _safe_float(row.get("close"))
        if close_v <= 0:
            continue
        time_v = int(row.get("time") or 0)
        bar_date = datetime.fromtimestamp(time_v).strftime("%Y-%m-%d") if time_v else fallback_date
        out.append({
            "as_of_date": bar_date,
            "close_price": close_v,
            "turnover_amount": _safe_float(row.get("amount") or row.get("volume") or 0),
        })
    return out


if __name__ == "__main__":
    raise SystemExit(main())
