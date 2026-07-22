"""A-share trading calendar utility.

Weekend exclusion is automatic (Saturday/Sunday).
Holidays are hardcoded for 2024-2026 based on official exchange announcements.
For dates outside this range, only weekend check is performed.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Set

# A-share market holidays 2024-2026 (official SSE/SZSE announcements)
_A_SHARE_HOLIDAYS: Set[str] = {
    # 2024
    "2024-01-01",
    "2024-02-09", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16",
    "2024-04-04", "2024-04-05",
    "2024-05-01", "2024-05-02", "2024-05-03",
    "2024-06-10",
    "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-07",
    # 2025
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04",
    "2025-04-04",
    "2025-05-01", "2025-05-02", "2025-05-05",
    "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
    # 2026
    "2026-01-01", "2026-01-02",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-04-06",
    "2026-05-01", "2026-05-04", "2026-05-05",
    "2026-06-19",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
}


def is_trading_day(d: Optional[str] = None) -> bool:
    """Check if a given date is an A-share trading day."""
    if d is None:
        d = datetime.now().strftime("%Y-%m-%d")
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    if dt.weekday() >= 5:
        return False
    if dt.strftime("%Y-%m-%d") in _A_SHARE_HOLIDAYS:
        return False
    return True


def get_trading_days_between(start: str, end: str) -> list:
    """Return all trading days between start and end (inclusive)."""
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end, "%Y-%m-%d").date()
    result = []
    cur = start_dt
    while cur <= end_dt:
        cur_str = cur.strftime("%Y-%m-%d")
        if is_trading_day(cur_str):
            result.append(cur_str)
        cur += timedelta(days=1)
    return result
