"""LLM advisor — market condition analysis and strategy parameter suggestion.

The LLM reads the current market data (broad index trends, sector rotation,
volume/flow aggregates) and outputs:
1. Market regime assessment (trend / range / transition)
2. Suggested strategy parameters
3. Early-stage ETF signals (low-base breakout candidates)

This sits upstream of the strategy engine. The engine uses the params blindly;
the LLM provides the intelligence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.llm import LLMService
from app.services.sector_feature_service import get_sector_feature_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _build_market_summary() -> str:
    """Build a concise market data summary for the LLM to analyze."""
    store = get_sector_feature_service()

    lines = ["=== 当前市场数据摘要 ===", ""]

    # Broad market ETF snapshot (use 510050 上证50 as proxy)
    for code, label in [("510050", "上证50"), ("159915", "创业板"), ("512480", "半导体"), ("512800", "银行")]:
        rows = store.list_etf_features(etf_code=code, limit=5)
        if rows:
            r = rows[0]
            lines.append(
                f"  {label}({code}): 近5日涨跌={_safe_float(r.get('return_5d')):.2f}%  "
                f"近1日={_safe_float(r.get('return_1d')):.2f}%  "
                f"成交额比={_safe_float(r.get('amount_ratio_5d')):.2f}  "
                f"20日回撤={_safe_float(r.get('drawdown_from_20d_high')):.2f}%"
            )

    # Fund flow for key ETFs
    lines.append("")
    lines.append("  主力资金流向(近1日):")
    for code in ["512480", "512800", "510050", "159915"]:
        flows = store.get_latest_etf_flow(etf_code=code, limit=1)
        if flows:
            f = flows[0]
            main = _safe_float(f.get("net_inflow_main"))
            ratio = _safe_float(f.get("net_inflow_ratio"))
            lines.append(f"  {code}: 主力净流入={main/1e8:.2f}亿 净占比={ratio:.1f}%")

    # ETF universe breadth
    lines.append("")
    rows = store.list_sector_features(limit=29)
    up_count = sum(1 for r in rows if _safe_float(r.get("return_5d")) > 0)
    lines.append(f"  29行业板块中5日上涨: {up_count}/29")

    return "\n".join(lines)


def _build_strategy_context(strategy_name: str) -> str:
    """Build strategy-specific context for the LLM."""
    if strategy_name == "triple_screen":
        return """
=== 三重滤网策略参数说明 ===

基于Alexander Elder三重滤网交易系统，适配ETF周度轮动：

第一层（趋势）: MACD(12,26,9)柱状图。柱>0=上升趋势，柱<0=下降趋势
第二层（择时）: RSI(14)。上升趋势中RSI超卖=回调买入机会；下降趋势中超买=反弹卖出
第三层（入场）: 价格突破前一日高点（上升趋势）或跌破前一日低点（下降趋势）= 确认信号

信号类型:
- oversold_bounce: 上升趋势+RSI超卖+突破前高 = 最佳买点
- breakout: 上升趋势+放量突破前高 = 追涨
- oversold_waiting: 上升趋势+RSI超卖但未突破 = 等待确认
- avoid: 下降趋势 = 不参与

 可调参数:
- rsi_oversold: RSI超卖阈值(25-40)。趋势强时提高(35-40)，趋势弱时降低(25-30)
- rsi_overbought: RSI超买阈值(60-75)

请根据当前市场数据输出JSON参数建议。
"""
    if strategy_name == "momentum_rotation":
        return """
=== 动量轮动策略参数说明 ===

当前策略: 基于ETF特征表的20日/10日/5日加权收益率排名。
(特征表已处理ETF除权事件，避免原始K线的跳空干扰)

动量分 = 20日收益×0.4 + 10日收益×0.35 + 5日收益×0.25

过滤条件:
- 5日跌幅 < max_drop_5d_pct 的ETF被排除（短期风险）
- 单日涨跌超过阈值的ETF被排除（异常波动）
- 5日成交额比 < min_volume_ratio 的ETF被排除（流动性不足）

可调参数:
- max_drop_5d_pct: 5日最大跌幅容忍度(-15%~0%)。趋势市中放宽(-10%)，震荡市中收紧(-5%)
- max_single_day_surge_pct: 单日涨幅排除线(5%-15%)
- min_volume_ratio: 成交量最低要求(0.2-0.8)

请根据当前市场数据，输出JSON格式的参数建议:
{
  "market_regime": "trend_up" | "trend_down" | "range" | "transition",
  "regime_confidence": 0.0-1.0,
  "params": { ... },
  "early_signals": ["ETF代码列表"],
  "reasoning": "简短的市场研判逻辑(50字)"
}
"""
    if strategy_name == "triple_screen":
        return """
=== 三重滤网策略参数说明 ===

基于Alexander Elder三重滤网交易系统，适配ETF周度轮动：
第一层: MACD(12,26,9), 柱>0=上升趋势
第二层: RSI(14), 超卖=回调买入, 超买=反弹卖出
第三层: 价格突破前日高点/低点确认
信号: oversold_bounce(最佳), breakout(追涨), oversold_waiting(等待), avoid(不参与)
    可调: rsi_oversold(25-40), rsi_overbought(60-75)
"""
    if strategy_name == "super_trend":
        return """
=== 超级趋势增强动量策略 ===

SuperTrend+曲率拐点+动态止损: 三重过滤(拐点+突破+方向确认), K值衰减止损(1.0→0.5)
可调: atr_multiplier(1.5-3.0), breakout_period(5-20), radius_strength(0.01-0.05)
"""
    return ""


def suggest_params(
    strategy_name: str = "momentum_rotation",
    prev_performance: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask LLM to analyze market and suggest strategy parameters.

    Args:
        strategy_name: Which strategy to tune.
        prev_performance: Optional text describing last week's strategy performance.

    Returns:
        Dict with "market_regime", "params", "early_signals", "reasoning".
        Falls back to default params if LLM call fails.
    """
    market_data = _build_market_summary()
    strategy_context = _build_strategy_context(strategy_name)

    prompt = f"""
{strategy_context}

{market_data}

{f"上周策略表现: {prev_performance}" if prev_performance else "首次运行，无历史表现。"}

请严格按照JSON格式输出参数建议（只输出JSON，不要额外文字）。
    """.strip()

    default_result = {
        "market_regime": "range",
        "regime_confidence": 0.5,
        "params": {
            "r2_threshold": 0.1,
            "max_drop_5d_pct": -8.0,
            "max_single_day_surge_pct": 12.0,
            "top_n": 10,
            "min_volume_ratio": 0.3,
        },
        "early_signals": [],
        "reasoning": "LLM不可用，使用默认参数。",
    }

    try:
        llm = LLMService()
        result = llm.safe_call_llm(
            system_prompt="你是A股量化策略参数调优助手。只输出JSON。",
            user_prompt=prompt,
            default_structure=default_result,
        )
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.warning("LLM advisor failed: %s", exc)

    return default_result
