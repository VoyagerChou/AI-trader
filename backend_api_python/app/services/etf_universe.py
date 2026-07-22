"""ETF universe service — weekly dynamic ETF list based on turnover threshold.

Fetches all A-share ETFs with daily turnover >= 1亿 from Eastmoney via AkShare,
caches the list locally and to DB for the weekly pipeline.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default turnover threshold (1亿 = 100,000,000)
DEFAULT_TURNOVER_THRESHOLD = 100_000_000

# Cache file path relative to backend
_CACHE_DIR = Path(__file__).resolve().parents[2] / "cache"
_CACHE_FILE = _CACHE_DIR / "etf_universe.json"


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


class ETFUniverseService:
    """Dynamic ETF list manager. Refreshes weekly from live market data."""

    def __init__(self, turnover_threshold: int = DEFAULT_TURNOVER_THRESHOLD) -> None:
        self.turnover_threshold = turnover_threshold
        self._etfs: List[Dict[str, Any]] = []
        self._last_refresh: Optional[str] = None

    # ── public API ──────────────────────────────────────────────

    def refresh(self, force: bool = False) -> List[Dict[str, Any]]:
        """Fetch the latest ETF list from AkShare, filtering by turnover.

        Returns the list cached to disk.  Use ``force=True`` to skip
        the disk-cache check; otherwise a cache < 24 h old is reused.
        """
        _ensure_cache_dir()

        if not force and _CACHE_FILE.exists():
            try:
                cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                age_h = (time.time() - cached.get("fetched_at", 0)) / 3600
                if age_h < 24:
                    self._etfs = cached.get("etfs", [])
                    self._last_refresh = cached.get("fetched_at_iso", "")
                    logger.info(
                        "ETF universe loaded from cache (%.1f h old, %d ETFs)",
                        age_h, len(self._etfs),
                    )
                    return self._etfs
            except Exception:
                pass

        try:
            import akshare as ak

            logger.info("Fetching ETF universe from AkShare fund_etf_spot_em ...")
            df = ak.fund_etf_spot_em()
            raw_count = len(df)

            etfs: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                turnover = float(row.get("成交额", 0) or 0)
                if turnover < self.turnover_threshold:
                    continue
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code:
                    continue
                etfs.append({
                    "code": code,
                    "name": name,
                    "turnover": turnover,
                    "latest_price": float(row.get("最新价", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                })

            # Sort by turnover descending
            etfs.sort(key=lambda x: -x["turnover"])

            now_ts = time.time()
            now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
            self._etfs = etfs
            self._last_refresh = now_iso

            cache_payload = {
                "fetched_at": now_ts,
                "fetched_at_iso": now_iso,
                "threshold": self.turnover_threshold,
                "total_raw": raw_count,
                "total_filtered": len(etfs),
                "etfs": etfs,
            }
            _CACHE_FILE.write_text(
                json.dumps(cache_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            logger.info(
                "ETF universe refreshed: %d/%d ETFs with turnover >= %.0f亿",
                len(etfs), raw_count, self.turnover_threshold / 1e8,
            )
            return etfs

        except Exception as exc:
            logger.error("ETF universe refresh failed: %s", exc, exc_info=True)
            # Fall back to cached list if available
            if _CACHE_FILE.exists():
                try:
                    cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                    self._etfs = cached.get("etfs", [])
                    self._last_refresh = cached.get("fetched_at_iso", "")
                    logger.warning("Falling back to cached ETF list (%d ETFs)", len(self._etfs))
                    return self._etfs
                except Exception:
                    pass
            return []

    def get_etf_list(self) -> List[Dict[str, Any]]:
        """Return current cached ETF list (does NOT trigger refresh)."""
        if not self._etfs and _CACHE_FILE.exists():
            try:
                cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self._etfs = cached.get("etfs", [])
                self._last_refresh = cached.get("fetched_at_iso", "")
            except Exception:
                pass
        return self._etfs

    def get_etf_codes(self) -> List[str]:
        """Return list of ETF codes only."""
        return [e["code"] for e in self.get_etf_list()]

    @property
    def count(self) -> int:
        return len(self.get_etf_list())

    @property
    def last_refresh(self) -> Optional[str]:
        return self._last_refresh

    def get_summary(self) -> Dict[str, Any]:
        """Diagnostic summary for agent context."""
        etfs = self.get_etf_list()
        return {
            "total_etfs": len(etfs),
            "turnover_threshold": self.turnover_threshold,
            "last_refresh": self._last_refresh,
            "top5": [
                {"code": e["code"], "name": e["name"], "turnover": e["turnover"]}
                for e in etfs[:5]
            ] if etfs else [],
        }

    def capture_flow_snapshot(self) -> Dict[str, Any]:
        """Fetch today's ETF fund flow data from Eastmoney and store to DB.

        Returns a summary dict with count of ETFs stored.
        Must be called AFTER ``refresh()`` so the ETF list is populated.
        """
        result = {"success": False, "etf_count": 0, "stored": 0, "error": None}
        etfs = self.get_etf_list()
        if not etfs:
            result["error"] = "ETF list empty, run refresh() first"
            return result

        try:
            import akshare as ak

            logger.info("Fetching ETF fund flow snapshot from AkShare ...")
            df = ak.fund_etf_spot_em()

            # Build a lookup: code → flow data
            flow_map: Dict[str, Dict[str, Any]] = {}
            flow_cols = {
                "主力净流入-净额": "net_inflow_main",
                "超大单净流入-净额": "net_inflow_super_large",
                "大单净流入-净额": "net_inflow_large",
                "中单净流入-净额": "net_inflow_medium",
                "小单净流入-净额": "net_inflow_small",
                "主力净流入-净占比": "net_inflow_ratio",
                "成交额": "turnover",
                "涨跌幅": "change_pct",
            }
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                if not code:
                    continue
                payload = {}
                for src_col, dst_col in flow_cols.items():
                    if src_col in df.columns:
                        payload[dst_col] = float(row.get(src_col, 0) or 0)
                flow_map[code] = payload

            return self._store_flow_data(etfs, flow_map, result)

        except Exception as exc:
            result["error"] = str(exc)
            logger.error("ETF flow snapshot failed: %s", exc)
            return result

    def capture_flow_for_codes(self, etf_codes: List[str], etf_names: Dict[str, str] = None) -> Dict[str, Any]:
        """Capture fund flow for a specific set of ETF codes (e.g. industry ETFs).

        Unlike ``capture_flow_snapshot`` which only processes universe ETFs,
        this fetches and stores flow data for any given codes, regardless of
        turnover threshold.
        """
        result = {"success": False, "stored": 0, "error": None}
        if not etf_codes:
            return result

        try:
            import akshare as ak
            df = ak.fund_etf_spot_em()

            flow_map: Dict[str, Dict[str, Any]] = {}
            flow_cols = {
                "主力净流入-净额": "net_inflow_main",
                "超大单净流入-净额": "net_inflow_super_large",
                "大单净流入-净额": "net_inflow_large",
                "中单净流入-净额": "net_inflow_medium",
                "小单净流入-净额": "net_inflow_small",
                "主力净流入-净占比": "net_inflow_ratio",
                "成交额": "turnover",
                "涨跌幅": "change_pct",
            }
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                if code not in etf_codes:
                    continue
                payload = {}
                for sc, dc in flow_cols.items():
                    if sc in df.columns:
                        payload[dc] = float(row.get(sc, 0) or 0)
                flow_map[code] = payload

            # Build etf list dict for _store_flow_data
            etf_list = [{"code": c, "name": (etf_names or {}).get(c, "")} for c in etf_codes]
            return self._store_flow_data(etf_list, flow_map, result)

        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Flow capture for codes failed: %s", exc)
            return result

    def capture_flow_history(self, days: int = 30) -> Dict[str, Any]:
        """Backfill recent ETF fund flow using Eastmoney 5d/10d cumulative rankings.

        Since Eastmoney only provides individual-stock daily flow via a
        rate-limited API, we use the aggregate ranking endpoints:
        - 今日 (today): from fund_etf_spot_em
        - 5日/10日 cumulative: from stock_individual_fund_flow_rank

        Args:
            days: Number of days to attempt backfill (5, 10, or 30).

        Returns:
            Summary dict with stored count.
        """
        result = {"success": False, "etf_count": 0, "stored": 0, "rounds": [], "error": None}
        etfs = self.get_etf_list()
        if not etfs:
            result["error"] = "ETF list empty, run refresh() first"
            return result

        etf_code_set = {e["code"] for e in etfs}
        stored_total = 0

        try:
            import akshare as ak

            # Round 1: today's data (most granular)
            logger.info("Flow history round 1: today snapshot")
            df_today = ak.fund_etf_spot_em()
            flow_map_today: Dict[str, Dict[str, Any]] = {}
            flow_cols = {
                "主力净流入-净额": "net_inflow_main",
                "超大单净流入-净额": "net_inflow_super_large",
                "大单净流入-净额": "net_inflow_large",
                "中单净流入-净额": "net_inflow_medium",
                "小单净流入-净额": "net_inflow_small",
                "主力净流入-净占比": "net_inflow_ratio",
                "成交额": "turnover",
                "涨跌幅": "change_pct",
            }
            for _, row in df_today.iterrows():
                code = str(row.get("代码", "")).strip()
                if code not in etf_code_set:
                    continue
                payload = {}
                for sc, dc in flow_cols.items():
                    if sc in df_today.columns:
                        payload[dc] = float(row.get(sc, 0) or 0)
                flow_map_today[code] = payload

            stored = self._store_flow_data(etfs, flow_map_today, {"success": False, "etf_count": 0, "stored": 0, "error": None})
            stored_total += stored.get("stored", 0) if isinstance(stored, dict) else 0
            result["rounds"].append({"label": "today", "stored": stored_total})

            # Round 2: 5-day cumulative rankings
            for label, indicator in [("5d", "5日"), ("10d", "10日")]:
                logger.info("Flow history round: %s cumulative", label)
                df_hist = ak.stock_individual_fund_flow_rank(indicator=indicator)
                flow_map_hist: Dict[str, Dict[str, Any]] = {}
                for _, row in df_hist.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code not in etf_code_set:
                        continue
                    payload = {
                        "net_inflow_main": float(row.get("主力净流入-净额", 0) or 0),
                        "net_inflow_ratio": float(row.get("主力净流入-净占比", 0) or 0),
                    }
                    if "超大单净流入-净额" in df_hist.columns:
                        payload["net_inflow_super_large"] = float(row.get("超大单净流入-净额", 0) or 0)
                    if "大单净流入-净额" in df_hist.columns:
                        payload["net_inflow_large"] = float(row.get("大单净流入-净额", 0) or 0)
                    payload["metadata"] = {"flow_window": label, "cumulative": True}
                    flow_map_hist[code] = payload

                # Store with slightly older date for historical context
                from datetime import datetime, timedelta
                offset_days = 5 if label == "5d" else 10
                hist_date = (datetime.now() - timedelta(days=offset_days)).strftime("%Y-%m-%d")
                
                from app.services.sector_feature_service import get_sector_feature_service
                store = get_sector_feature_service()
                round_stored = 0
                for etf in etfs:
                    flow = flow_map_hist.get(etf["code"])
                    if not flow:
                        continue
                    try:
                        store.upsert_etf_flow(
                            market="CNStock", etf_code=etf["code"],
                            etf_name=etf["name"], as_of_date=hist_date, payload=flow,
                        )
                        round_stored += 1
                    except Exception:
                        pass
                stored_total += round_stored
                result["rounds"].append({"label": label, "stored": round_stored})

            result["success"] = True
            result["etf_count"] = len(etfs)
            result["stored"] = stored_total
            logger.info("ETF flow history: %d total stored across %d rounds", stored_total, len(result["rounds"]))
            return result

        except Exception as exc:
            result["error"] = str(exc)
            logger.error("ETF flow history failed: %s", exc)
            return result

    def _store_flow_data(
        self, etfs: List[Dict[str, Any]],
        flow_map: Dict[str, Dict[str, Any]],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Store flow data for all ETFs to DB. (internal helper)"""
        from app.services.sector_feature_service import get_sector_feature_service
        from datetime import datetime

        store = get_sector_feature_service()
        today = datetime.now().strftime("%Y-%m-%d")
        stored = 0
        for etf in etfs:
            flow = flow_map.get(etf["code"])
            if not flow:
                continue
            try:
                store.upsert_etf_flow(
                    market="CNStock", etf_code=etf["code"],
                    etf_name=etf["name"], as_of_date=today, payload=flow,
                )
                stored += 1
            except Exception:
                pass
        result["success"] = True
        result["etf_count"] = len(etfs)
        result["stored"] = stored
        return result


# ── singleton ──────────────────────────────────────────────────

_etf_universe: Optional[ETFUniverseService] = None


def get_etf_universe_service() -> ETFUniverseService:
    global _etf_universe
    if _etf_universe is None:
        _etf_universe = ETFUniverseService()
    return _etf_universe
