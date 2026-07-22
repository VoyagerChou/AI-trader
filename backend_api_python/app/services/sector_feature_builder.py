"""First-stage structured feature builder for A-share sectors / ETFs.

This builder intentionally starts lightweight. It uses currently available
signals:
- recent tagged documents from the knowledge base
- ETF price / K-line data available from existing KlineService

Goal: give the weekly pipeline a first version of "market position" instead of
purely text-driven evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.kline import KlineService
from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.sector_feature_service import get_sector_feature_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


INDUSTRY_TO_ETFS: Dict[str, List[Dict[str, str]]] = {
    # 科技
    "半导体": [{"code": "512480", "name": "半导体ETF"}, {"code": "159995", "name": "芯片ETF"}],
    "消费电子": [{"code": "159997", "name": "电子ETF"}, {"code": "159732", "name": "消费电子ETF"}],
    "算力": [{"code": "515000", "name": "科技ETF"}],
    "计算机": [{"code": "512720", "name": "计算机ETF"}],
    "通信": [{"code": "515050", "name": "5GETF"}],
    "传媒": [{"code": "512980", "name": "传媒ETF"}],
    # 金融
    "券商": [{"code": "512000", "name": "券商ETF"}, {"code": "512880", "name": "证券ETF"}],
    "银行": [{"code": "512800", "name": "银行ETF"}],
    "保险": [{"code": "512070", "name": "证券保险ETF"}],
    "房地产": [{"code": "512200", "name": "房地产ETF"}],
    # 周期
    "石油": [{"code": "159697", "name": "石油ETF"}],
    "化工": [{"code": "159870", "name": "化工ETF"}, {"code": "516020", "name": "化工ETF"}],
    "黄金有色": [{"code": "518880", "name": "黄金ETF"}, {"code": "512400", "name": "有色金属ETF"}],
    "钢铁": [{"code": "515210", "name": "钢铁ETF"}],
    "煤炭": [{"code": "515220", "name": "煤炭ETF"}],
    # 制造
    "电力设备": [{"code": "516160", "name": "新能源ETF"}, {"code": "159611", "name": "电力ETF"}],
    "新能源车": [{"code": "515230", "name": "新能源车ETF"}, {"code": "515030", "name": "新能源车ETF"}],
    "光伏": [{"code": "159857", "name": "光伏ETF"}],
    "汽车": [{"code": "516110", "name": "汽车ETF"}],
    "军工": [{"code": "512660", "name": "军工ETF"}, {"code": "512670", "name": "国防ETF"}],
    "机械": [{"code": "159886", "name": "机械ETF"}],
    # 消费
    "医药": [{"code": "512010", "name": "医药ETF"}, {"code": "512170", "name": "医疗ETF"}],
    "食品饮料": [{"code": "512690", "name": "酒ETF"}],
    "农业": [{"code": "159825", "name": "农业ETF"}],
    "家电": [{"code": "159996", "name": "家电ETF"}],
    "旅游": [{"code": "159766", "name": "旅游ETF"}],
    # 基建
    "基建": [{"code": "516950", "name": "基建ETF"}],
    "环保": [{"code": "512580", "name": "环保ETF"}],
    "建材": [{"code": "516750", "name": "建材ETF"}],
}

# 综合评分公式说明（与代码逻辑一致）
# score = 知识库热度分 + max(0, 5日收益率) * 0.2 + max(0, 5日成交额比) * 0.5 + ETF5日成交额比 * 0.3


THEME_TO_ETFS: Dict[str, List[Dict[str, str]]] = {
    "高股息红利": [{"code": "510880", "name": "红利ETF"}],
    "人工智能应用": [{"code": "515000", "name": "科技ETF"}, {"code": "159915", "name": "创业板ETF"}],
    "机器人": [{"code": "159915", "name": "创业板ETF"}],
    "低空经济": [{"code": "159915", "name": "创业板ETF"}],
    "数据要素": [{"code": "159915", "name": "创业板ETF"}],
}


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


class SectorFeatureBuilder:
    """Compute daily sector / ETF feature snapshots."""

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()
        self.kline = KlineService()
        self.store = get_sector_feature_service()

    def _recent_docs(
        self,
        *,
        lookback_days: int = 7,
        limit: int = 200,
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

    def _sector_doc_features(self, docs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        buckets: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "news_count_7d": 0,
                "policy_count_7d": 0,
                "theme_heat_score": 0.0,
            }
        )
        for doc in docs:
            sectors = doc.get("industry_tags") or []
            if not sectors:
                continue
            doc_type = str(doc.get("doc_type") or "")
            for sector in sectors:
                buckets[sector]["theme_heat_score"] += 1.0
                if doc_type == "policy":
                    buckets[sector]["policy_count_7d"] += 1
                    buckets[sector]["theme_heat_score"] += 2.0
                elif doc_type == "news":
                    buckets[sector]["news_count_7d"] += 1
                elif doc_type == "etf_notice":
                    buckets[sector]["theme_heat_score"] += 1.5
        return buckets

    def _etf_price_features(self, etf_code: str, *, as_of_date: str) -> Dict[str, Any]:
        before_time = int((datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)).timestamp())
        rows = self.kline.get_kline(market="CNStock", symbol=etf_code, timeframe="1D", limit=60, before_time=before_time)
        if not rows or len(rows) < 2:
            return {}

        normalized_rows: List[Dict[str, Any]] = []
        for row in rows:
            close_v = _safe_float(row.get("close"))
            if close_v <= 0:
                continue
            time_v = int(row.get("time") or 0)
            bar_date = datetime.fromtimestamp(time_v).strftime("%Y-%m-%d") if time_v else as_of_date
            amount_v = _safe_float(row.get("amount") or row.get("volume") or 0)
            bar = {
                "as_of_date": bar_date,
                "open_price": _safe_float(row.get("open")),
                "high_price": _safe_float(row.get("high")),
                "low_price": _safe_float(row.get("low")),
                "close_price": close_v,
                "volume": _safe_float(row.get("volume")),
                "turnover_amount": amount_v,
            }
            normalized_rows.append(bar)
            self.store.upsert_etf_market_bar(
                market="CNStock",
                etf_code=etf_code,
                as_of_date=bar_date,
                payload=bar,
            )

        if len(normalized_rows) < 2:
            return {}

        closes = [bar["close_price"] for bar in normalized_rows]
        amounts = [bar["turnover_amount"] for bar in normalized_rows]
        
        # Detect ETF adjustment events: single-day price jump > 20%
        # When found, only use post-jump bars for return calculations
        adj_index = 0
        for i in range(1, len(closes)):
            pct = _pct_change(closes[i], closes[i - 1])
            if abs(pct) > 20:
                adj_index = i
                break
        
        effective_closes = closes[adj_index:] if adj_index > 0 else closes
        effective_amounts = amounts[adj_index:] if adj_index > 0 else amounts
        current = effective_closes[-1]
        
        feature: Dict[str, Any] = {
            "close_price": current,
            "return_1d": _pct_change(effective_closes[-1], effective_closes[-2]) if len(effective_closes) >= 2 else 0.0,
            "return_3d": _pct_change(effective_closes[-1], effective_closes[-4]) if len(effective_closes) >= 4 else 0.0,
            "return_5d": _pct_change(effective_closes[-1], effective_closes[-6]) if len(effective_closes) >= 6 else 0.0,
            "return_10d": _pct_change(effective_closes[-1], effective_closes[-11]) if len(effective_closes) >= 11 else 0.0,
            "return_20d": _pct_change(effective_closes[-1], effective_closes[-21]) if len(effective_closes) >= 21 else 0.0,
            "turnover_amount": effective_amounts[-1] if effective_amounts else 0.0,
            "etf_avg_amount_5d": sum(effective_amounts[-5:]) / max(1, len(effective_amounts[-5:])),
            "etf_avg_amount_20d": sum(effective_amounts[-20:]) / max(1, len(effective_amounts[-20:])),
            "drawdown_from_20d_high": _pct_change(current, max(effective_closes[-20:])) if len(effective_closes) >= 20 else 0.0,
        }

        if adj_index > 0:
            feature["adj_event_detected"] = True
            feature["adj_event_date"] = normalized_rows[adj_index]["as_of_date"] if adj_index < len(normalized_rows) else "unknown"
            feature["adj_event_pct"] = _pct_change(closes[adj_index], closes[adj_index - 1])
        else:
            feature["adj_event_detected"] = False

        avg5 = feature["etf_avg_amount_5d"]
        avg20 = feature["etf_avg_amount_20d"]
        feature["amount_ratio_5d"] = (feature["turnover_amount"] / avg5) if avg5 > 0 else 0.0
        feature["amount_ratio_20d"] = (feature["turnover_amount"] / avg20) if avg20 > 0 else 0.0
        returns_5 = [_pct_change(closes[i], closes[i - 1]) for i in range(max(1, len(closes) - 5), len(closes))]
        feature["volatility_5d"] = sum(abs(x) for x in returns_5) / max(1, len(returns_5))
        feature["etf_liquidity_score"] = min(100.0, avg5 / 1_000_000.0)
        return feature

    def build_daily_features(self, *, as_of_date: Optional[str] = None, lookback_days: int = 7) -> Dict[str, Any]:
        as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
        from app.utils.trading_calendar import is_trading_day
        if not is_trading_day(as_of_date):
            return {"success": False, "as_of_date": as_of_date, "message": "non-trading day, skipped"}
        docs = self._recent_docs(lookback_days=lookback_days, limit=400, as_of_date=as_of_date)
        sector_doc = self._sector_doc_features(docs)

        sector_rows = 0
        etf_rows = 0
        sector_names = sorted(set(list(sector_doc.keys()) + list(INDUSTRY_TO_ETFS.keys())))

        for sector in sector_names:
            etfs = INDUSTRY_TO_ETFS.get(sector, [])
            etf_features = self._etf_price_features(etfs[0]["code"], as_of_date=as_of_date) if etfs else {}

            sector_payload = {
                "return_1d": etf_features.get("return_1d", 0.0),
                "return_3d": etf_features.get("return_3d", 0.0),
                "return_5d": etf_features.get("return_5d", 0.0),
                "return_10d": etf_features.get("return_10d", 0.0),
                "return_20d": etf_features.get("return_20d", 0.0),
                "turnover_amount": etf_features.get("turnover_amount", 0.0),
                "amount_ratio_5d": etf_features.get("amount_ratio_5d", 0.0),
                "amount_ratio_20d": etf_features.get("amount_ratio_20d", 0.0),
                "drawdown_from_20d_high": etf_features.get("drawdown_from_20d_high", 0.0),
                "volatility_5d": etf_features.get("volatility_5d", 0.0),
                "news_count_7d": sector_doc.get(sector, {}).get("news_count_7d", 0),
                "policy_count_7d": sector_doc.get(sector, {}).get("policy_count_7d", 0),
                "theme_heat_score": sector_doc.get(sector, {}).get("theme_heat_score", 0.0),
                "metadata": {
                    "linked_etfs": [item["code"] for item in etfs],
                    "adj_event_detected": etf_features.get("adj_event_detected", False),
                    "adj_event_date": etf_features.get("adj_event_date"),
                    "adj_event_pct": etf_features.get("adj_event_pct"),
                },
            }
            self.store.upsert_sector_feature(
                market="CNStock",
                sector_name=sector,
                as_of_date=as_of_date,
                payload=sector_payload,
            )
            sector_rows += 1

            for etf in etfs:
                etf_payload = {
                    **etf_features,
                    "news_count_7d": sector_payload["news_count_7d"],
                    "policy_count_7d": sector_payload["policy_count_7d"],
                    "theme_heat_score": sector_payload["theme_heat_score"],
                    "metadata": {"sector_name": sector},
                }
                self.store.upsert_etf_feature(
                    market="CNStock",
                    etf_code=etf["code"],
                    etf_name=etf["name"],
                    linked_sector=sector,
                    as_of_date=as_of_date,
                    payload=etf_payload,
                )
                etf_rows += 1

        return {
            "success": True,
            "as_of_date": as_of_date,
            "sector_rows": sector_rows,
            "etf_rows": etf_rows,
        }


_sector_feature_builder: Optional[SectorFeatureBuilder] = None


def get_sector_feature_builder() -> SectorFeatureBuilder:
    global _sector_feature_builder
    if _sector_feature_builder is None:
        _sector_feature_builder = SectorFeatureBuilder()
    return _sector_feature_builder
