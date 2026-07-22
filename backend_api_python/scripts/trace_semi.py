"""Daily price/volume/fund-flow trace for 7 key semiconductor ETFs."""
import psycopg2, json

conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

codes = ["512480", "159995", "588080", "588170", "589020", "159327", "159558"]
names = {"512480": "半导体ETF", "159995": "芯片ETF", "588080": "科创50ETF",
         "588170": "科创半导体", "589020": "科创设备", "159327": "半导体设备", "159558": "半导体设备(鹏华)"}

for code in codes:
    # 15 daily bars
    cur.execute("""SELECT as_of_date, close_price, open_price, high_price, low_price, volume
                   FROM qd_etf_market_bars_daily 
                   WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 20""", (code,))
    rows = list(reversed(cur.fetchall()))
    
    # Fund flow
    cur.execute("""SELECT as_of_date, net_inflow_main, net_inflow_super_large, net_inflow_ratio
                   FROM qd_etf_fund_flow_daily 
                   WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 10""", (code,))
    flows = {(r[0]): r for r in cur.fetchall()}
    
    # Returns
    cur.execute("""SELECT as_of_date, return_1d, return_5d, amount_ratio_5d
                   FROM qd_etf_features_daily 
                   WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 15""", (code,))
    features = {(r[0]): r for r in cur.fetchall()}
    
    name = names.get(code, code)
    print(f"\n{'='*80}")
    print(f"  {code} {name}")
    print(f"  {'日期':<12} {'开盘':>8} {'收盘':>8} {'最高':>8} {'最低':>8} {'日涨跌':>8} {'成交量':>12} {'主力资金':>12}")
    print(f"  {'-'*76}")
    
    prev_close = None
    for r in rows[-12:]:
        d = str(r[0])
        close = float(r[1])
        open_p = float(r[2])
        high = float(r[3])
        low = float(r[4])
        vol = float(r[5])
        
        chg = f"{(close-open_p)/open_p*100:+.1f}%" if prev_close is None else f"{(close-prev_close)/prev_close*100:+.1f}%"
        
        flow_str = ""
        if d in flows:
            f = flows[d]
            main = f[1] or 0
            flow_str = f"{main/1e4:+.0f}万"
        
        prev_close = close
        
        # Mark volume surges
        vol_mark = ""
        if vol > 1.5e7: vol_mark = " 放量"
        
        print(f"  {d:<12} {open_p:>8.3f} {close:>8.3f} {high:>8.3f} {low:>8.3f} {chg:>8} {vol/1e4:>10.0f}万{vol_mark} {flow_str:>12}")
    
    # Add 7/9 and 7/10 close analysis
    if len(rows) >= 2:
        today = rows[-1]
        yesterday = rows[-2]
        today_close = float(today[1])
        yest_close = float(yesterday[1])
        today_vol = float(today[5])
        yest_vol = float(yesterday[5])
        
        print(f"\n  7/9→7/10: {yest_close:.3f}→{today_close:.3f} ({((today_close-yest_close)/yest_close*100):+.1f}%)")
        print(f"  成交量: {yest_vol/1e4:.0f}万→{today_vol/1e4:.0f}万 ({(today_vol/yest_vol-1)*100:+.0f}%)")
        
        # Check if yesterday was a breakout
        if len(rows) >= 6:
            prev_5_highs = [float(r[3]) for r in rows[-6:-1]]
            max_5d = max(prev_5_highs)
            
            # Check 7/9 pattern
            yest_high = float(yesterday[3])
            yest_close_p = float(yesterday[1])
            yest_open_p = float(yesterday[2])
            yest_vol_ratio = yest_vol / (sum(float(r[5]) for r in rows[-6:-1]) / 5) if len(rows) >= 6 else 0
            
            print(f"  前5日最高: {max_5d:.3f} | 7/9最高: {yest_high:.3f} | 突破{'YES' if yest_close_p > max_5d else 'NO'}")
            
            # 7/10 follow-through
            today_open = float(today[2])
            today_high_p = float(today[3])
            print(f"  7/10: 开={today_open:.3f} 高={today_high_p:.3f} 收={today_close:.3f}")
            if today_open > yest_close_p:
                print(f"  -> 高开 ({((today_open-yest_close_p)/yest_close_p*100):+.1f}%)，收{'阳' if today_close > today_open else '阴'}线")
            else:
                print(f"  -> 低开 ({((today_open-yest_close_p)/yest_close_p*100):+.1f}%)")

conn.close()
