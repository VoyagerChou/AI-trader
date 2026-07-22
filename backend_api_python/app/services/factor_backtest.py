"""Multi-factor backtesting framework for ETFs.

Design:
- Factor: a pure function that receives a dict of OHLCV arrays and returns a bool array
- Engine: iterates all ETFs, calls factor(s), records forward N-day returns
- Stats: aggregates results across all ETFs and time periods
- Multi-factor: supports AND/OR resonance testing

Usage:
  from app.services.factor_backtest import FactorBacktester, run_factor_test
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Data Types ───────────────────────────────────────────────────


@dataclass
class TradeRecord:
    """Single trade signal → forward return."""
    etf_code: str
    signal_date: str
    entry_price: float
    exit_price: float
    forward_return: float  # percentage
    forward_days: int
    factor_name: str


@dataclass
class FactorStats:
    """Aggregated statistics for a factor (or factor combination)."""
    factor_name: str
    total_signals: int = 0
    total_etfs: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    median_return: float = 0.0
    max_return: float = 0.0
    max_loss: float = 0.0
    sharpe: float = 0.0
    annualized_return: float = 0.0  # % per year
    max_drawdown: float = 0.0  # % worst peak-to-trough
    profit_factor: float = 0.0
    by_month: Dict[str, float] = field(default_factory=dict)
    by_etf: Dict[str, Dict[str, float]] = field(default_factory=dict)
    return_distribution: List[float] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)  # cumulative return %


# ── Factor Interface ─────────────────────────────────────────────

# A factor takes these arrays (all same length, earliest→latest) and returns a bool array.
# True at index i means "signal triggered at bar i".
# The backtester enters at bar i's close and exits at bar i+forward_days close.
FactorFn = Callable[
    [Dict[str, np.ndarray]],  # {"opens":..., "closes":..., "highs":..., "lows":..., "volumes":...}
    np.ndarray,  # bool array, same length as input
]


# ── Factor Combinators ───────────────────────────────────────────

def factor_and(*factors: FactorFn) -> FactorFn:
    """AND resonance: all factors must signal on the same bar."""
    def combined(bars: Dict[str, np.ndarray]) -> np.ndarray:
        results = [f(bars) for f in factors]
        return np.all(results, axis=0)
    return combined


def factor_or(*factors: FactorFn) -> FactorFn:
    """OR resonance: any factor signal triggers."""
    def combined(bars: Dict[str, np.ndarray]) -> np.ndarray:
        results = [f(bars) for f in factors]
        return np.any(results, axis=0)
    return combined


# ── Backtest Engine ──────────────────────────────────────────────

class FactorBacktester:
    """Multi-factor backtesting engine."""

    def __init__(self, etf_codes: Optional[List[str]] = None):
        self.etf_codes = etf_codes or []

    def run(
        self,
        factor: FactorFn,
        factor_name: str = "unnamed",
        forward_days: int = 5,
        min_bars: int = 60,
        date_range: Optional[Tuple[str, str]] = None,  # ("2024-01-01", "2025-12-31")
    ) -> Tuple[List[TradeRecord], FactorStats]:
        """Run a factor across all ETFs. date_range limits signals to a date window."""
        trades: List[TradeRecord] = []
        etf_count = 0
        range_start, range_end = date_range if date_range else (None, None)

        with get_db_connection() as db:
            cur = db.cursor()

            for code in (self.etf_codes or self._load_etf_list()):
                cur.execute(
                    """SELECT as_of_date, open_price, high_price, low_price, 
                              close_price, volume
                       FROM qd_etf_market_bars_daily
                       WHERE etf_code = %s
                       ORDER BY as_of_date ASC""",
                    (code,),
                )
                rows = cur.fetchall()
                if len(rows) < min_bars:
                    continue

                # Build arrays
                n = len(rows)
                dates = [str(r["as_of_date"]) for r in rows]
                opens = np.array([float(r["open_price"]) for r in rows], dtype=float)
                highs = np.array([float(r["high_price"]) for r in rows], dtype=float)
                lows = np.array([float(r["low_price"]) for r in rows], dtype=float)
                closes = np.array([float(r["close_price"]) for r in rows], dtype=float)
                volumes = np.array([float(r["volume"]) for r in rows], dtype=float)

                # Skip invalid bars
                valid = closes > 0
                if valid.sum() < min_bars:
                    continue

                bars = {"opens": opens, "highs": highs, "lows": lows,
                        "closes": closes, "volumes": volumes, "dates": dates}

                # Run factor
                try:
                    signals = factor(bars)
                except Exception as exc:
                    logger.warning("Factor %s failed on %s: %s", factor_name, code, exc)
                    continue

                # Record trades
                for i in range(len(signals) - forward_days):
                    if not signals[i]:
                        continue
                    sig_date = dates[i] if i < len(dates) else ""
                    # Date range filter
                    if range_start and sig_date < range_start:
                        continue
                    if range_end and sig_date > range_end:
                        continue
                    entry = closes[i]
                    exit_p = closes[i + forward_days]
                    if entry <= 0:
                        continue
                    # Also check exit_date is within range_end if specified
                    exit_date = dates[i + forward_days] if (i + forward_days) < len(dates) else ""
                    if range_end and exit_date > range_end:
                        continue
                    ret = (exit_p - entry) / entry * 100.0
                    trades.append(TradeRecord(
                        etf_code=code,
                        signal_date=dates[i] if i < len(dates) else "",
                        entry_price=round(entry, 4),
                        exit_price=round(exit_p, 4),
                        forward_return=round(ret, 4),
                        forward_days=forward_days,
                        factor_name=factor_name,
                    ))

                etf_count += 1

        return trades, self._compute_stats(trades, factor_name, forward_days, etf_count)

    def run_multi(
        self,
        factors: Dict[str, FactorFn],
        forward_days: int = 5,
        combine: str = "separate",  # "separate", "and", "or"
    ) -> Dict[str, Tuple[List[TradeRecord], FactorStats]]:
        """Run multiple factors. combine="and"/"or" for resonance test."""
        results: Dict[str, Tuple[List[TradeRecord], FactorStats]] = {}

        if combine == "and":
            combined = factor_and(*factors.values())
            name = " AND ".join(factors.keys())
            results[name] = self.run(combined, name, forward_days)
        elif combine == "or":
            combined = factor_or(*factors.values())
            name = " OR ".join(factors.keys())
            results[name] = self.run(combined, name, forward_days)
        else:
            for name, fn in factors.items():
                results[name] = self.run(fn, name, forward_days)

        return results

    def _load_etf_list(self) -> List[str]:
        """Load ETF codes from universe cache."""
        try:
            import json
            from pathlib import Path
            cache = json.loads(
                (Path(__file__).resolve().parents[2] / "cache" / "etf_universe.json")
                .read_text(encoding="utf-8")
            )
            return [e["code"] for e in cache.get("etfs", [])]
        except Exception:
            return []

    def _compute_stats(
        self, trades: List[TradeRecord], name: str, forward_days: int, etf_count: int,
    ) -> FactorStats:
        """Compute aggregated statistics from trade records."""
        stats = FactorStats(factor_name=name, total_signals=len(trades), total_etfs=etf_count)

        if not trades:
            return stats

        returns = [t.forward_return for t in trades]
        stats.return_distribution = returns
        stats.win_rate = sum(1 for r in returns if r > 0) / len(returns)
        stats.avg_return = float(np.mean(returns))
        stats.median_return = float(np.median(returns))
        stats.max_return = max(returns)
        stats.max_loss = min(returns)

        # Sharpe (annualized, assuming daily returns → 252 trading days)
        if len(returns) > 1:
            std = float(np.std(returns))
            stats.sharpe = (stats.avg_return / std) * math.sqrt(252 / forward_days) if std > 0 else 0.0

        # Annualized return: computed from equity curve (not per-trade avg)
        # Equity curve + max drawdown (same-day trades averaged, then compounded)
        if trades:
            from collections import defaultdict as _dd
            by_date = _dd(list)
            for t in trades:
                by_date[t.signal_date].append(t.forward_return)
            
            sorted_dates = sorted(by_date.keys())
            equity = 100.0
            peak = 100.0
            max_dd = 0.0
            curve = []
            for d in sorted_dates:
                daily_rets = by_date[d]
                avg_ret = sum(daily_rets) / len(daily_rets)
                equity *= (1 + avg_ret / 100)
                curve.append(round(equity, 2))
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
            stats.equity_curve = curve
            stats.max_drawdown = round(max_dd, 2)
            
            # Annualized: compound growth from start to end of equity curve
            if len(sorted_dates) >= 2 and curve:
                try:
                    first_d = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
                    last_d = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
                    years = max(0.1, (last_d - first_d).days / 365.25)
                    final = curve[-1]
                    stats.annualized_return = ((final / 100.0) ** (1.0 / years) - 1.0) * 100.0
                except Exception:
                    pass

        # Profit factor
        gains = sum(r for r in returns if r > 0)
        losses = abs(sum(r for r in returns if r < 0))
        stats.profit_factor = gains / losses if losses > 0 else float("inf")

        # By month
        month_returns: Dict[str, List[float]] = defaultdict(list)
        for t in trades:
            if len(t.signal_date) >= 7:
                month = t.signal_date[:7]  # YYYY-MM
                month_returns[month].append(t.forward_return)
        stats.by_month = {m: float(np.mean(v)) for m, v in sorted(month_returns.items())}

        # By ETF
        etf_returns: Dict[str, List[float]] = defaultdict(list)
        for t in trades:
            etf_returns[t.etf_code].append(t.forward_return)
        stats.by_etf = {}
        for code, rets in etf_returns.items():
            stats.by_etf[code] = {
                "signals": len(rets),
                "win_rate": sum(1 for r in rets if r > 0) / len(rets),
                "avg_return": float(np.mean(rets)),
                "sharpe": float(np.mean(rets) / np.std(rets) * math.sqrt(252 / forward_days)) if len(rets) > 1 else 0,
            }

        return stats


# ── Convenience ──────────────────────────────────────────────────

def run_factor_test(
    factor: FactorFn,
    name: str = "unnamed",
    forward_days: int = 5,
    etf_codes: Optional[List[str]] = None,
) -> FactorStats:
    """Quick single-factor test. Returns FactorStats."""
    tester = FactorBacktester(etf_codes)
    _, stats = tester.run(factor, name, forward_days)
    return stats


def _print_ascii_chart(data: List[float], title: str = "", width: int = 50, height: int = 12):
    """Print a simple ASCII line chart of cumulative returns."""
    if len(data) < 2:
        return
    print(f"\n  {title}:")
    # Downsample to fit width
    step = max(1, len(data) // width)
    sampled = [sum(data[i:i+step]) / step for i in range(0, len(data), step)][:width]
    if not sampled:
        return
    y_min, y_max = min(sampled), max(sampled)
    if y_max == y_min:
        y_max = y_min + 1
    scale = height / (y_max - y_min)
    canvas = [[" "] * len(sampled) for _ in range(height + 1)]
    zero_row = int((0 - y_min) * scale) if y_min <= 0 <= y_max else (0 if y_min > 0 else height)
    for x, y in enumerate(sampled):
        row = min(height, max(0, int((y - y_min) * scale)))
        canvas[height - row][x] = "█"
    for row in range(height + 1):
        line = "".join(canvas[row])
        if line.strip():
            label = f"{y_max - row * (y_max - y_min) / height:+6.1f}% " if row % 3 == 0 else "       |"
            print(f"  {label} {line}")
    # X-axis dates
    print(f"  {'─' * (width + 8)}")


def run_is_oos_test(
    factor: FactorFn,
    name: str = "unnamed",
    forward_days: int = 5,
    is_range: Tuple[str, str] = ("2024-01-01", "2025-12-31"),
    oos_range: Tuple[str, str] = ("2026-01-01", "2026-12-31"),
) -> Dict[str, Any]:
    """Run in-sample / out-of-sample split test with PBO estimation.

    Returns dict with IS stats, OOS stats, and degradation metrics.
    """
    tester = FactorBacktester()

    is_trades, is_stats = tester.run(factor, f"{name}_IS", forward_days, date_range=is_range)
    oos_trades, oos_stats = tester.run(factor, f"{name}_OOS", forward_days, date_range=oos_range)

    # Degradation metrics
    is_sharpe = is_stats.sharpe
    oos_sharpe = oos_stats.sharpe
    degradation = (is_sharpe - oos_sharpe) / max(abs(is_sharpe), 0.01) if is_sharpe != 0 else 0

    # PBO estimation (simplified): fraction of IS top-decile trades that underperform
    # IS median in OOS. Higher PBO = more overfitting concern.
    if is_trades and oos_trades:
        is_returns = sorted([t.forward_return for t in is_trades], reverse=True)
        top_10_pct = is_returns[: max(1, len(is_returns) // 10)]
        oos_median = float(np.median([t.forward_return for t in oos_trades]))
        overfit_count = sum(1 for r in top_10_pct if r < oos_median)
        pbo = overfit_count / len(top_10_pct) if top_10_pct else 0.0
    else:
        pbo = 0.0

    # PBO interpretation
    if pbo > 0.7:
        pbo_warning = "高风险：IS表现无法延续到OOS，严重过拟合风险"
    elif pbo > 0.4:
        pbo_warning = "中等风险：IS和OOS有一定关联但不够稳健"
    else:
        pbo_warning = "低风险：IS选出的组合在OOS中仍有效"

    return {
        "factor": name,
        "forward_days": forward_days,
        "is_signals": is_stats.total_signals,
        "is_win_rate": round(is_stats.win_rate, 4),
        "is_avg_return": round(is_stats.avg_return, 2),
        "is_sharpe": round(is_stats.sharpe, 3),
        "is_ann_return": round(is_stats.annualized_return, 1),
        "is_max_dd": is_stats.max_drawdown,
        "oos_signals": oos_stats.total_signals,
        "oos_win_rate": round(oos_stats.win_rate, 4),
        "oos_avg_return": round(oos_stats.avg_return, 2),
        "oos_sharpe": round(oos_stats.sharpe, 3),
        "oos_ann_return": round(oos_stats.annualized_return, 1),
        "oos_max_dd": oos_stats.max_drawdown,
        "degradation": round(degradation, 3),
        "pbo": round(pbo, 3),
        "pbo_warning": pbo_warning,
    }


def print_is_oos(result: Dict[str, Any]) -> None:
    """Pretty-print IS/OOS split results."""
    print(f"\n{'='*60}")
    print(f"  IS/OOS Split Test: {result['factor']}")
    print(f"  {'─'*50}")
    print(f"  {'':20} {'In-Sample':>15} {'Out-of-Sample':>15}")
    print(f"  {'─'*50}")
    print(f"  {'Signals':20} {result['is_signals']:>15} {result['oos_signals']:>15}")
    print(f"  {'Win Rate':20} {result['is_win_rate']*100:>14.1f}% {result['oos_win_rate']*100:>14.1f}%")
    print(f"  {'Avg Return':20} {result['is_avg_return']:>14.2f}% {result['oos_avg_return']:>14.2f}%")
    print(f"  {'Sharpe':20} {result['is_sharpe']:>15.3f} {result['oos_sharpe']:>15.3f}")
    print(f"  {'Ann Return':20} {result['is_ann_return']:>14.1f}% {result['oos_ann_return']:>14.1f}%")
    print(f"  {'Max DD':20} {result['is_max_dd']:>14.1f}% {result['oos_max_dd']:>14.1f}%")
    print(f"  {'─'*50}")
    print(f"  Degradation: {result['degradation']:.3f}  (Sharpe衰减, >0.5=严重)")
    print(f"  PBO: {result['pbo']:.3f}  ({result['pbo_warning']})")


def print_stats(stats: FactorStats) -> None:
    """Pretty-print factor statistics."""
    print(f"\n{'='*60}")
    print(f"  Factor: {stats.factor_name}")
    print(f"  {'─'*50}")
    print(f"  Signals: {stats.total_signals}  ETFs: {stats.total_etfs}")
    print(f"  Win Rate: {stats.win_rate*100:.1f}%")
    print(f"  Avg Return: {stats.avg_return:+.2f}%")
    print(f"  Median: {stats.median_return:+.2f}%")
    print(f"  Max Return: {stats.max_return:+.2f}%")
    print(f"  Max Loss: {stats.max_loss:+.2f}%")
    print(f"  Sharpe: {stats.sharpe:.3f}")
    print(f"  Annualized Return: {stats.annualized_return:+.1f}%")
    print(f"  Max Drawdown: {stats.max_drawdown:.1f}%")
    print(f"  Profit Factor: {stats.profit_factor:.2f}")
    print(f"  {'─'*50}")
    print(f"  Monthly Returns:")
    for m, r in list(stats.by_month.items())[-12:]:
        bar = "+" * max(1, int(r * 2)) if r > 0 else "-" * max(1, int(abs(r) * 2))
        print(f"    {m}: {r:+6.2f}% {bar}")
    print(f"  {'─'*50}")
    if stats.equity_curve and len(stats.equity_curve) > 1:
        _print_ascii_chart(stats.equity_curve, title="Equity Curve")
    """Pretty-print factor statistics."""
    print(f"\n{'='*60}")
    print(f"  Factor: {stats.factor_name}")
    print(f"  {'─'*50}")
    print(f"  Signals: {stats.total_signals}  ETFs: {stats.total_etfs}")
    print(f"  Win Rate: {stats.win_rate*100:.1f}%")
    print(f"  Avg Return: {stats.avg_return:+.2f}%")
    print(f"  Median: {stats.median_return:+.2f}%")
    print(f"  Max Return: {stats.max_return:+.2f}%")
    print(f"  Max Loss: {stats.max_loss:+.2f}%")
    print(f"  Sharpe: {stats.sharpe:.3f}")
    print(f"  Annualized Return: {stats.annualized_return:+.1f}%")
    print(f"  Max Drawdown: {stats.max_drawdown:.1f}%")
    print(f"  Profit Factor: {stats.profit_factor:.2f}")
    print(f"  {'─'*50}")
    print(f"  Monthly Returns:")
    for m, r in list(stats.by_month.items())[-12:]:
        bar = "+" * max(1, int(r * 2)) if r > 0 else "-" * max(1, int(abs(r) * 2))
        print(f"    {m}: {r:+6.2f}% {bar}")
    print(f"  {'─'*50}")
    # ASCII equity curve
    if stats.equity_curve:
        curve = stats.equity_curve
        if len(curve) > 1:
            _print_ascii_chart(curve, title="Equity Curve")
