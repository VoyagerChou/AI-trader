"""Strategy engine — momentum rotation and future strategy implementations.

Each strategy is a pure function: (data, params) → rankings.
LLM advisor sits upstream, providing params based on market conditions.
Pipeline orchestrates the flow.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.sector_feature_service import get_sector_feature_service
from app.services.etf_universe import get_etf_universe_service
from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _log_return(prices: List[float]) -> List[float]:
    """Compute log returns: ln(p_t / p_{t-1})."""
    return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]


def _linear_fit_r2(series: List[float]) -> tuple:
    """Linear regression on [0, 1, 2, ...] vs series. Returns (slope, r_squared)."""
    n = len(series)
    if n < 5:
        return 0.0, 0.0
    x = np.arange(n, dtype=float)
    y = np.array(series, dtype=float)
    # Remove NaN
    mask = ~np.isnan(y)
    if mask.sum() < 5:
        return 0.0, 0.0
    x, y = x[mask], y[mask]
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, max(0.0, r2)


def _load_etf_closes(etf_codes: List[str], lookback: int = 30) -> Dict[str, List[float]]:
    """Load daily close prices from qd_etf_market_bars_daily."""
    from app.utils.db import get_db_connection

    result: Dict[str, List[float]] = {}
    with get_db_connection() as db:
        cur = db.cursor()
        for code in etf_codes:
            cur.execute(
                """SELECT close_price FROM qd_etf_market_bars_daily
                   WHERE etf_code = %s
                   ORDER BY as_of_date DESC
                   LIMIT %s""",
                (code, lookback + 5),
            )
            rows = cur.fetchall()
            closes = [_safe_float(r["close_price"]) for r in reversed(rows)]
            closes = [c for c in closes if c > 0]
            if len(closes) >= 10:
                result[code] = closes
    return result


# ── Momentum Rotation Strategy ───────────────────────────────────

def run_triple_screen(
    etf_codes: List[str],
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Triple Screen Trading System adapted for ETF weekly rotation.

    Screen 1 (Trend): MACD histogram > 0 → uptrend, < 0 → downtrend
    Screen 2 (Timing): In uptrend, RSI < oversold = pullback buy.
                       In downtrend, RSI > overbought = bounce sell.
    Screen 3 (Entry): Price breaks above yesterday's high (long)
                      or below yesterday's low (short).
    """
    p = {**DEFAULT_TRIPLE_SCREEN_PARAMS, **(params or {})}
    rsi_period = int(p.get("rsi_period", 14))
    rsi_os = float(p.get("rsi_oversold", 35))
    rsi_ob = float(p.get("rsi_overbought", 65))
    min_bars = int(p.get("min_bars", 50))

    # Load ETF names
    name_map: Dict[str, str] = {}
    try:
        universe = get_etf_universe_service()
        for e in universe.get_etf_list():
            name_map[e["code"]] = e.get("name", "")
    except Exception:
        pass

    # Load OHLCV bars
    from app.utils.db import get_db_connection
    results: List[Dict[str, Any]] = []

    with get_db_connection() as db:
        cur = db.cursor()
        for code in etf_codes:
            cur.execute(
                """SELECT close_price, high_price, low_price, volume
                   FROM qd_etf_market_bars_daily
                   WHERE etf_code=%s ORDER BY as_of_date ASC""",
                (code,),
            )
            rows = cur.fetchall()
            if len(rows) < min_bars:
                continue

            closes = [_safe_float(r["close_price"]) for r in rows]
            highs = [_safe_float(r["high_price"]) for r in rows]
            lows = [_safe_float(r["low_price"]) for r in rows]
            volumes = [_safe_float(r["volume"]) for r in rows]

            # ── Screen 1: MACD Trend ──
            macd = _compute_macd(closes)
            hist_now = macd["histogram"][-1]
            hist_prev = macd["histogram"][-2] if len(macd["histogram"]) >= 2 else hist_now
            trend = "uptrend" if hist_now > 0 else "downtrend"
            trend_strength = "strong" if abs(hist_now) > abs(hist_prev) else "weakening"

            # ── Screen 2: RSI Timing ──
            rsi_values = _compute_rsi(closes, rsi_period)
            rsi_now = rsi_values[-1]

            # ── Screen 3: Price Breakout ──
            close_now = closes[-1]
            close_yest = closes[-2] if len(closes) >= 2 else close_now
            high_yest = highs[-2] if len(highs) >= 2 else close_now
            low_yest = lows[-2] if len(lows) >= 2 else close_now
            high_prev = highs[-1]
            vol_now = volumes[-1]
            vol_avg5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else vol_now

            # Entry signal determination
            signal = "none"
            signal_score = 0.0

            if trend == "uptrend":
                if rsi_now < rsi_os:
                    # Pullback in uptrend - check if bounce is starting
                    if close_now > high_yest:
                        signal = "oversold_bounce"
                        signal_score = 3.0
                    elif rsi_now < rsi_os:
                        signal = "oversold_waiting"
                        signal_score = 1.0
                elif close_now > high_yest and vol_now > vol_avg5:
                    signal = "breakout"
                    signal_score = 2.0
                else:
                    signal = "holding"
                    signal_score = 0.5

            elif trend == "downtrend":
                if rsi_now > rsi_ob and close_now < low_yest:
                    signal = "overbought_fade"
                    signal_score = -1.0
                else:
                    signal = "avoid"
                    signal_score = -2.0

            # Composite score: trend * 5 + signal_score + volume bonus
            trend_bonus = 5.0 if trend == "uptrend" else -5.0
            vol_bonus = min(2.0, (vol_now / max(vol_avg5, 1)) - 1.0)
            composite = trend_bonus + signal_score + vol_bonus

            results.append({
                "code": code,
                "name": name_map.get(code, ""),
                "trend": trend,
                "trend_strength": trend_strength,
                "rsi": round(rsi_now, 1),
                "macd_hist": round(hist_now, 6),
                "signal": signal,
                "composite_score": round(composite, 2),
                "close": close_now,
                "high_yest": high_yest,
                "vol_ratio": round(vol_now / max(vol_avg5, 1), 2),
            })

    results.sort(key=lambda x: -x["composite_score"])
    return results

