"""Structured feature storage for A-share sector / ETF research.

First-stage scope:
- daily sector features
- daily ETF features

This layer is designed to sit between raw market data and the weekly research
pipeline. It should make "market position" explicit, instead of forcing the AI
to infer it from text alone.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


class SectorFeatureService:
    """Persistence helper for sector / ETF daily structured features."""

    def __init__(self) -> None:
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_sector_features_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    sector_name VARCHAR(120) NOT NULL,
                    as_of_date DATE NOT NULL,
                    return_1d DECIMAL(12,6) DEFAULT 0,
                    return_3d DECIMAL(12,6) DEFAULT 0,
                    return_5d DECIMAL(12,6) DEFAULT 0,
                    return_10d DECIMAL(12,6) DEFAULT 0,
                    return_20d DECIMAL(12,6) DEFAULT 0,
                    turnover_amount DECIMAL(24,4) DEFAULT 0,
                    amount_ratio_5d DECIMAL(12,6) DEFAULT 0,
                    amount_ratio_20d DECIMAL(12,6) DEFAULT 0,
                    drawdown_from_20d_high DECIMAL(12,6) DEFAULT 0,
                    volatility_5d DECIMAL(12,6) DEFAULT 0,
                    news_count_7d INTEGER DEFAULT 0,
                    policy_count_7d INTEGER DEFAULT 0,
                    theme_heat_score DECIMAL(12,6) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_sector_features_daily UNIQUE (market, sector_name, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_sector_features_daily_date ON qd_sector_features_daily(as_of_date DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_sector_features_daily_sector ON qd_sector_features_daily(sector_name)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_etf_features_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    etf_code VARCHAR(32) NOT NULL,
                    etf_name VARCHAR(255) NOT NULL DEFAULT '',
                    linked_sector VARCHAR(120) NOT NULL DEFAULT '',
                    as_of_date DATE NOT NULL,
                    close_price DECIMAL(24,8) DEFAULT 0,
                    return_1d DECIMAL(12,6) DEFAULT 0,
                    return_3d DECIMAL(12,6) DEFAULT 0,
                    return_5d DECIMAL(12,6) DEFAULT 0,
                    return_10d DECIMAL(12,6) DEFAULT 0,
                    return_20d DECIMAL(12,6) DEFAULT 0,
                    turnover_amount DECIMAL(24,4) DEFAULT 0,
                    etf_avg_amount_5d DECIMAL(24,4) DEFAULT 0,
                    etf_avg_amount_20d DECIMAL(24,4) DEFAULT 0,
                    etf_liquidity_score DECIMAL(12,6) DEFAULT 0,
                    amount_ratio_5d DECIMAL(12,6) DEFAULT 0,
                    amount_ratio_20d DECIMAL(12,6) DEFAULT 0,
                    drawdown_from_20d_high DECIMAL(12,6) DEFAULT 0,
                    volatility_5d DECIMAL(12,6) DEFAULT 0,
                    news_count_7d INTEGER DEFAULT 0,
                    policy_count_7d INTEGER DEFAULT 0,
                    theme_heat_score DECIMAL(12,6) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_etf_features_daily UNIQUE (market, etf_code, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_etf_features_daily_date ON qd_etf_features_daily(as_of_date DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_etf_features_daily_etf ON qd_etf_features_daily(etf_code)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_etf_market_bars_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    etf_code VARCHAR(32) NOT NULL,
                    as_of_date DATE NOT NULL,
                    open_price DECIMAL(24,8) DEFAULT 0,
                    high_price DECIMAL(24,8) DEFAULT 0,
                    low_price DECIMAL(24,8) DEFAULT 0,
                    close_price DECIMAL(24,8) DEFAULT 0,
                    volume DECIMAL(24,4) DEFAULT 0,
                    turnover_amount DECIMAL(24,4) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_etf_market_bars_daily UNIQUE (market, etf_code, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_etf_market_bars_daily_etf_date ON qd_etf_market_bars_daily(etf_code, as_of_date DESC)"
            )
            db.commit()
            cur.close()

    def upsert_sector_feature(self, *, market: str = "CNStock", sector_name: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_sector_features_daily (
                    market, sector_name, as_of_date,
                    return_1d, return_3d, return_5d, return_10d, return_20d,
                    turnover_amount, amount_ratio_5d, amount_ratio_20d,
                    drawdown_from_20d_high, volatility_5d,
                    news_count_7d, policy_count_7d, theme_heat_score,
                    metadata
                ) VALUES (
                    %s, %s, %s::date,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb
                )
                ON CONFLICT (market, sector_name, as_of_date) DO UPDATE SET
                    return_1d = EXCLUDED.return_1d,
                    return_3d = EXCLUDED.return_3d,
                    return_5d = EXCLUDED.return_5d,
                    return_10d = EXCLUDED.return_10d,
                    return_20d = EXCLUDED.return_20d,
                    turnover_amount = EXCLUDED.turnover_amount,
                    amount_ratio_5d = EXCLUDED.amount_ratio_5d,
                    amount_ratio_20d = EXCLUDED.amount_ratio_20d,
                    drawdown_from_20d_high = EXCLUDED.drawdown_from_20d_high,
                    volatility_5d = EXCLUDED.volatility_5d,
                    news_count_7d = EXCLUDED.news_count_7d,
                    policy_count_7d = EXCLUDED.policy_count_7d,
                    theme_heat_score = EXCLUDED.theme_heat_score,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    market,
                    sector_name,
                    as_of_date,
                    float(payload.get("return_1d") or 0),
                    float(payload.get("return_3d") or 0),
                    float(payload.get("return_5d") or 0),
                    float(payload.get("return_10d") or 0),
                    float(payload.get("return_20d") or 0),
                    float(payload.get("turnover_amount") or 0),
                    float(payload.get("amount_ratio_5d") or 0),
                    float(payload.get("amount_ratio_20d") or 0),
                    float(payload.get("drawdown_from_20d_high") or 0),
                    float(payload.get("volatility_5d") or 0),
                    int(payload.get("news_count_7d") or 0),
                    int(payload.get("policy_count_7d") or 0),
                    float(payload.get("theme_heat_score") or 0),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def upsert_etf_feature(self, *, market: str = "CNStock", etf_code: str, etf_name: str, linked_sector: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_etf_features_daily (
                    market, etf_code, etf_name, linked_sector, as_of_date,
                    close_price, return_1d, return_3d, return_5d, return_10d, return_20d,
                    turnover_amount, etf_avg_amount_5d, etf_avg_amount_20d, etf_liquidity_score,
                    amount_ratio_5d, amount_ratio_20d,
                    drawdown_from_20d_high, volatility_5d,
                    news_count_7d, policy_count_7d, theme_heat_score,
                    metadata
                ) VALUES (
                    %s, %s, %s, %s, %s::date,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb
                )
                ON CONFLICT (market, etf_code, as_of_date) DO UPDATE SET
                    etf_name = EXCLUDED.etf_name,
                    linked_sector = EXCLUDED.linked_sector,
                    close_price = EXCLUDED.close_price,
                    return_1d = EXCLUDED.return_1d,
                    return_3d = EXCLUDED.return_3d,
                    return_5d = EXCLUDED.return_5d,
                    return_10d = EXCLUDED.return_10d,
                    return_20d = EXCLUDED.return_20d,
                    turnover_amount = EXCLUDED.turnover_amount,
                    etf_avg_amount_5d = EXCLUDED.etf_avg_amount_5d,
                    etf_avg_amount_20d = EXCLUDED.etf_avg_amount_20d,
                    etf_liquidity_score = EXCLUDED.etf_liquidity_score,
                    amount_ratio_5d = EXCLUDED.amount_ratio_5d,
                    amount_ratio_20d = EXCLUDED.amount_ratio_20d,
                    drawdown_from_20d_high = EXCLUDED.drawdown_from_20d_high,
                    volatility_5d = EXCLUDED.volatility_5d,
                    news_count_7d = EXCLUDED.news_count_7d,
                    policy_count_7d = EXCLUDED.policy_count_7d,
                    theme_heat_score = EXCLUDED.theme_heat_score,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    market,
                    etf_code,
                    etf_name,
                    linked_sector,
                    as_of_date,
                    float(payload.get("close_price") or 0),
                    float(payload.get("return_1d") or 0),
                    float(payload.get("return_3d") or 0),
                    float(payload.get("return_5d") or 0),
                    float(payload.get("return_10d") or 0),
                    float(payload.get("return_20d") or 0),
                    float(payload.get("turnover_amount") or 0),
                    float(payload.get("etf_avg_amount_5d") or 0),
                    float(payload.get("etf_avg_amount_20d") or 0),
                    float(payload.get("etf_liquidity_score") or 0),
                    float(payload.get("amount_ratio_5d") or 0),
                    float(payload.get("amount_ratio_20d") or 0),
                    float(payload.get("drawdown_from_20d_high") or 0),
                    float(payload.get("volatility_5d") or 0),
                    int(payload.get("news_count_7d") or 0),
                    int(payload.get("policy_count_7d") or 0),
                    float(payload.get("theme_heat_score") or 0),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def list_sector_features(self, *, as_of_date: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, market, sector_name, as_of_date, return_1d, return_3d, return_5d, return_10d, return_20d, "
            "turnover_amount, amount_ratio_5d, amount_ratio_20d, drawdown_from_20d_high, volatility_5d, "
            "news_count_7d, policy_count_7d, theme_heat_score, metadata "
            "FROM qd_sector_features_daily WHERE 1=1"
        )
        params: List[Any] = []
        if as_of_date:
            sql += " AND as_of_date = %s::date"
            params.append(as_of_date)
        sql += " ORDER BY as_of_date DESC, theme_heat_score DESC LIMIT %s"
        params.append(max(1, min(int(limit or 200), 5000)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            out.append(item)
        return out

    def list_etf_features(self, *, as_of_date: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, market, etf_code, etf_name, linked_sector, as_of_date, close_price, return_1d, return_3d, return_5d, return_10d, return_20d, "
            "turnover_amount, etf_avg_amount_5d, etf_avg_amount_20d, etf_liquidity_score, amount_ratio_5d, amount_ratio_20d, drawdown_from_20d_high, volatility_5d, "
            "news_count_7d, policy_count_7d, theme_heat_score, metadata "
            "FROM qd_etf_features_daily WHERE 1=1"
        )
        params: List[Any] = []
        if as_of_date:
            sql += " AND as_of_date = %s::date"
            params.append(as_of_date)
        sql += " ORDER BY as_of_date DESC, theme_heat_score DESC LIMIT %s"
        params.append(max(1, min(int(limit or 200), 5000)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            out.append(item)
        return out

    def upsert_etf_market_bar(self, *, market: str = "CNStock", etf_code: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_etf_market_bars_daily (
                    market, etf_code, as_of_date, open_price, high_price, low_price,
                    close_price, volume, turnover_amount, metadata
                ) VALUES (
                    %s, %s, %s::date, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (market, etf_code, as_of_date) DO UPDATE SET
                    open_price = EXCLUDED.open_price,
                    high_price = EXCLUDED.high_price,
                    low_price = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price,
                    volume = EXCLUDED.volume,
                    turnover_amount = EXCLUDED.turnover_amount,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    market,
                    etf_code,
                    as_of_date,
                    float(payload.get("open_price") or 0),
                    float(payload.get("high_price") or 0),
                    float(payload.get("low_price") or 0),
                    float(payload.get("close_price") or 0),
                    float(payload.get("volume") or 0),
                    float(payload.get("turnover_amount") or 0),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def list_etf_market_bars(self, *, etf_code: str, limit: int = 60) -> List[Dict[str, Any]]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT etf_code, as_of_date, open_price, high_price, low_price, close_price, volume, turnover_amount, metadata "
                "FROM qd_etf_market_bars_daily WHERE etf_code = %s ORDER BY as_of_date DESC LIMIT %s",
                (etf_code, max(1, min(int(limit), 5000))),
            )
            rows = cur.fetchall() or []
            cur.close()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            out.append(item)
        return out


    def upsert_etf_flow(
        self, *, market: str = "CNStock", etf_code: str, etf_name: str,
        as_of_date: str, payload: Dict[str, Any],
    ) -> int:
        """Store daily ETF fund flow snapshot (net inflow by order size)."""
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS qd_etf_fund_flow_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(32) NOT NULL DEFAULT 'CNStock',
                    etf_code VARCHAR(16) NOT NULL,
                    etf_name VARCHAR(128),
                    as_of_date DATE NOT NULL,
                    net_inflow_main DOUBLE PRECISION,
                    net_inflow_super_large DOUBLE PRECISION,
                    net_inflow_large DOUBLE PRECISION,
                    net_inflow_medium DOUBLE PRECISION,
                    net_inflow_small DOUBLE PRECISION,
                    net_inflow_ratio DOUBLE PRECISION,
                    turnover DOUBLE PRECISION,
                    change_pct DOUBLE PRECISION,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE (market, etf_code, as_of_date)
                )
            """)
            db.commit()

            cur.execute("""
                INSERT INTO qd_etf_fund_flow_daily (
                    market, etf_code, etf_name, as_of_date,
                    net_inflow_main, net_inflow_super_large, net_inflow_large,
                    net_inflow_medium, net_inflow_small, net_inflow_ratio,
                    turnover, change_pct, metadata
                ) VALUES (
                    %s, %s, %s, %s::date,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (market, etf_code, as_of_date) DO UPDATE SET
                    etf_name = EXCLUDED.etf_name,
                    net_inflow_main = EXCLUDED.net_inflow_main,
                    net_inflow_super_large = EXCLUDED.net_inflow_super_large,
                    net_inflow_large = EXCLUDED.net_inflow_large,
                    net_inflow_medium = EXCLUDED.net_inflow_medium,
                    net_inflow_small = EXCLUDED.net_inflow_small,
                    net_inflow_ratio = EXCLUDED.net_inflow_ratio,
                    turnover = EXCLUDED.turnover,
                    change_pct = EXCLUDED.change_pct,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """, (
                market, etf_code, etf_name, as_of_date,
                payload.get("net_inflow_main"), payload.get("net_inflow_super_large"),
                payload.get("net_inflow_large"), payload.get("net_inflow_medium"),
                payload.get("net_inflow_small"), payload.get("net_inflow_ratio"),
                payload.get("turnover"), payload.get("change_pct"),
                json.dumps(payload.get("metadata", {}), ensure_ascii=False),
            ))
            db.commit()
            return cur.rowcount


    def list_etf_features(self, etf_code: str, limit: int = 1) -> List[Dict[str, Any]]:
        """List recent ETF feature rows for a given code."""
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("""
                SELECT * FROM qd_etf_features_daily
                WHERE etf_code = %s
                ORDER BY as_of_date DESC
                LIMIT %s
            """, (etf_code, limit))
            return [dict(r) for r in cur.fetchall()]

    def get_latest_etf_flow(self, etf_code: str, limit: int = 1) -> List[Dict[str, Any]]:
        """Get latest fund flow records for an ETF."""
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("""
                SELECT etf_code, etf_name, as_of_date,
                       net_inflow_main, net_inflow_super_large, net_inflow_large,
                       net_inflow_medium, net_inflow_small, net_inflow_ratio,
                       turnover, change_pct
                FROM qd_etf_fund_flow_daily
                WHERE etf_code = %s
                ORDER BY as_of_date DESC
                LIMIT %s
            """, (etf_code, limit))
            rows = cur.fetchall()
            results: List[Dict[str, Any]] = []
            for row in rows:
                results.append({
                    "etf_code": row.get("etf_code", ""),
                    "etf_name": row.get("etf_name", ""),
                    "as_of_date": row.get("as_of_date"),
                    "net_inflow_main": row.get("net_inflow_main"),
                    "net_inflow_super_large": row.get("net_inflow_super_large"),
                    "net_inflow_large": row.get("net_inflow_large"),
                    "net_inflow_medium": row.get("net_inflow_medium"),
                    "net_inflow_small": row.get("net_inflow_small"),
                    "net_inflow_ratio": row.get("net_inflow_ratio"),
                    "turnover": row.get("turnover"),
                    "change_pct": row.get("change_pct"),
                })
            return results


_sector_feature_service: Optional[SectorFeatureService] = None


def get_sector_feature_service() -> SectorFeatureService:
    global _sector_feature_service
    if _sector_feature_service is None:
        _sector_feature_service = SectorFeatureService()
    return _sector_feature_service
