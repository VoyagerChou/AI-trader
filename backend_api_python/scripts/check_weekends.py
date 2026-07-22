import psycopg2
conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

# Check by day of week
cur.execute("""
    SELECT EXTRACT(DOW FROM as_of_date) as dow, count(*) 
    FROM qd_etf_market_bars_daily 
    GROUP BY dow ORDER BY dow
""")
for r in cur.fetchall():
    labels = {0:"周日",1:"周一",2:"周二",3:"周三",4:"周四",5:"周五",6:"周六"}
    print(f"  {labels.get(int(r[0]),'?')}: {r[1]} 条")

# Check for any weekend data
cur.execute("""
    SELECT count(*) FROM qd_etf_market_bars_daily 
    WHERE EXTRACT(DOW FROM as_of_date) IN (0, 6)
""")
bad = cur.fetchone()[0]
print(f"\n周末数据: {bad} 条")

# Check sample dates in 2024
cur.execute("""
    SELECT DISTINCT as_of_date FROM qd_etf_market_bars_daily 
    WHERE as_of_date >= '2024-01-01' AND as_of_date < '2024-02-01'
    ORDER BY as_of_date LIMIT 10
""")
print(f"\n2024年1月前10个交易日:")
for r in cur.fetchall():
    print(f"  {r[0]}")

cur.execute("SELECT MIN(as_of_date), MAX(as_of_date) FROM qd_etf_market_bars_daily")
r = cur.fetchone()
print(f"\nK线范围: [{r[0]}..{r[1]}]")
conn.close()