# ── SuperTrend Enhanced Momentum ──────────────────────────────────

def _compute_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return [0.0] * len(closes)
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    atr = [sum(tr[:period])/period] * period
    for i in range(period, len(tr)):
        atr.append((atr[-1]*(period-1)+tr[i])/period)
    return [atr[0]] + atr

def _compute_super_trend(highs, lows, closes, atr_period=14, multiplier=2.0):
    n = len(closes)
    atr = _compute_atr(highs, lows, closes, atr_period)
    midline = [(highs[i]+lows[i])/2.0 for i in range(n)]
    upper, lower, direction = [0.0]*n, [0.0]*n, [0]*n
    for i in range(1, n):
        up = midline[i] - multiplier*atr[i]
        dn = midline[i] + multiplier*atr[i]
        upper[i] = up if (up > upper[i-1] or closes[i-1] > upper[i-1]) else upper[i-1]
        lower[i] = dn if (dn < lower[i-1] or closes[i-1] < lower[i-1]) else lower[i-1]
        if closes[i] > lower[i-1]: direction[i] = 1
        elif closes[i] < upper[i-1]: direction[i] = -1
        else: direction[i] = direction[i-1]
    return {"upper": upper, "lower": lower, "direction": direction, "atr": atr}

SUPERTREND_DEFAULTS = {"atr_period":14,"atr_multiplier":2.0,"breakout_period":10,
    "radius_strength":0.02,"trailing_stop_rate":15.0,"min_bars":50,"top_n":20}

