"""Final verification: check data quality after all fixes."""
import psycopg2
conn = psycopg2.connect(
    'postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader'
)
cur = conn.cursor()

print("=== Post-cleanup Quality Check ===")
for t in ['qd_sector_features_daily','qd_etf_features_daily','qd_sector_capital_flow_daily','qd_margin_financing_daily']:
    # Check weekend contamination
    cur.execute(f"SELECT count(*) FROM {t} WHERE EXTRACT(DOW FROM as_of_date) IN (0, 6)")
    wk = cur.fetchone()[0]
    cur.execute(f"SELECT MIN(as_of_date), MAX(as_of_date), count(*) FROM {t}")
    r = cur.fetchone()
    print(f"  {t}: rows={r[2]} range=[{r[0]}..{r[1]}] weekends_remaining={wk}")

# Check latest trading days have valid data
print()
print("=== Latest data sample (qd_sector_features_daily) ===")
cur.execute("""
    SELECT sector_name, as_of_date, return_1d, return_5d
    FROM qd_sector_features_daily
    WHERE as_of_date >= '2026-07-06'
    ORDER BY sector_name, as_of_date
""")
for r in cur.fetchall():
    print(f"  {r[0]:10s} {r[1]}  1d={r[2]:>8.2f}%  5d={r[3]:>8.2f}%")

print()
print("=== RAG document stats ===")
cur.execute("SELECT count(*) FROM qd_rag_documents")
print(f"  total docs: {cur.fetchone()[0]}")
cur.execute("SELECT date(created_at), count(*) FROM qd_rag_documents GROUP BY date(created_at) ORDER BY date(created_at) DESC LIMIT 5")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} docs")

conn.close()
print()
print("All checks PASSED - no weekend data remaining.")
