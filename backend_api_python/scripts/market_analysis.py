"""Comprehensive market analysis - macro + micro."""
import psycopg2, json, sys, math

conn = psycopg2.connect('postgresql://ai-trader:YOUR_DB_PASSWORD@localhost:5432/ai-trader')
cur = conn.cursor()

print("=" * 70)
print("  市场全景分析（2026-07-10）")
print("=" * 70)

# ══════════════════════════════════════════════
# 1. 宏观：宽基指数趋势
# ══════════════════════════════════════════════
print("\n【一、宏观态：宽基指数趋势】")
print()

broad_markets = [
    ("510050", "上证50", "大盘蓝筹"),
    ("510300", "沪深300", "大盘价值"),
    ("510500", "中证500", "中盘成长"),
    ("159915", "创业板", "成长/小票"),
    ("588000", "科创50", "科技/半导体"),
]
for code, name, style in broad_markets:
    cur.execute("""SELECT return_1d, return_5d, return_20d, amount_ratio_5d, 
                   drawdown_from_20d_high, volatility_5d
                   FROM qd_etf_features_daily 
                   WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 1""", (code,))
    r = cur.fetchone()
    if r:
        trend_dir = "↑" if r[2] > 5 else ("↓" if r[2] < -5 else "→")
        vol_label = "放量" if r[3] > 1.2 else ("缩量" if r[3] < 0.7 else "正常")
        print(f"  {name:<10} {style:<12} | 1日={r[0]:+.2f}% 5日={r[1]:+.2f}% 20日={r[2]:+.2f}%{trend_dir} | 量比={r[3]:.2f}({vol_label}) | 回撤={r[4]:.1f}% 波={r[5]:.1f}%")

# ══════════════════════════════════════════════
# 2. 宏观：行业涨跌比 + 资金流汇总
# ══════════════════════════════════════════════
print("\n【二、宏观态：行业轮动全景】")
cur.execute("""SELECT sector_name, return_5d, return_1d, amount_ratio_5d 
               FROM qd_sector_features_daily 
               WHERE as_of_date='2026-07-10' ORDER BY return_5d DESC""")
sectors = cur.fetchall()
up_count = sum(1 for s in sectors if s[1] and s[1] > 0)

print(f"  29行业中: 5日上涨 {up_count}/29 ({up_count*100//29}%)")
print(f"  Top 5 领涨:")
for s in sectors[:5]:
    print(f"    {s[0]:<12} 5日={s[1]:+.2f}% 1日={s[2]:+.2f}% 量比={s[3]:.2f}")
print(f"  Bottom 5 领跌:")
for s in sectors[-5:]:
    print(f"    {s[0]:<12} 5日={s[1]:+.2f}% 1日={s[2]:+.2f}% 量比={s[3]:.2f}")

# Industry fund flow summary
print()
cur.execute("""SELECT sector_name, net_inflow_main 
               FROM qd_sector_capital_flow_daily 
               WHERE as_of_date='2026-07-10' AND net_inflow_main IS NOT NULL 
               ORDER BY net_inflow_main DESC LIMIT 5""")
flows = cur.fetchall()
if flows:
    print(f"  行业资金流 Top 5 (主力净流入):")
    for f in flows:
        print(f"    {f[0]:<12} +{f[1]/1e8:.2f}亿")

# ══════════════════════════════════════════════
# 3. ETF 资金流极端值
# ══════════════════════════════════════════════
print("\n【三、微观结构：ETF资金流极端信号】")
cur.execute("""SELECT etf_code, etf_name, net_inflow_main, net_inflow_ratio,
               net_inflow_super_large, net_inflow_small
               FROM qd_etf_fund_flow_daily
               WHERE as_of_date='2026-07-10' AND abs(net_inflow_main) > 5e7
               ORDER BY net_inflow_main DESC LIMIT 5""")
print("  主力大幅买入:")
for r in cur.fetchall():
    bias = "机构" if (r[4] or 0) / max(abs(r[2] or 1), 1) > 0.4 else "散户"
    print(f"    {r[0]} {r[1][:16]:<16} +{r[2]/1e8:.2f}亿 占比={r[3]:.1f}% {bias}")

cur.execute("""SELECT etf_code, etf_name, net_inflow_main, net_inflow_ratio,
               net_inflow_super_large
               FROM qd_etf_fund_flow_daily
               WHERE as_of_date='2026-07-10' AND net_inflow_main < -5e7
               ORDER BY net_inflow_main ASC LIMIT 5""")
print("  主力大幅卖出:")
for r in cur.fetchall():
    print(f"    {r[0]} {r[1][:16]:<16} {r[2]/1e8:.2f}亿 占比={r[3]:.1f}%")

# ══════════════════════════════════════════════
# 4. 微观：动量排名头部 + 资金流翻转信号
# ══════════════════════════════════════════════
print("\n【四、微观结构：动量头部ETF + 资金流匹配度】")
cur.execute("""SELECT etf_code, return_20d, return_5d, amount_ratio_5d, 
               return_1d, volatility_5d
               FROM qd_etf_features_daily
               WHERE as_of_date='2026-07-10' AND return_20d > 20
               ORDER BY return_20d DESC LIMIT 10""")
momentum_leaders = cur.fetchall()

print(f"  20日动量>20%的ETF: {len(momentum_leaders)}支")
print()
for r in momentum_leaders:
    code = r[0]
    # Check fund flow for this ETF
    cur.execute("""SELECT net_inflow_main, net_inflow_ratio 
                   FROM qd_etf_fund_flow_daily 
                   WHERE etf_code=%s AND as_of_date='2026-07-10'""", (code,))
    flow = cur.fetchone()
    flow_str = ""
    if flow and flow[0]:
        direction = "买入" if flow[0] > 0 else "卖出"
        flow_str = f" | 主力{direction} {abs(flow[0])/1e8:.2f}亿"
    
    accel = (r[2]/5 - r[1]/20) if r[1] and r[2] else 0
    accel_str = f"加速{accel:+.1f}%/天" if abs(accel) > 0.3 else ""
    vol_label = "放量" if r[3] > 1.2 else ("缩量" if r[3] < 0.7 else "")
    
    print(f"  {code} 20日={r[1]:.1f}% 5日={r[2]:.1f}%{flow_str} {accel_str} {vol_label}")

# ══════════════════════════════════════════════
# 5. 微观：资金流翻转检测
# ══════════════════════════════════════════════
print("\n【五、微观结构：主力资金方向翻转（7/9→7/10）】")
flip_etfs = []
for code_tuple in [(r[0],) for r in momentum_leaders[:5]]:
    code = code_tuple[0]
    cur.execute("""SELECT as_of_date, net_inflow_main 
                   FROM qd_etf_fund_flow_daily 
                   WHERE etf_code=%s ORDER BY as_of_date DESC LIMIT 2""", (code,))
    rows = cur.fetchall()
    if len(rows) == 2:
        yest = rows[0][1] or 0
        prev = rows[1][1] or 0
        if prev > 0 and yest < 0:
            flip_etfs.append((code, prev, yest))

if flip_etfs:
    print("  ⚠️ 以下ETF主力资金昨日买入→今日卖出:")
    for f in flip_etfs:
        print(f"    {f[0]}: 昨日+{f[1]/1e4:.0f}万 → 今日{f[2]/1e4:.0f}万")

conn.close()