def run_super_trend(etf_codes, params=None):
    p = {**SUPERTREND_DEFAULTS, **(params or {})}
    atr_p, atr_m = int(p["atr_period"]), float(p["atr_multiplier"])
    brk, rad, trl = int(p["breakout_period"]), float(p["radius_strength"]), float(p["trailing_stop_rate"])
    min_b = int(p["min_bars"])
    name_map = {}
    try:
        for e in get_etf_universe_service().get_etf_list():
            name_map[e["code"]] = e.get("name","")
    except: pass
    from app.utils.db import get_db_connection
    results = []
    with get_db_connection() as db:
        cur = db.cursor()
        for code in etf_codes:
            cur.execute("SELECT close_price,high_price,low_price,open_price,volume FROM qd_etf_market_bars_daily WHERE etf_code=%s ORDER BY as_of_date ASC",(code,))
            rows = cur.fetchall()
            if len(rows) < min_b: continue
            cl = [_safe_float(r["close_price"]) for r in rows]
            hi = [_safe_float(r["high_price"]) for r in rows]
            lo = [_safe_float(r["low_price"]) for r in rows]
            op = [_safe_float(r["open_price"]) for r in rows]
            vl = [_safe_float(r["volume"]) for r in rows]
            n = len(cl)
            st = _compute_super_trend(hi, lo, cl, atr_p, atr_m)
            sd = st["direction"]
            # Curved band
            cb = [0.0]*n; streak = 0
            for i in range(1,n):
                if sd[i]==1: streak=max(0,streak)+1; cb[i]=cb[i-1]+rad*streak
                elif sd[i]==-1: streak=0 if streak>0 else streak-1; cb[i]=cb[i-1]-rad*abs(streak)
                else: cb[i]=cb[i-1]
            sb = _compute_ema(cb,5)
            # Inflection
            inf = [0]*n
            for i in range(1,n):
                if cb[i]>0 and cb[i-1]<=0: inf[i]=1
                elif cb[i]<0 and cb[i-1]>=0: inf[i]=-1
            # Breakout levels
            nh = [max(hi[max(0,i-brk):i+1]) for i in range(n)]
            nl = [min(lo[max(0,i-brk):i+1]) for i in range(n)]
            # Entry signals
            el, es = [False]*n, [False]*n
            for i in range(2,n):
                pv=i-1
                if inf[pv]==1 and cl[pv]>=nh[pv-1] and sd[pv]==1: el[i]=True
                if inf[pv]==-1 and cl[pv]<=nl[pv-1] and sd[pv]==-1: es[i]=True
            # Dynamic stop
            entry_b = -1
            for i in range(n-1,0,-1):
                if el[i]: entry_b=i; break
            stop_level, stop_pct = None, None
            if entry_b>0:
                low_since = min(cl[entry_b:])
                k = max(0.5, 1.0-0.1*(n-entry_b))
                stop_level = low_since - (op[entry_b]*trl/1000.0)*k
                if cl[-1]>0: stop_pct = (cl[-1]-stop_level)/cl[-1]*100
            trend_now = "long" if sd[-1]==1 else ("short" if sd[-1]==-1 else "neutral")
            sig_bonus = 3.0 if el[-1] else (0.5 if es[-1] else 0.0)
            composite = round(cb[-1]*10.0 + sig_bonus, 2)
            va = vl[-1]
            va5 = sum(vl[-6:-1])/5 if len(vl)>=6 else va
            results.append({"code":code,"name":name_map.get(code,""),"trend":trend_now,
                "curve_momentum":round(cb[-1],4),"inflection":inf[-1]!=0,
                "entry_signal":el[-1] or es[-1],"entry_type":"long" if el[-1] else ("short" if es[-1] else "none"),
                "composite_score":composite,"close":cl[-1],
                "atr":round(st["atr"][-1],4),"st_upper":round(st["upper"][-1],3),
                "st_lower":round(st["lower"][-1],3),"stop_level":round(stop_level,3) if stop_level else None,
                "stop_pct":round(stop_pct,1) if stop_pct else None,
                "vol_ratio":round(va/max(va5,1),2),
                "bars_since_entry":(n-entry_b) if entry_b>0 else None})
    results.sort(key=lambda x:-x["composite_score"])
    return results

# ── MA Slope Strategy ───────────────────────────────────────────

def _compute_sma(series, period):
    if len(series) < period: return [series[-1]]*len(series)
    sma = []
    for i in range(len(series)):
        start = max(0, i-period+1)
        sma.append(sum(series[start:i+1])/(i-start+1))
    return sma

