"""Resume flow backfill - only ETFs without historical data yet."""
import json, os, sys, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

script = ROOT / "scripts" / "backfill_flow_history.py"
log = ROOT / "cache" / "flow_backfill.log"
err = ROOT / "cache" / "flow_backfill_err.log"

with open(log, "w", encoding="utf-8") as out, open(err, "w", encoding="utf-8") as eout:
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=out, stderr=eout,
        cwd=str(ROOT),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"Flow backfill restarted, PID={proc.pid}")
    print(f"Log: {log}")
    print(f"Check: Get-Content {log} -Tail 3")
