import psycopg2
conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

for code, label in [("513770","港股互联网"), ("512710","军工龙头"), ("512170","医疗"), ("512760","芯片"), ("159206","卫星/军工"), ("512660","军工")]:
    cur.execute("SELECT return_1d, return_5d, return_20d, amount_ratio_5d FROM qd_etf_features_daily WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 1", (code,))
    r = cur.fetchone()
    cur.execute("SELECT net_inflow_main, net_inflow_ratio FROM qd_etf_fund_flow_daily WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 1", (code,))
    f = cur.fetchone()
    flow_str = ""
    if f:
        flow_str = f" 主力={f[0]/1e4:.0f}万" if f[0] else " 主力=0"
    result = f"1d={r[0]:+.2f}% 5d={r[1]:+.2f}% 20d={r[2]:+.2f}% vol5d={r[3]:.2f}{flow_str}"
    print(f"{code} {label:10s}: {result}")
conn.close()