MASLOPE_DEFAULTS = {"ma_period":20,"slope_period":5,"breakout_period":10,
    "trailing_stop_rate":15.0,"min_bars":50,"top_n":20}

def run_ma_slope(etf_codes, params=None):
    p = {**MASLOPE_DEFAULTS, **(params or {})}
    ma_p, sl_p = int(p["ma_period"]), int(p["slope_period"])
    brk, trl = int(p["breakout_period"]), float(p["trailing_stop_rate"])
    min_b = int(p["min_bars"])
    name_map = {}
    try:
        for e in get_etf_universe_service().get_etf_list(): name_map[e["code"]]=e.get("name","")
    except: pass
    from app.utils.db import get_db_connection
    results = []
    with get_db_connection() as db:
        cur=db.cursor()
        for code in etf_codes:
            cur.execute("SELECT close_price,high_price,low_price,open_price,volume FROM qd_etf_market_bars_daily WHERE etf_code=%s ORDER BY as_of_date ASC",(code,))
            rows=cur.fetchall()
            if len(rows)<min_b: continue
            cl=[_safe_float(r["close_price"]) for r in rows]
            hi=[_safe_float(r["high_price"]) for r in rows]
            lo=[_safe_float(r["low_price"]) for r in rows]
            op=[_safe_float(r["open_price"]) for r in rows]
            vl=[_safe_float(r["volume"]) for r in rows]
            n=len(cl)
            # MA and slope
            ma=_compute_sma(cl,ma_p)
            # MA slope = (MA[t] - MA[t-sl_p]) / sl_p  (rate of change)
            ma_slope=[0.0]*n
            for i in range(sl_p,n):
                if ma[i-sl_p]>0: ma_slope[i]=(ma[i]-ma[i-sl_p])/ma[i-sl_p]*100
            # Trend: slope > threshold = uptrend
            trend=["neutral"]*n
            for i in range(1,n):
                if ma_slope[i]>0.1: trend[i]="uptrend"
                elif ma_slope[i]<-0.1: trend[i]="downtrend"
                else: trend[i]="neutral"
            # Breakout levels
            nh=[max(hi[max(0,i-brk):i+1]) for i in range(n)]
            nl=[min(lo[max(0,i-brk):i+1]) for i in range(n)]
            # 5MA for add-position check
            ma5=_compute_sma(cl,5)
            # Entry signals
            entry_long=[False]*n; entry_short=[False]*n
            add_long=[False]*n
            for i in range(2,n):
                pv=i-1
                # Long: uptrend + close breaks N-high
                if trend[pv]=="uptrend" and cl[pv]>=nh[pv-1]: entry_long[i]=True
                # Short: downtrend + close breaks N-low
                if trend[pv]=="downtrend" and cl[pv]<=nl[pv-1]: entry_short[i]=True
                # Add: holding long + close above entry but below 5MA + bullish candle
                if entry_long[i] or (i>0 and entry_long[i-1]):
                    if cl[i-1]>cl[max(0,i-5)] and cl[pv]>ma5[max(0,pv-2)] and cl[pv]<ma5[pv]: add_long[i]=True
            # Dynamic stop
            entry_b=-1
            for i in range(n-1,0,-1):
                if entry_long[i]: entry_b=i; break
            stop_lvl,stop_pct=None,None
            if entry_b>0:
                low_since=min(cl[entry_b:])
                k=max(0.3,1.0-0.07*(n-entry_b))
                stop_lvl=low_since-(op[entry_b]*trl/1000.0)*k
                if cl[-1]>0: stop_pct=(cl[-1]-stop_lvl)/cl[-1]*100
            # Slope strength
            slope_now=ma_slope[-1]
            trend_now=trend[-1]
            sig_bonus=3.0 if entry_long[-1] else (0.5 if entry_short[-1] else 0.0)
            composite=round(slope_now*5.0+sig_bonus,2)
            va=vl[-1]; va5=sum(vl[-6:-1])/5 if len(vl)>=6 else va
            results.append({"code":code,"name":name_map.get(code,""),"trend":trend_now,
                "ma_slope":round(slope_now,4),"slope_strength":"strong" if abs(slope_now)>0.5 else "weak",
                "entry_signal":entry_long[-1] or entry_short[-1],"entry_type":"long" if entry_long[-1] else ("short" if entry_short[-1] else "none"),
                "add_signal":add_long[-1],"composite_score":composite,"close":cl[-1],
                "stop_level":round(stop_lvl,3) if stop_lvl else None,"stop_pct":round(stop_pct,1) if stop_pct else None,
                "vol_ratio":round(va/max(va5,1),2),"bars_since_entry":(n-entry_b) if entry_b>0 else None})
    results.sort(key=lambda x:-x["composite_score"])
    return results

