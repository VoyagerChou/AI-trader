"""Verify all sector returns after fixes."""
import psycopg2

conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

# Show latest data for all sectors
cur.execute("""
    SELECT sector_name, as_of_date, return_1d, return_5d, amount_ratio_5d, metadata
    FROM qd_sector_features_daily
    WHERE as_of_date = '2026-07-08'
    ORDER BY sector_name
""")
print("=== All sectors on 2026-07-08 ===")
for r in cur.fetchall():
    adj_flag = ""
    try:
        import json
        meta = r[5] if isinstance(r[5], dict) else json.loads(str(r[5])) if r[5] else {}
        if meta.get("adj_event_detected"):
            adj_flag = f" [ADJ EVENT: {meta.get('adj_event_date')} {meta.get('adj_event_pct', 0):.1f}%]"
    except:
        pass
    print(f"  {r[0]:<10}  1d={r[2]:>8.2f}%  5d={r[3]:>8.2f}%  vol={r[4]:.3f}{adj_flag}")

# Also check if any sector still has all zeros
print()
print("=== Sectors with zero returns (missing data) ===")
cur.execute("""
    SELECT DISTINCT sector_name 
    FROM qd_sector_features_daily 
    WHERE as_of_date >= '2026-07-01' 
      AND return_1d = 0 AND return_5d = 0 AND amount_ratio_5d = 0
""")
zeros = [r[0] for r in cur.fetchall()]
if zeros:
    print(f"  WARNING: {zeros}")
else:
    print("  All sectors have real data!")

conn.close()
