#!/usr/bin/env python3
"""Spawn a detached background backfill process that survives terminal close."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script = ROOT / "scripts" / "backfill_etf_universe.py"
log = ROOT / "cache" / "etf_backfill.log"
err = ROOT / "cache" / "etf_backfill_err.log"

# Ensure cache dir
log.parent.mkdir(parents=True, exist_ok=True)

with open(log, "w", encoding="utf-8") as out, open(err, "w", encoding="utf-8") as eout:
    proc = subprocess.Popen(
        [sys.executable, str(script), "--start-date", "2026-01-01"],
        stdout=out, stderr=eout,
        cwd=str(ROOT),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"Backfill started, PID={proc.pid}")
    print(f"Log: {log}")
    print(f"Check progress: Get-Content {log} -Tail 3")
