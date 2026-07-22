import psycopg2
conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

months = [
    ("2024-10", "2024-10-01", "2024-10-31"),
    ("2024-11", "2024-11-01", "2024-11-30"),
    ("2024-12", "2024-12-01", "2024-12-31"),
    ("2025-01", "2025-01-01", "2025-01-31"),
    ("2025-02", "2025-02-01", "2025-02-28"),
    ("2025-03", "2025-03-01", "2025-03-31"),
    ("2025-04", "2025-04-01", "2025-04-30"),
    ("2025-05", "2025-05-01", "2025-05-31"),
    ("2025-06", "2025-06-01", "2025-06-30"),
]

for label, s, e in months:
    cur.execute("""
        SELECT etf_code, 
               MIN(close_price) FILTER (WHERE as_of_date = (SELECT MIN(as_of_date) FROM qd_etf_market_bars_daily b2 WHERE b2.etf_code=b.etf_code AND b2.as_of_date>=%s AND b2.as_of_date<=%s)) as first,
               MAX(close_price) FILTER (WHERE as_of_date = (SELECT MAX(as_of_date) FROM qd_etf_market_bars_daily b2 WHERE b2.etf_code=b.etf_code AND b2.as_of_date>=%s AND b2.as_of_date<=%s)) as last
        FROM qd_etf_market_bars_daily b
        WHERE as_of_date>=%s AND as_of_date<=%s AND close_price>0
        GROUP BY etf_code
    """, (s, e, s, e, s, e))
    
    rets = []
    for r in cur.fetchall():
        if r[1] and r[2] and r[1] > 0:
            ret = (r[2] - r[1]) / r[1] * 100
            rets.append((r[0], ret))
    
    rets.sort(key=lambda x: -x[1])
    
    print(f"\n{label}")
    for i, (code, ret) in enumerate(rets[:3], 1):
        # Try to get name
        name = ""
        try:
            cur.execute("SELECT etf_name FROM qd_etf_features_daily WHERE etf_code=%s LIMIT 1", (code,))
            nr = cur.fetchone()
            name = nr[0] if nr else ""
        except:
            pass
        print(f"  #{i} {code} {name[:20] if name else ''}: {ret:+.1f}%")

conn.close()
