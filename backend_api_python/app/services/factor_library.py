"""Factor library — low-position, volume surge, strong up, low volatility.

All factors receive:
    bars = {"opens","closes","highs","lows","volumes","dates"}
All arrays are np.ndarray, same length, earliest->latest.
Return: np.ndarray[bool], True = signal triggered at that bar.
"""

import numpy as np


def _sma(series, period):
    if len(series) < period: return np.full(len(series), series[0])
    out = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        out[i] = np.mean(series[i - period + 1 : i + 1])
    return out

def _rsi(closes, period=14):
    if len(closes) < period + 1: return np.full(len(closes), 50.0)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0); losses = np.where(deltas < 0, -deltas, 0)
    avg_g = np.full(len(closes), np.nan); avg_l = np.full(len(closes), np.nan)
    avg_g[period] = np.mean(gains[:period]); avg_l[period] = np.mean(losses[:period])
    for i in range(period + 1, len(closes)):
        avg_g[i] = (avg_g[i-1]*(period-1) + gains[i-1]) / period
        avg_l[i] = (avg_l[i-1]*(period-1) + losses[i-1]) / period
    rs = avg_g / np.maximum(avg_l, 1e-8)
    return 100.0 - 100.0 / (1.0 + rs)

def _linear_slope(y):
    n = len(y)
    if n < 2: return 0.0
    x = np.arange(n, dtype=float)
    valid = ~np.isnan(y)
    if valid.sum() < 2: return 0.0
    return float(np.polyfit(x[valid], y[valid], 1)[0])

def _rolling_max(series, period):
    out = np.full(len(series), np.nan)
    for i in range(len(series)):
        out[i] = np.max(series[max(0, i - period + 1) : i + 1])
    return out

# ── Low-position (5 variants) ──

def low_drawdown(period=60, drawdown_pct=-20):
    """回撤型: close < N日最高 * (1+drawdown_pct/100)."""
    def fn(bars):
        c = bars["closes"]; h = bars["highs"]
        n = len(c)
        if n < period: return np.zeros(n, dtype=bool)
        rh = _rolling_max(h, period)
        return c < rh * (1 + drawdown_pct / 100)
    return fn

def low_ma(ma_period=60):
    """均线型: close < MA(N)."""
    def fn(bars):
        c = bars["closes"]; ma = _sma(c, ma_period)
        return (c < ma) & (~np.isnan(ma))
    return fn

def low_range(range_days=20, max_amplitude_pct=5):
    """横盘型: N日振幅 < X%."""
    def fn(bars):
        c = bars["closes"]; h = bars["highs"]; lo = bars["lows"]
        n = len(c)
        if n < range_days: return np.zeros(n, dtype=bool)
        sig = np.zeros(n, dtype=bool)
        for i in range(range_days - 1, n):
            wc = c[i - range_days + 1 : i + 1]
            wh = h[i - range_days + 1 : i + 1]
            wl = lo[i - range_days + 1 : i + 1]
            amp = (np.max(wh) - np.min(wl)) / np.mean(wc) * 100
            if amp < max_amplitude_pct: sig[i] = True
        return sig
    return fn

def low_rsi(rsi_period=14, oversold=30):
    """RSI型: RSI < oversold."""
    def fn(bars):
        r = _rsi(bars["closes"], rsi_period)
        return (r < oversold) & (~np.isnan(r))
    return fn

def low_bollinger(bb_period=20, bb_std=2.0):
    """布林型: close < 布林下轨 * 1.02."""
    def fn(bars):
        c = bars["closes"]; n = len(c)
        if n < bb_period: return np.zeros(n, dtype=bool)
        ma = _sma(c, bb_period)
        rs = np.full(n, np.nan)
        for i in range(bb_period - 1, n):
            rs[i] = np.std(c[i - bb_period + 1 : i + 1])
        lower = ma - bb_std * rs
        return (c < lower * 1.02) & (~np.isnan(lower))
    return fn

# ── Volume surge ──

def volume_surge(vol_period=5, multiplier=1.5):
    """放量: 当日量 > N日均量 * multiplier."""
    def fn(bars):
        v = bars["volumes"]; n = len(v)
        if n < vol_period: return np.zeros(n, dtype=bool)
        mv = np.full(n, np.nan)
        for i in range(vol_period - 1, n):
            mv[i] = np.mean(v[i - vol_period + 1 : i + 1])
        return (v > mv * multiplier) & (~np.isnan(mv))
    return fn

# ── Strong up (2 variants) ──

def strong_up_slope(ma_period=5, lookback=3):
    """斜率型: 5MA近lookback日斜率>0."""
    def fn(bars):
        c = bars["closes"]; n = len(c)
        if n < ma_period + lookback: return np.zeros(n, dtype=bool)
        ma5 = _sma(c, ma_period); sig = np.zeros(n, dtype=bool)
        for i in range(ma_period + lookback - 1, n):
            w = ma5[i - lookback + 1 : i + 1]
            if not np.isnan(w).any() and _linear_slope(w) > 0:
                sig[i] = True
        return sig
    return fn

def strong_up_direction(ma_period=5):
    """方向型: 5MA今日 > 5MA昨日."""
    def fn(bars):
        c = bars["closes"]; n = len(c)
        if n < ma_period + 2: return np.zeros(n, dtype=bool)
        ma5 = _sma(c, ma_period); sig = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if not np.isnan(ma5[i]) and not np.isnan(ma5[i-1]) and ma5[i] > ma5[i-1]:
                sig[i] = True
        return sig
    return fn

def low_volatility(lookback=20, max_vol_pct=1.5):
    """低波动: 前lookback天(不含当日)日收益率标准差 < max_vol_pct%."""
    def fn(bars):
        c = bars["closes"]; n = len(c)
        if n < lookback + 2: return np.zeros(n, dtype=bool)
        sig = np.zeros(n, dtype=bool)
        for i in range(lookback + 1, n):
            prev = c[i - lookback : i]
            rets = np.diff(prev) / prev[:-1] * 100
            if np.std(rets) < max_vol_pct: sig[i] = True
        return sig
    return fn


def trend_r2(lookback=20, min_r2=0.7):
    """趋势R²: 前lookback日收盘价对数线性拟合R² > min_r2."""
    def fn(bars):
        c = bars["closes"]; n = len(c)
        if n < lookback + 1: return np.zeros(n, dtype=bool)
        sig = np.zeros(n, dtype=bool)
        for i in range(lookback, n):
            window = c[i - lookback : i]
            if np.any(window <= 0): continue
            log_p = np.log(window)
            x = np.arange(lookback, dtype=float)
            valid = ~np.isnan(log_p)
            if valid.sum() < 5: continue
            slope, _ = np.polyfit(x[valid], log_p[valid], 1)
            pred = slope * x + (log_p[valid].mean() - slope * x[valid].mean())
            ss_res = np.sum((log_p[valid] - pred[valid]) ** 2)
            ss_tot = np.sum((log_p[valid] - log_p[valid].mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            if r2 > min_r2: sig[i] = True
        return sig
    return fn
