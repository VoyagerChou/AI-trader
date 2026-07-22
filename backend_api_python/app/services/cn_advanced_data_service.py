"""A-share advanced structured data storage.

Phase 1 scope:
- capital flow snapshots
- margin financing / securities lending snapshots

Phase 2 can extend this same service to northbound, leaderboard, valuation,
and other advanced structure data.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection


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


class CNAdvancedDataService:
    """Persistence for advanced A-share structured data."""

    def __init__(self) -> None:
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_sector_capital_flow_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    sector_name VARCHAR(120) NOT NULL,
                    as_of_date DATE NOT NULL,
                    net_inflow_main DECIMAL(24,4) DEFAULT 0,
                    net_inflow_large DECIMAL(24,4) DEFAULT 0,
                    net_inflow_super_large DECIMAL(24,4) DEFAULT 0,
                    net_inflow_ratio DECIMAL(12,6) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_sector_capital_flow_daily UNIQUE (market, sector_name, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_sector_capital_flow_daily_date ON qd_sector_capital_flow_daily(as_of_date DESC)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_etf_capital_flow_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    etf_code VARCHAR(32) NOT NULL,
                    etf_name VARCHAR(255) NOT NULL DEFAULT '',
                    linked_sector VARCHAR(120) NOT NULL DEFAULT '',
                    as_of_date DATE NOT NULL,
                    turnover_amount DECIMAL(24,4) DEFAULT 0,
                    avg_amount_5d DECIMAL(24,4) DEFAULT 0,
                    avg_amount_20d DECIMAL(24,4) DEFAULT 0,
                    amount_ratio_5d DECIMAL(12,6) DEFAULT 0,
                    amount_ratio_20d DECIMAL(12,6) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_etf_capital_flow_daily UNIQUE (market, etf_code, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_etf_capital_flow_daily_date ON qd_etf_capital_flow_daily(as_of_date DESC)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qd_margin_financing_daily (
                    id SERIAL PRIMARY KEY,
                    market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                    symbol VARCHAR(32) NOT NULL,
                    as_of_date DATE NOT NULL,
                    financing_balance DECIMAL(24,4) DEFAULT 0,
                    financing_buy_amount DECIMAL(24,4) DEFAULT 0,
                    securities_lending_balance DECIMAL(24,4) DEFAULT 0,
                    securities_lending_volume DECIMAL(24,4) DEFAULT 0,
                    total_balance DECIMAL(24,4) DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_qd_margin_financing_daily UNIQUE (market, symbol, as_of_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qd_margin_financing_daily_date ON qd_margin_financing_daily(as_of_date DESC)"
            )
            db.commit()
            cur.close()

    def upsert_sector_capital_flow(self, *, sector_name: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_sector_capital_flow_daily (
                    sector_name, as_of_date, net_inflow_main, net_inflow_large,
                    net_inflow_super_large, net_inflow_ratio, metadata
                ) VALUES (
                    %s, %s::date, %s, %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (market, sector_name, as_of_date) DO UPDATE SET
                    net_inflow_main = EXCLUDED.net_inflow_main,
                    net_inflow_large = EXCLUDED.net_inflow_large,
                    net_inflow_super_large = EXCLUDED.net_inflow_super_large,
                    net_inflow_ratio = EXCLUDED.net_inflow_ratio,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    sector_name,
                    as_of_date,
                    None if payload.get("net_inflow_main") is None else float(payload.get("net_inflow_main")),
                    None if payload.get("net_inflow_large") is None else float(payload.get("net_inflow_large")),
                    None if payload.get("net_inflow_super_large") is None else float(payload.get("net_inflow_super_large")),
                    None if payload.get("net_inflow_ratio") is None else float(payload.get("net_inflow_ratio")),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def upsert_etf_capital_flow(self, *, etf_code: str, etf_name: str, linked_sector: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_etf_capital_flow_daily (
                    etf_code, etf_name, linked_sector, as_of_date,
                    turnover_amount, avg_amount_5d, avg_amount_20d,
                    amount_ratio_5d, amount_ratio_20d, metadata
                ) VALUES (
                    %s, %s, %s, %s::date,
                    %s, %s, %s,
                    %s, %s, %s::jsonb
                )
                ON CONFLICT (market, etf_code, as_of_date) DO UPDATE SET
                    etf_name = EXCLUDED.etf_name,
                    linked_sector = EXCLUDED.linked_sector,
                    turnover_amount = EXCLUDED.turnover_amount,
                    avg_amount_5d = EXCLUDED.avg_amount_5d,
                    avg_amount_20d = EXCLUDED.avg_amount_20d,
                    amount_ratio_5d = EXCLUDED.amount_ratio_5d,
                    amount_ratio_20d = EXCLUDED.amount_ratio_20d,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    etf_code,
                    etf_name,
                    linked_sector,
                    as_of_date,
                    float(payload.get("turnover_amount") or 0),
                    float(payload.get("avg_amount_5d") or 0),
                    float(payload.get("avg_amount_20d") or 0),
                    float(payload.get("amount_ratio_5d") or 0),
                    float(payload.get("amount_ratio_20d") or 0),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def upsert_margin_financing(self, *, symbol: str, as_of_date: str, payload: Dict[str, Any]) -> int:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_margin_financing_daily (
                    symbol, as_of_date, financing_balance, financing_buy_amount,
                    securities_lending_balance, securities_lending_volume, total_balance, metadata
                ) VALUES (
                    %s, %s::date, %s, %s, %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (market, symbol, as_of_date) DO UPDATE SET
                    financing_balance = EXCLUDED.financing_balance,
                    financing_buy_amount = EXCLUDED.financing_buy_amount,
                    securities_lending_balance = EXCLUDED.securities_lending_balance,
                    securities_lending_volume = EXCLUDED.securities_lending_volume,
                    total_balance = EXCLUDED.total_balance,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    symbol,
                    as_of_date,
                    float(payload.get("financing_balance") or 0),
                    float(payload.get("financing_buy_amount") or 0),
                    float(payload.get("securities_lending_balance") or 0),
                    float(payload.get("securities_lending_volume") or 0),
                    float(payload.get("total_balance") or 0),
                    _json_dump(payload.get("metadata") or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])


    def list_margin_financing_latest(self, *, limit: int = 5) -> List[Dict[str, Any]]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT symbol, as_of_date, financing_balance, financing_buy_amount, "
                "securities_lending_balance, securities_lending_volume, total_balance, metadata "
                "FROM qd_margin_financing_daily ORDER BY as_of_date DESC LIMIT %s",
                (max(1, min(int(limit), 20)),),
            )
            rows = cur.fetchall() or []
            cur.close()
        return [dict(r) for r in rows]

    def get_latest_etf_flows(self, *, linked_sector: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        sql = (
            "SELECT etf_code, etf_name, linked_sector, as_of_date, turnover_amount, "
            "avg_amount_5d, avg_amount_20d, amount_ratio_5d, amount_ratio_20d, metadata "
            "FROM qd_etf_capital_flow_daily WHERE 1=1"
        )
        params: List[Any] = []
        if linked_sector:
            sql += " AND linked_sector = %s"
            params.append(linked_sector)
        sql += " ORDER BY as_of_date DESC LIMIT %s"
        params.append(max(1, min(int(limit), 5000)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()
        return [dict(r) for r in rows]


_cn_advanced_data_service: Optional[CNAdvancedDataService] = None


def get_cn_advanced_data_service() -> CNAdvancedDataService:
    global _cn_advanced_data_service
    if _cn_advanced_data_service is None:
        _cn_advanced_data_service = CNAdvancedDataService()
    return _cn_advanced_data_service
