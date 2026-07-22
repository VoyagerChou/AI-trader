#!/usr/bin/env python3
"""Run the weekly sector pipeline and print the full report."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.rag_ingest.weekly_sector_pipeline import WeeklySectorPipeline

pipeline = WeeklySectorPipeline()
result = pipeline.run(lookback_days=7, doc_limit=100)

if result.get("success"):
    report = result.get("report", {})
    
    print("=" * 60)
    print("周报分析报告")
    print("=" * 60)
    print(f"report_type: {report.get('report_type')}")
    print(f"lookback_days: {report.get('lookback_days')}")
    print(f"generated_at: {result.get('generated_at')}")
    print()
    print("--- SUMMARY ---")
    print(report.get("summary", "N/A"))
    print()
    
    # Top sectors
    print("--- TOP SECTORS ---")
    for i, s in enumerate(report.get("top_sectors", []), 1):
        print(f"\n{i}. {s.get('name')} (confidence: {s.get('confidence')})")
        print(f"   Reasons: {json.dumps(s.get('reasons', []), ensure_ascii=False)}")
        print(f"   Sources: {json.dumps(s.get('sources', []), ensure_ascii=False)}")
        print(f"   Risks: {json.dumps(s.get('risks', []), ensure_ascii=False)}")
    
    print()
    print("--- NEXT ACTIONS ---")
    for a in report.get("next_actions", []):
        print(f"  - {a}")
    
    print()
    print("--- INDUSTRY MAINLINE (top 10) ---")
    for row in report.get("industry_mainline", [])[:10]:
        print(f"  {row.get('sector_name')}: score={row.get('total_score')}, docs={row.get('doc_count')}, trend={row.get('trend_score')}")
    
    print()
    print("--- THEME MAINLINE (top 5) ---")
    for row in report.get("theme_mainline", [])[:5]:
        print(f"  {row.get('theme_name')}: score={row.get('total_score')}, docs={row.get('doc_count')}")
    
    print()
    print("--- ETF CANDIDATES ---")
    for e in report.get("etf_candidates", [])[:10]:
        print(f"  {e.get('etf_code')} | {e.get('etf_name')} | theme: {e.get('linked_theme')} | score: {e.get('theme_score')}")
    
    print()
    print("--- DOC COUNT ---")
    print(f"  Recent docs ingested: {result.get('doc_count', 0)}")
    print(f"  Sector evidence entries: {result.get('sector_count', 0)}")
    print(f"  Theme evidence entries: {result.get('theme_count', 0)}")
    
else:
    print(f"Pipeline failed: {json.dumps(result, ensure_ascii=False, indent=2)}")
