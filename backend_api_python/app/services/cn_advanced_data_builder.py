"""First- and second-stage advanced A-share structure builder.

Phase 1 goal:
- populate ETF activity snapshots from existing K-line data
- populate sector heat / pseudo capital flow from current evidence
- create a stable place for later AkShare native flow data

Phase 2 goal:
- extend with richer AkShare-based data sources (northbound, leaderboard,
  margin financing, sector fund flow, valuation snapshots)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import akshare as ak

from app.services.cn_advanced_data_service import get_cn_advanced_data_service
from app.services.kline import KlineService
from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.sector_feature_builder import INDUSTRY_TO_ETFS
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


class CNAdvancedDataBuilder:
    """Populate advanced A-share structure snapshots."""

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()
        self.kline = KlineService()
        self.store = get_cn_advanced_data_service()

    def _recent_docs(
        self,
        *,
        lookback_days: int = 7,
        limit: int = 400,
        as_of_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        docs = self.repo.list_recent_documents(limit=limit, market="CNStock")
        as_of_dt = datetime.now(timezone.utc)
        if as_of_date:
            as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        cutoff = as_of_dt - timedelta(days=max(1, int(lookback_days or 7)))
        out: List[Dict[str, Any]] = []
        for doc in docs:
            published = doc.get("published_at") or doc.get("created_at")
            if isinstance(published, datetime):
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if cutoff <= published <= as_of_dt:
                    out.append(doc)
                continue
            out.append(doc)
        return out

    def _doc_stats(self, docs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        buckets: Dict[str, Dict[str, Any]] = {}
        for doc in docs:
            sectors = doc.get("industry_tags") or []
            for sector in sectors:
                bucket = buckets.setdefault(
                    sector,
                    {
                        "news_count": 0,
                        "policy_count": 0,
                        "etf_notice_count": 0,
                        "heat": 0.0,
                    },
                )
                doc_type = str(doc.get("doc_type") or "")
                if doc_type == "news":
                    bucket["news_count"] += 1
                    bucket["heat"] += 1.0
                elif doc_type == "policy":
                    bucket["policy_count"] += 1
                    bucket["heat"] += 2.0
                elif doc_type == "etf_notice":
                    bucket["etf_notice_count"] += 1
                    bucket["heat"] += 1.5
        return buckets

    def _fetch_real_sector_fund_flow(self) -> Dict[str, Dict[str, Any]]:
        """通过独立子进程获取东方财富行业资金流，避免 AkShare 全局代理污染。"""
        import json as _json
        import subprocess as _subprocess
        import sys as _sys
        from pathlib import Path as _Path

        script = _Path(__file__).resolve().parents[2] / "scripts" / "fetch_real_sector_fund_flow.py"
        flow_map: Dict[str, Dict[str, Any]] = {}
        try:
            proc = _subprocess.run(
                [_sys.executable, str(script)],
                capture_output=True, text=True, encoding="utf-8", timeout=45,
            )
            rows = _json.loads(proc.stdout or "[]")
            for row in rows:
                name = str(row.get("name", "")).strip()
                if name:
                    flow_map[name] = {
                        "name": name,
                        "net_inflow_main": float(row.get("net_inflow_main") or 0),
                        "net_inflow_super_large": float(row.get("net_inflow_super_large") or 0),
                        "net_inflow_large": float(row.get("net_inflow_large") or 0),
                        "net_inflow_ratio": float(row.get("net_inflow_ratio") or 0),
                        "net_inflow_super_large_ratio": 0.0,
                    }
            if flow_map:
                logger.info("Subprocess fetched %d real sector fund flow rows", len(flow_map))
        except Exception as exc:
            logger.warning("Real sector fund flow subprocess failed: %s", exc)
        return flow_map

    def _etf_activity(self, etf_code: str) -> Dict[str, Any]:
        rows = self.kline.get_kline(market="CNStock", symbol=etf_code, timeframe="1D", limit=25)
        if not rows:
            return {}
        amounts = [_safe_float(row.get("amount") or row.get("volume") or 0) for row in rows]
        current = amounts[-1] if amounts else 0.0
        avg5 = sum(amounts[-5:]) / max(1, len(amounts[-5:]))
        avg20 = sum(amounts[-20:]) / max(1, len(amounts[-20:]))
        return {
            "turnover_amount": current,
            "avg_amount_5d": avg5,
            "avg_amount_20d": avg20,
            "amount_ratio_5d": (current / avg5) if avg5 > 0 else 0.0,
            "amount_ratio_20d": (current / avg20) if avg20 > 0 else 0.0,
        }

    def _fetch_margin_financing_rows(self, *, as_of_date: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        as_of_raw = datetime.strptime(as_of_date, "%Y-%m-%d").strftime("%Y%m%d")
        try:
            df_sh = ak.stock_margin_sse()
            if df_sh is not None and len(df_sh) > 0:
                col_date = df_sh.columns[0]
                df_sh = df_sh[df_sh[col_date].astype(str) <= as_of_raw]
                df_sorted = df_sh.sort_values(by=col_date, ascending=False)
                row = df_sorted.iloc[0]
                rows.append(
                    {
                        "symbol": "SSE_MARGIN_SUMMARY",
                        "financing_balance": _safe_float(row.iloc[1] if len(row) > 1 else 0),
                        "financing_buy_amount": _safe_float(row.iloc[2] if len(row) > 2 else 0),
                        "securities_lending_volume": _safe_float(row.iloc[3] if len(row) > 3 else 0),
                        "securities_lending_balance": _safe_float(row.iloc[4] if len(row) > 4 else 0),
                        "total_balance": _safe_float(row.iloc[6] if len(row) > 6 else _safe_float(row.iloc[-1])),
                        "metadata": {"exchange": "SSE", "raw_columns": list(df_sh.columns)},
                    }
                )
        except Exception:
            pass

        try:
            df_sz = ak.stock_margin_szse(date=as_of_raw)
            if df_sz is not None and len(df_sz) > 0:
                row = df_sz.iloc[0]
                rows.append(
                    {
                        "symbol": "SZSE_MARGIN_SUMMARY",
                        "financing_balance": _safe_float(row.iloc[1] if len(row) > 1 else 0),
                        "financing_buy_amount": _safe_float(row.iloc[0] if len(row) > 0 else 0),
                        "securities_lending_volume": _safe_float(row.iloc[2] if len(row) > 2 else 0),
                        "securities_lending_balance": _safe_float(row.iloc[3] if len(row) > 3 else 0),
                        "total_balance": _safe_float(row.iloc[-1] if len(row) > 0 else 0),
                        "metadata": {"exchange": "SZSE", "raw_columns": list(df_sz.columns) if len(df_sz) > 0 else []},
                    }
                )
        except Exception:
            pass
        return rows

    def build_phase1(self, *, as_of_date: Optional[str] = None, lookback_days: int = 7) -> Dict[str, Any]:
        as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
        from app.utils.trading_calendar import is_trading_day
        if not is_trading_day(as_of_date):
            return {"success": False, "as_of_date": as_of_date, "message": "non-trading day, skipped"}
        docs = self._recent_docs(lookback_days=lookback_days, limit=400, as_of_date=as_of_date)
        stats = self._doc_stats(docs)
        real_flow = self._fetch_real_sector_fund_flow()

        # 东方财富行业名 → 我们行业名的近似映射（扩展到29行业）
        SECTOR_FLOW_MATCH: Dict[str, List[str]] = {
            "半导体": ["半导体", "电子", "光学光电子", "电子元件"],
            "券商": ["证券", "券商", "多元金融"],
            "银行": ["银行"],
            "保险": ["保险"],
            "算力": ["通信", "通信设备", "计算机设备", "互联网服务"],
            "计算机": ["计算机设备", "软件开发", "互联网服务"],
            "通信": ["通信设备", "通信服务"],
            "传媒": ["文化传媒", "游戏"],
            "电力设备": ["电力行业", "电网", "输配电气"],
            "新能源车": ["汽车整车", "汽车零部件"],
            "光伏": ["光伏设备"],
            "汽车": ["汽车整车", "汽车零部件"],
            "医药": ["医药", "医疗器械", "化学制药"],
            "消费电子": ["消费电子", "电子"],
            "食品饮料": ["食品饮料", "酿酒行业"],
            "农业": ["农牧饲渔"],
            "家电": ["家电行业"],
            "旅游": ["旅游酒店", "航空机场"],
            "黄金有色": ["有色金属", "贵金属", "黄金"],
            "钢铁": ["钢铁行业"],
            "煤炭": ["煤炭行业"],
            "石油": ["石油行业"],
            "化工": ["化学制品", "化纤行业", "塑料制品"],
            "房地产": ["房地产开发", "房地产服务"],
            "军工": ["航天航空", "船舶制造"],
            "机械": ["专用设备", "通用设备", "工程机械"],
            "基建": ["工程建设", "水泥建材"],
            "环保": ["环保行业"],
            "建材": ["水泥建材", "装修建材"],
        }

        sector_rows = 0
        etf_rows = 0
        margin_rows = 0

        for sector, sector_etfs in INDUSTRY_TO_ETFS.items():
            stat = stats.get(sector, {"news_count": 0, "policy_count": 0, "etf_notice_count": 0, "heat": 0.0})

            # 优先找真实资金流
            flow = None
            match_names = SECTOR_FLOW_MATCH.get(sector, [])
            for match_name in match_names:
                flow = real_flow.get(match_name)
                if flow:
                    break
            # 如果名称为空或有部分匹配，再做模糊搜索
            if not flow and match_names:
                flow = real_flow.get(sector)

            if flow:
                flow_payload = {
                    "net_inflow_main": flow["net_inflow_main"],
                    "net_inflow_large": flow["net_inflow_large"],
                    "net_inflow_super_large": flow["net_inflow_super_large"],
                    "net_inflow_ratio": flow["net_inflow_ratio"],
                    "metadata": {
                        "pseudo": False,
                        "source": "eastmoney_push2",
                        "matched_sector": flow["name"],
                        "news_count": stat["news_count"],
                        "policy_count": stat["policy_count"],
                    },
                }
            else:
                flow_payload = {
                    "net_inflow_main": None,
                    "net_inflow_large": None,
                    "net_inflow_super_large": None,
                    "net_inflow_ratio": None,
                    "metadata": {
                        "pseudo": False,
                        "missing_real_flow": True,
                        "news_count": stat["news_count"],
                        "policy_count": stat["policy_count"],
                    },
                }

            self.store.upsert_sector_capital_flow(
                sector_name=sector,
                as_of_date=as_of_date,
                payload=flow_payload,
            )
            sector_rows += 1

            for etf in sector_etfs:
                activity = self._etf_activity(etf["code"])
                self.store.upsert_etf_capital_flow(
                    etf_code=etf["code"],
                    etf_name=etf["name"],
                    linked_sector=sector,
                    as_of_date=as_of_date,
                    payload={
                        **activity,
                        "metadata": {
                            "pseudo": False,
                            "sector_heat": stat["heat"],
                        },
                    },
                )
                etf_rows += 1

        for row in self._fetch_margin_financing_rows(as_of_date=as_of_date):
            self.store.upsert_margin_financing(
                symbol=row["symbol"],
                as_of_date=as_of_date,
                payload=row,
            )
            margin_rows += 1

        return {
            "success": True,
            "as_of_date": as_of_date,
            "sector_rows": sector_rows,
            "etf_rows": etf_rows,
            "margin_rows": margin_rows,
        }

    def build_phase2(self, *, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        """Second-stage richer AkShare-native structure hooks.

        Current implementation includes real margin financing summary rows.
        Sector/main fund flow endpoints are still reserved because public access
        proved flaky during probing and need dedicated retry / anti-blocking work.
        """
        as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
        from app.utils.trading_calendar import is_trading_day
        if not is_trading_day(as_of_date):
            return {"success": False, "as_of_date": as_of_date, "message": "non-trading day, skipped"}
        margin_rows = 0
        for row in self._fetch_margin_financing_rows(as_of_date=as_of_date):
            self.store.upsert_margin_financing(
                symbol=row["symbol"],
                as_of_date=as_of_date,
                payload=row,
            )
            margin_rows += 1
        return {
            "success": True,
            "as_of_date": as_of_date,
            "margin_rows": margin_rows,
            "message": "Phase 2 margin financing wired; fund-flow endpoints still pending dedicated hardening.",
        }


_cn_advanced_data_builder: Optional[CNAdvancedDataBuilder] = None


def get_cn_advanced_data_builder() -> CNAdvancedDataBuilder:
    global _cn_advanced_data_builder
    if _cn_advanced_data_builder is None:
        _cn_advanced_data_builder = CNAdvancedDataBuilder()
    return _cn_advanced_data_builder
