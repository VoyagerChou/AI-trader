#!/usr/bin/env python3
"""Daily ETF flow capture — run once per trading day after market close.
Captures today's fund flow snapshot for all ETFs in the universe.
~45 seconds. Designed for daily cron / scheduled task.
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader",
)

from app.services.etf_universe import get_etf_universe_service


def main():
    universe = get_etf_universe_service()
    
    # Refresh ETF list (uses cache if < 24h)
    etfs = universe.refresh(force=False)
    print(f"ETF universe: {len(etfs)} ETFs")
    
    # Capture today's flow
    result = universe.capture_flow_snapshot()
    if result.get("success"):
        print(f"Flow captured: {result['stored']}/{result['etf_count']} ETFs")
    else:
        print(f"Flow capture failed: {result.get('error')}")
    
    # Also try to backfill history for industry ETFs (best-effort)
    # Only runs if < 3 days of data exist for most ETFs
    print("Attempting historical backfill for industry ETFs...")
    try:
        hist = universe.capture_flow_history(days=30)
        print(f"History: {hist.get('stored', 0)} rows across {len(hist.get('rounds', []))} rounds")
    except Exception as e:
        print(f"History skipped (network unavailable): {e}")
    
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
