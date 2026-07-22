"""Clean partial ETF backfill data and restart."""
import psycopg2, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

# The partial backfill only stored data for 1 ETF (511880) across ~29 days
# We keep that data since it's valid. Just restart from where we left off.
# But the progress tracking in the log resets on restart anyway.

# Check what was actually stored
cur.execute("SELECT count(*), count(DISTINCT etf_code) FROM qd_etf_market_bars_daily WHERE as_of_date >= '2026-01-01'")
r = cur.fetchone()
print(f"etf bars since 2026: {r[0]} rows, {r[1]} distinct ETFs")

cur.execute("SELECT count(*), count(DISTINCT etf_code) FROM qd_etf_features_daily WHERE as_of_date >= '2026-01-01'")
r = cur.fetchone()
print(f"etf features since 2026: {r[0]} rows, {r[1]} distinct ETFs")

conn.close()

# Restart backfill
log = ROOT / "cache" / "etf_backfill.log"
err = ROOT / "cache" / "etf_backfill_err.log"
script = ROOT / "scripts" / "backfill_etf_universe.py"

with open(log, "w", encoding="utf-8") as out, open(err, "w", encoding="utf-8") as eout:
    proc = subprocess.Popen(
        [sys.executable, str(script), "--start-date", "2026-01-01"],
        stdout=out, stderr=eout,
        cwd=str(ROOT),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"Restarted, PID={proc.pid}")
    print(f"Log: {log}")