# ── Hilbert Transform Regime Timing ─────────────────────────────

def _wma4(series):
    """4-bar Weighted Moving Average (weights 4,3,2,1)."""
    if len(series) < 4: return series[:]
    out = [0.0]*(len(series))
    for i in range(3, len(series)):
        out[i] = (4*series[i] + 3*series[i-1] + 2*series[i-2] + series[i-3]) / 10.0
    return out

HILBERT_DEFAULTS = {"min_bars": 60}

def run_hilbert_regime(etf_codes, params=None):
    """Hilbert Transform Regime Timing — extracts market cycle and trend state.

    Computes instantaneous period from price using Ehlers' Hilbert Transform.
    The measured period controls an adaptive EMA, which feeds into a three-layer
    timing filter: trend check → state machine → range breakout.
    
    Returns regime assessment for the broad market (top ETFs).
    """
    p = {**HILBERT_DEFAULTS, **(params or {})}
    min_b = int(p["min_bars"])
    # Use top broad-market ETFs (search by name or code prefix)
    broad_codes = []
    for code in etf_codes:
        name = ""
        try:
            for e in get_etf_universe_service().get_etf_list():
                if e["code"] == code: name = e.get("name",""); break
        except: pass
        # Broad market ETFs: 50/300/500/创业板/科创/半导体/银行
        broad_kw = ["上证50","沪深300","中证500","创业板","科创50","半导体","银行","芯片"]
        if code in ("510050","510300","510500","159915","588000","512480","512800"):
            broad_codes.append(code)
        elif any(kw in name for kw in broad_kw) and code not in broad_codes:
            broad_codes.append(code)
    if len(broad_codes) < 3:
        broad_codes = etf_codes[:8]  # absolute fallback
    
    from app.utils.db import get_db_connection
    # Aggregate: compute Hilbert on each broad ETF, average the results
    all_periods = []
    all_trends = []
    all_signals = []
    
    with get_db_connection() as db:
        cur = db.cursor()
        for code in broad_codes:
            cur.execute("SELECT close_price FROM qd_etf_market_bars_daily WHERE etf_code=%s ORDER BY as_of_date ASC",(code,))
            rows = cur.fetchall()
            if len(rows) < min_b: continue
            cl = [_safe_float(r["close_price"]) for r in rows]
            n = len(cl)
            
            # ── Hilbert Transform (Ehlers) ──
            # Smooth price
            smooth = _wma4(cl)
            # Detrender: price - price[7]
            detrender = [0.0]*n
            for i in range(7, n): detrender[i] = smooth[i] - smooth[i-7]
            # Q1 (quadrature)
            q1 = [0.0]*n
            for i in range(6, n):
                q1[i] = (detrender[i]-detrender[i-2])*0.0962 + (detrender[i-2]-detrender[i-4])*0.5769
            # I1 (in-phase) = detrender[3]
            i1 = [0.0]*n
            for i in range(3, n): i1[i] = detrender[i-3]
            # Smooth I1 and Q1
            ji = _wma4(i1)
            jq = _wma4(q1)
            # Phase, delta phase, period
            phase = [0.0]*n
            delta_phase = [0.0]*n
            inst_period = [0.0]*n
            for i in range(6, n):
                if abs(i1[i]) > 1e-8:
                    phase[i] = math.atan(abs(jq[i] / i1[i]))
                # Delta phase
                dp = phase[i-1] - phase[i]
                if dp < 0.1: dp = 0.1
                delta_phase[i] = dp
                # Instantaneous period
                if delta_phase[i] > 0:
                    inst_period[i] = 6.28318 / delta_phase[i]
                inst_period[i] = max(6, min(50, inst_period[i]))  # clamp
            
            # ── Adaptive EMA (α = 2/(period+1)) ──
            alpha = [0.0]*n
            for i in range(1, n):
                alpha[i] = min(0.5, 2.0 / (inst_period[i] + 1)) if inst_period[i] > 0 else 0.2
            # Adaptive smoothing
            adaptive_ema = [cl[0]]*n
            for i in range(1, n):
                adaptive_ema[i] = alpha[i]*cl[i] + (1-alpha[i])*adaptive_ema[i-1]
            
            # ── Trend State ──
            trend = ["neutral"]*n
            for i in range(1, n):
                if adaptive_ema[i] > adaptive_ema[i-1] and inst_period[i] > 20:
                    trend[i] = "trending_up"
                elif adaptive_ema[i] < adaptive_ema[i-1] and inst_period[i] > 20:
                    trend[i] = "trending_down"
                elif inst_period[i] <= 20:
                    trend[i] = "ranging"
                else:
                    trend[i] = trend[i-1]
            
            # ── Range Breakout ──
            # 10-bar high/low breakout zone
            signal = ["none"]*n
            for i in range(10, n):
                range_high = max(cl[i-10:i])
                range_low = min(cl[i-10:i])
                if trend[i] == "trending_up" and cl[i] > range_high:
                    signal[i] = "breakout_long"
                elif trend[i] == "trending_down" and cl[i] < range_low:
                    signal[i] = "breakout_short"
                elif trend[i] == "ranging":
                    if cl[i] > 0.7*range_high and cl[i] < range_high:
                        signal[i] = "range_top"
                    elif cl[i] < 1.3*range_low and cl[i] > range_low:
                        signal[i] = "range_bottom"
            
            # Collect results
            all_periods.append(inst_period[-1])
            final_trend = trend[-1]
            all_trends.append(final_trend)
            all_signals.append(signal[-1])
    
    # ── Aggregate regime ──
    avg_period = sum(all_periods) / max(1, len(all_periods))
    trend_counts = {}
    for t in all_trends: trend_counts[t] = trend_counts.get(t, 0) + 1
    dominant_trend = max(trend_counts, key=trend_counts.get) if trend_counts else "unknown"
    
    regime = "trending" if avg_period > 25 else "ranging"
    regime_detail = f"周期={avg_period:.1f}bar, 主导趋势={dominant_trend}"
    
    # Recommended strategy weights based on regime
    if regime == "trending":
        if dominant_trend == "trending_up":
            strategy_weights = {"super_trend": 1.5, "triple_screen": 1.2, "ma_slope": 1.3}
            suggestion = "当前处于上升趋势市（周期>25），建议增加趋势跟踪策略权重。超级趋势和均线斜率策略优先。"
        else:
            strategy_weights = {"super_trend": 0.5, "triple_screen": 0.5, "ma_slope": 0.5}
            suggestion = "当前处于下降趋势市（周期>25），做多策略应减仓观望。等待周期收敛或趋势反转信号后再入场。"
    else:
        strategy_weights = {"super_trend": 0.7, "triple_screen": 1.0, "ma_slope": 0.8}
        suggestion = "当前处于震荡市（周期<25），趋势策略可能频繁止损。建议降低仓位、收紧止损、等待趋势确认。"
    
    return {
        "regime": regime,
        "avg_period": round(avg_period, 1),
        "dominant_trend": dominant_trend,
        "trend_counts": trend_counts,
        "signals": list(set(all_signals)),
        "detail": regime_detail,
        "strategy_weights": strategy_weights,
        "suggestion": suggestion,
        "broad_etfs": len(broad_codes),
    }

