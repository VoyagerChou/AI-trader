#!/usr/bin/env python3
"""Run daily pipeline and save full JSON report."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.rag_ingest.weekly_sector_pipeline import DailyReportPipeline

pipeline = DailyReportPipeline()
result = pipeline.run(lookback_days=7, doc_limit=100)

print(f"Success: {result.get('success')}")
print(f"Report type: {result.get('report', {}).get('report_type', '?')}")
recs = result.get('report', {}).get('recommendations') or result.get('report', {}).get('rankings', [])
print(f"Recommendations: {len(recs)} ETFs")
if recs:
    for r in recs[:5]:
        print(f"  #{r.get('rank')} {r.get('primary_etf')} {r.get('primary_name','')} | score={r.get('score')}")
        if r.get('related_etfs'):
            print(f"    +related: {', '.join(r['related_etfs'])}")
