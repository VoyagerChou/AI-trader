#!/usr/bin/env python3
"""Backfill structured A-share history into AI-Trader.

This script is the first serious step toward a larger historical database.
It walks day by day and materializes:
- industry / ETF daily features
- advanced A-share structure snapshots (phase1 / phase2)

Usage example:
  python scripts/backfill_structured_history.py --start-date 2024-09-25 --end-date 2026-07-03
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

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.services.cn_advanced_data_builder import get_cn_advanced_data_builder  # noqa: E402
from app.services.sector_feature_builder import get_sector_feature_builder  # noqa: E402
from app.utils.trading_calendar import get_trading_days_between  # noqa: E402


def _iter_dates(start_date: str, end_date: str):
    """Iterate over TRADING days only between start and end (inclusive)."""
    return get_trading_days_between(start_date, end_date)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill structured history")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--sleep-ms", type=int, default=0)
    args = parser.parse_args()

    sector_builder = get_sector_feature_builder()
    advanced_builder = get_cn_advanced_data_builder()

    total_days = 0
    sector_days = 0
    advanced_days = 0

    for as_of_date in _iter_dates(args.start_date, args.end_date):
        total_days += 1
        sf = sector_builder.build_daily_features(as_of_date=as_of_date, lookback_days=7)
        adv1 = advanced_builder.build_phase1(as_of_date=as_of_date, lookback_days=7)
        adv2 = advanced_builder.build_phase2(as_of_date=as_of_date)
        if sf.get("success"):
            sector_days += 1
        if adv1.get("success") and adv2.get("success"):
            advanced_days += 1
        print(
            json.dumps(
                {
                    "as_of_date": as_of_date,
                    "sector_features": sf,
                    "advanced_phase1": adv1,
                    "advanced_phase2": adv2,
                },
                ensure_ascii=False,
            )
        )
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    print(
        json.dumps(
            {
                "done": True,
                "total_days": total_days,
                "sector_days": sector_days,
                "advanced_days": advanced_days,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