# ── Tank300 Micro-Cap Rotation (adapted for ETFs) ─────────────

TANK300_DEFAULTS = {"max_ret_20d":40.0,"max_ret_5d":30.0,"top_n":8,
    "stoploss_hard":10.0,"stoploss_market":5.0,"min_bars":30}

def run_tank300(etf_codes, params=None):
    """Tank300 strategy adapted for ETFs.

    Core logic:
    1. Anti-chasing: exclude ETFs with 20d>40% or 5d>30% (prevents buying into pumps)
    2. Sort by turnover (small=higher alpha potential, like small-cap)
    3. Top N picks
    4. Stop-loss: 10% hard + 5% market trend (from Hilbert or simple MA)
    """
    p = {**TANK300_DEFAULTS, **(params or {})}
    max_20d, max_5d = float(p["max_ret_20d"]), float(p["max_ret_5d"])
    top_n = int(p["top_n"])
    sl_hard = float(p["stoploss_hard"]) / 100.0
    name_map = {}
    try:
        for e in get_etf_universe_service().get_etf_list(): name_map[e["code"]]=e.get("name","")
    except: pass
    from app.utils.db import get_db_connection
    store = get_sector_feature_service()
    results = []
    with get_db_connection() as db:
        cur = db.cursor()
        for code in etf_codes:
            feats = store.list_etf_features(etf_code=code, limit=5)
            if len(feats) < 3: continue
            f = feats[0]  # latest
            ret_20d = _safe_float(f.get("return_20d"))
            ret_5d = _safe_float(f.get("return_5d"))
            ret_1d = _safe_float(f.get("return_1d"))
            vol_5d = _safe_float(f.get("amount_ratio_5d"))
            turnover = _safe_float(f.get("turnover_amount"))
            close = _safe_float(f.get("close_price"))
            if close <= 0: continue
            
            # Anti-chasing filter
            if ret_20d > max_20d or ret_5d > max_5d: continue
            
            # Skip non-equity
            name = name_map.get(code,"")
            if any(kw in name for kw in ["货币","添利","国债","债"]): continue
            
            # Get bars for stop-loss computation
            cur.execute("SELECT close_price FROM qd_etf_market_bars_daily WHERE etf_code=%s ORDER BY as_of_date ASC",(code,))
            rows = cur.fetchall()
            if len(rows) < 30: continue
            closes = [_safe_float(r["close_price"]) for r in rows]
            n = len(closes)
            
            # Market trend: recent 20-bar high
            high_20 = max(closes[-20:]) if n >= 20 else closes[-1]
            low_5 = min(closes[-5:]) if n >= 5 else closes[-1]
            trend_pct = (close - high_20) / close * 100  # distance from 20d high
            
            # Stop-loss levels
            sl_h = close * (1 - sl_hard)
            sl_m = high_20 * (1 - sl_hard * 0.5)
            
            # Composite score: higher = better (lower turnover + positive recent + not overbought)
            # Small turnover = less crowded, similar to small-cap alpha
            vol_penalty = max(0, vol_5d - 1.5) * 2  # penalty for excessive volume
            composite = round((-ret_20d * 0.3) + (ret_5d * 0.2) + (-vol_penalty) + 5.0, 2)
            
            results.append({
                "code":code,"name":name,"close":close,
                "ret_20d":round(ret_20d,2),"ret_5d":round(ret_5d,2),"ret_1d":round(ret_1d,2),
                "turnover":turnover,"vol_5d":round(vol_5d,2),
                "stop_loss_hard":round(sl_h,3),"stop_loss_market":round(sl_m,3),
                "trend_pct":round(trend_pct,1),
                "composite_score":composite,
            })
    results.sort(key=lambda x:-x["composite_score"])
    return results[:top_n]

