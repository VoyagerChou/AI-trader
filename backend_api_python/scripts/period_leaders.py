"""Find top ETFs by period returns from 2024-10 to 2025-06."""
import psycopg2
conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

periods = [
    ("2024-10", "2024-10-01", "2024-10-31"),
    ("2024-11", "2024-11-01", "2024-11-30"),
    ("2024-12", "2024-12-01", "2024-12-31"),
    ("2025-01", "2025-01-01", "2025-01-31"),
    ("2025-02", "2025-02-01", "2025-02-28"),
    ("2025-03", "2025-03-01", "2025-03-31"),
    ("2025-04", "2025-04-01", "2025-04-30"),
    ("2025-05", "2025-05-01", "2025-05-31"),
    ("2025-06", "2025-06-01", "2025-06-30"),
    ("2024-10~2025-06 全程", "2024-10-01", "2025-06-30"),
]

for label, start, end in periods:
    cur.execute("""
        SELECT etf_code, 
               MIN(close_price) FILTER (WHERE as_of_date = (SELECT MIN(as_of_date) FROM qd_etf_market_bars_daily b2 WHERE b2.etf_code=b.etf_code AND b2.as_of_date>=%s AND b2.as_of_date<=%s)) as first_close,
               MAX(close_price) FILTER (WHERE as_of_date = (SELECT MAX(as_of_date) FROM qd_etf_market_bars_daily b2 WHERE b2.etf_code=b.etf_code AND b2.as_of_date>=%s AND b2.as_of_date<=%s)) as last_close
        FROM qd_etf_market_bars_daily b
        WHERE as_of_date >= %s AND as_of_date <= %s AND close_price > 0
        GROUP BY etf_code
        HAVING MIN(as_of_date) != MAX(as_of_date)
    """, (start, end, start, end, start, end))
    
    results = []
    for r in cur.fetchall():
        if r[1] and r[2] and r[1] > 0:
            ret = (r[2] - r[1]) / r[1] * 100
            results.append((r[0], ret))
    
    if results:
        results.sort(key=lambda x: -x[1])
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"  Top 5:")
        for code, ret in results[:5]:
            print(f"    {code}: {ret:+.1f}%")
        print(f"  Bottom 3:")
        for code, ret in results[-3:]:
            print(f"    {code}: {ret:+.1f}%")

conn.close()
