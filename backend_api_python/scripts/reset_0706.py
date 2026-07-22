"""Delete 2026-07-06 to 2026-07-08 data (re-run with clean trading-day-aware builders)."""
import psycopg2

conn = psycopg2.connect(
    'postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader'
)
cur = conn.cursor()

tables = [
    'qd_sector_features_daily',
    'qd_etf_features_daily',
    'qd_sector_capital_flow_daily',
    'qd_margin_financing_daily',
]

for t in tables:
    cur.execute(f"DELETE FROM {t} WHERE as_of_date >= '2026-07-06'")
    print(f"{t}: DELETED {cur.rowcount} rows since 2026-07-06")
    cur.execute(f"SELECT count(*) FROM {t}")
    print(f"  remaining: {cur.fetchone()[0]}")

conn.commit()
conn.close()
print("Done")