# ── Dynamic ETF Rotation (adapted from dynamic_etf_joinquant.py) ──

DYNAMIC_ETF_DEFAULTS = {"lookback":25,"r2_threshold":0.1,"min_annual_return":-50.0,
    "volume_lookback":5,"volume_threshold":1.0,"enable_loss_filter":True,
    "max_daily_loss":0.90,"top_n":8,"min_bars":60}

def run_dynamic_etf(etf_codes, params=None):
    """Dynamic ETF rotation: momentum scoring via 25-day log return linear fit.
    
    Core logic from dynamic_etf_joinquant.py:
    1. Compute log returns over lookback days
    2. Linear regression: slope = momentum score, R² = trend quality
    3. Multiple filters: R², annualized return, volume, loss
    4. Fixed percentage stop loss
    """
    p = {**DYNAMIC_ETF_DEFAULTS, **(params or {})}
    lookback = int(p["lookback"])
    r2_thresh = float(p["r2_threshold"])
    min_ann = float(p["min_annual_return"])
    vol_lb = int(p["volume_lookback"])
    vol_thresh = float(p["volume_threshold"])
    loss_enabled = bool(p.get("enable_loss_filter", True))
    max_loss = float(p["max_daily_loss"])
    top_n = int(p["top_n"])
    min_b = int(p["min_bars"])
    
    name_map = {}
    try:
        for e in get_etf_universe_service().get_etf_list(): name_map[e["code"]]=e.get("name","")
    except: pass
    from app.utils.db import get_db_connection
    store = get_sector_feature_service()
    results = []
    
    with get_db_connection() as db:
        cur = db.cursor()
        for code in etf_codes:
            name = name_map.get(code,"")
            if any(kw in name for kw in ["货币","添利","国债","债"]): continue
            
            cur.execute("SELECT close_price FROM qd_etf_market_bars_daily WHERE etf_code=%s ORDER BY as_of_date ASC",(code,))
            rows = cur.fetchall()
            if len(rows) < min_b: continue
            closes = [_safe_float(r["close_price"]) for r in rows]
            n = len(closes)
            window = closes[-lookback:]
            
            # Log returns
            if len(window) < 10: continue
            log_rets = [math.log(window[i]/window[i-1]) for i in range(1, len(window))]
            
            # Linear regression slope + R²
            slope, r2 = _linear_fit_r2(log_rets)
            if r2 < r2_thresh: continue
            
            # Annualized return (slope * 252)
            ann_ret = slope * 252
            if ann_ret < min_ann: continue
            
            # Volume filter
            feats = store.list_etf_features(etf_code=code, limit=vol_lb)
            avg_vol = sum(_safe_float(f.get("amount_ratio_5d")) for f in feats[:vol_lb])/max(1,len(feats[:vol_lb]))
            if avg_vol > vol_thresh * 2: continue
            
            # Loss filter: no single day > max_loss% drop in last 3 days
            if loss_enabled:
                daily_rets = [(closes[i]-closes[i-1])/closes[i-1] for i in range(max(1,n-3), n)]
                if any(r < (max_loss-1) for r in daily_rets): continue
            
            # Composite score
            close = closes[-1]
            momentum_score = round(ann_ret * r2 * 100, 2)
            stop_loss = round(close * 0.95, 3)
            
            results.append({
                "code":code,"name":name,"close":close,
                "ann_ret":round(ann_ret*100,1),"r2":round(r2,4),
                "slope":round(slope,6),"momentum_score":momentum_score,
                "avg_vol":round(avg_vol,2),"stop_loss_95":stop_loss,
            })
    
    results.sort(key=lambda x:-x["momentum_score"])
    return results[:top_n]

def run_strategy(
    strategy_name: str = "super_trend",
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Main entry point called by the weekly pipeline."""
    universe = get_etf_universe_service()
    etfs = universe.get_etf_list()
    skip_kw = ["货币"]
    codes = [e["code"] for e in etfs if not any(kw in e.get("name", "") for kw in skip_kw)]

    if strategy_name == "triple_screen":
        rankings = run_triple_screen(codes, params)
    elif strategy_name == "super_trend":
        rankings = run_super_trend(codes, params)
    elif strategy_name == "ma_slope":
        rankings = run_ma_slope(codes, params)
    elif strategy_name == "hilbert_regime":
        rankings = run_hilbert_regime(codes, params)
    elif strategy_name == "tank300":
        rankings = run_tank300(codes, params)
    elif strategy_name == "dynamic_etf":
        rankings = run_dynamic_etf(codes, params)
    else:
        rankings = []

    return {
        "strategy": strategy_name,
        "params": params or {},
        "rankings": rankings,
        "timestamp": datetime.now().isoformat(),
    }
