"""Weekly sector research pipeline.

First-stage implementation for A-share weekly sector rotation research.
It retrieves recently ingested documents, aggregates sector evidence, and tries
to produce a structured weekly draft with optional LLM enhancement.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.llm import LLMService
from app.services.cn_advanced_data_service import get_cn_advanced_data_service
from app.services.rag_ingest.embedding_service import get_embedding_service
from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.sector_feature_service import get_sector_feature_service
from app.services.sector_feature_builder import INDUSTRY_TO_ETFS, THEME_TO_ETFS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Legacy tag → modern tag mapping (for documents tagged with old merged sector names)
_LEGACY_SECTOR_MAP: Dict[str, List[str]] = {
    "石油化工": ["石油", "化工"],
    "银行保险": ["银行", "保险"],
}


def _expand_legacy_sector(sector: str) -> List[str]:
    """Expand a sector tag, splitting legacy merged names into individual sectors."""
    return _LEGACY_SECTOR_MAP.get(sector, [sector])


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _safe_json_loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return default


def _fmt_flow(value: float) -> str:
    """Format fund flow amount for display (亿/万)."""
    if abs(value) >= 1e8:
        return f"{value / 1e8:+.2f}亿"
    elif abs(value) >= 1e4:
        return f"{value / 1e4:+.1f}万"
    return f"{value:+.0f}"


class DailyReportPipeline:
    """Build a daily ETF/strategy report from recent RAG documents and market data."""

    TOPIC_QUERIES = ["A股 本周 可能 领涨 板块 政策 新闻 ETF"]
    DEFAULT_DOC_LIMIT = 24
    DEFAULT_RETRIEVAL_PER_QUERY = 3
    DEFAULT_EMBED_WARM_DOCS = 4

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()
        self.llm = LLMService()
        self.embedding_service = get_embedding_service()
        self.feature_store = get_sector_feature_service()
        self.advanced_store = get_cn_advanced_data_service()

    def _fetch_recent_documents(self, lookback_days: int = 7, limit: int = 200) -> List[Dict[str, Any]]:
        docs = self.repo.list_recent_documents(limit=limit, market="CNStock")
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days or 7)))

        out: List[Dict[str, Any]] = []
        for doc in docs:
            published = doc.get("published_at") or doc.get("created_at")
            if isinstance(published, datetime):
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published >= cutoff:
                    out.append(doc)
                continue
            out.append(doc)
        return out

    def _aggregate_sector_evidence(self, docs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        evidence: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "sector": "",
                "doc_count": 0,
                "sources": set(),
                "doc_types": Counter(),
                "titles": [],
                "urls": [],
                "score": 0,
            }
        )

        for doc in docs:
            sector_tags = doc.get("industry_tags") or []
            if not sector_tags:
                continue

            title = str(doc.get("title") or "").strip()
            source = str(doc.get("source") or "").strip()
            url = str(doc.get("url") or "").strip()
            doc_type = str(doc.get("doc_type") or "").strip()

            for sector in sector_tags:
                # Expand legacy merged tags into current individual sector names
                expanded = _expand_legacy_sector(sector)
                for resolved in expanded:
                    bucket = evidence[resolved]
                    bucket["sector"] = resolved
                    bucket["doc_count"] += 1
                    bucket["sources"].add(source)
                    bucket["doc_types"][doc_type] += 1
                    if title and len(bucket["titles"]) < 8:
                        bucket["titles"].append(title)
                    if url and len(bucket["urls"]) < 8:
                        bucket["urls"].append(url)

                    score = 1
                    if doc_type == "policy":
                        score += 3
                    elif doc_type == "etf_notice":
                        score += 2
                    elif doc_type == "news":
                        score += 1
                    elif doc_type == "forum":
                        score -= 1
                    bucket["score"] += score

        normalized: Dict[str, Dict[str, Any]] = {}
        for sector, bucket in evidence.items():
            normalized[sector] = {
                "sector": bucket["sector"],
                "doc_count": bucket["doc_count"],
                "sources": sorted([item for item in bucket["sources"] if item]),
                "doc_types": dict(bucket["doc_types"]),
                "titles": list(bucket["titles"]),
                "urls": list(bucket["urls"]),
                "score": int(bucket["score"]),
            }
        return normalized

    def _aggregate_theme_evidence(self, docs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        evidence: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "theme": "",
                "doc_count": 0,
                "sources": set(),
                "doc_types": Counter(),
                "titles": [],
                "urls": [],
                "score": 0,
            }
        )

        for doc in docs:
            theme_tags = doc.get("theme_tags") or []
            if not theme_tags:
                continue

            title = str(doc.get("title") or "").strip()
            source = str(doc.get("source") or "").strip()
            url = str(doc.get("url") or "").strip()
            doc_type = str(doc.get("doc_type") or "").strip()

            for theme in theme_tags:
                bucket = evidence[theme]
                bucket["theme"] = theme
                bucket["doc_count"] += 1
                bucket["sources"].add(source)
                bucket["doc_types"][doc_type] += 1
                if title and len(bucket["titles"]) < 8:
                    bucket["titles"].append(title)
                if url and len(bucket["urls"]) < 8:
                    bucket["urls"].append(url)

                score = 1
                if doc_type == "policy":
                    score += 3
                elif doc_type == "etf_notice":
                    score += 2
                elif doc_type == "news":
                    score += 1
                elif doc_type == "forum":
                    score += 0
                bucket["score"] += score

        normalized: Dict[str, Dict[str, Any]] = {}
        for theme, bucket in evidence.items():
            normalized[theme] = {
                "theme": bucket["theme"],
                "doc_count": bucket["doc_count"],
                "sources": sorted([item for item in bucket["sources"] if item]),
                "doc_types": dict(bucket["doc_types"]),
                "titles": list(bucket["titles"]),
                "urls": list(bucket["urls"]),
                "score": int(bucket["score"]),
            }
        return normalized

    def _load_etf_rankings(self, etf_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Load features + flow for A-share ETFs only, score each, return sorted."""
        from datetime import datetime

        # Filter: only tradable equity ETFs on SH/SZ exchanges
        # Exclude money-market (货币) and bond (债券) ETFs
        def _is_equity_etf(code: str, name: str = "") -> bool:
            skip_kw = ["货币"]
            if any(kw in name for kw in skip_kw):
                return False
            if code.startswith(("51", "56", "58", "15", "16")): return True
            return False

        equity_etfs = [(e["code"], e.get("name", "")) for e in etf_list if _is_equity_etf(e["code"], e.get("name", ""))]
        etf_data: List[Dict[str, Any]] = []

        for code, name in equity_etfs:
            try:
                # Load features
                features = self.feature_store.list_etf_features(etf_code=code, limit=1)
                flow_rows = self.feature_store.get_latest_etf_flow(etf_code=code, limit=1)
                name_rows = self.feature_store.list_etf_features(etf_code=code, limit=1)

                f = features[0] if features else {}
                fl = flow_rows[0] if flow_rows else {}
                etf_name = f.get("etf_name", "") or fl.get("etf_name", "")

                ret_5d = float(f.get("return_5d") or 0)
                ret_1d = float(f.get("return_1d") or 0)
                vol_5d = float(f.get("amount_ratio_5d") or 0)
                flow_main = float(fl.get("net_inflow_main") or 0)
                flow_ratio = float(fl.get("net_inflow_ratio") or 0)
                super_large = float(fl.get("net_inflow_super_large") or 0)
                flow_bias = (super_large / abs(flow_main)) if abs(flow_main) > 1e4 else 0.0

                meta = f.get("metadata") or {}
                is_adj = bool(meta.get("adj_event_detected")) if isinstance(meta, dict) else False

                score = self._score_etf(ret_5d, ret_1d, vol_5d, flow_ratio, flow_bias, is_adj)

                etf_data.append({
                    "code": code,
                    "name": etf_name,
                    "ret_5d": ret_5d,
                    "ret_1d": ret_1d,
                    "vol_5d": vol_5d,
                    "flow_main": flow_main,
                    "flow_ratio": flow_ratio,
                    "flow_bias": flow_bias,
                    "is_adjusted": is_adj,
                    "score": score,
                })
            except Exception:
                pass

        etf_data.sort(key=lambda x: -x["score"]["total"])
        return etf_data

    def _group_etfs(self, ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group ranked ETFs by cluster (primary) or industry/theme (fallback).

        Same cluster → only top ETF gets a recommendation slot, rest go to related.
        ETFs not in any cluster fall back to INDUSTRY_TO_ETFS / THEME_TO_ETFS matching.
        """
        groups: List[Dict[str, Any]] = []
        used_codes: set = set()

        # Load cluster service
        cluster_svc = None
        try:
            from app.services.etf_cluster import get_etf_cluster_service
            cluster_svc = get_etf_cluster_service()
        except Exception:
            pass

        # Build fallback map: code -> industry/theme names
        code_to_groups: Dict[str, List[str]] = {}
        for sector, etfs in INDUSTRY_TO_ETFS.items():
            for e in etfs:
                code_to_groups.setdefault(e["code"], []).append(sector)
        for theme, etfs in THEME_TO_ETFS.items():
            for e in etfs:
                code_to_groups.setdefault(e["code"], []).append(theme)

        for etf in ranked:
            if etf["code"] in used_codes:
                continue

            related: List[Dict[str, Any]] = []

            # --- Primary: cluster-based grouping ---
            cluster_id = None
            if cluster_svc and cluster_svc.is_loaded:
                cluster_id = cluster_svc.get_cluster(etf["code"])
            if cluster_id is not None:
                peers = cluster_svc.get_peers(etf["code"])
                for other in ranked:
                    if other["code"] in used_codes:
                        continue
                    if other["code"] in peers:
                        related.append(other)
                        used_codes.add(other["code"])
                        if len(related) >= 8:
                            break

            # --- Fallback: industry/theme overlap ---
            if not related:
                group_names = code_to_groups.get(etf["code"], [])
                for other in ranked:
                    if other["code"] == etf["code"]:
                        continue
                    if other["code"] in used_codes:
                        continue
                    other_groups = code_to_groups.get(other["code"], [])
                    if set(group_names) & set(other_groups):
                        related.append(other)
                        used_codes.add(other["code"])
                        if len(related) >= 4:
                            break

            used_codes.add(etf["code"])
            themes = code_to_groups.get(etf["code"], [])
            if cluster_id is not None:
                themes.insert(0, f"cluster_{cluster_id}")

            groups.append({
                "primary": etf,
                "related": related[:8],
                "themes": themes,
                "score": etf["score"]["total"],
                "cluster_id": cluster_id,
            })

        return groups


    def _score_etf(self, ret_5d: float, ret_1d: float, vol_5d: float,
                   flow_ratio: float, flow_bias: float,
                   is_adjusted: bool = False) -> Dict[str, float]:
        """Score an individual ETF using the established formula."""
        ret_mult = 0.3 if is_adjusted else 1.0
        price_score = ret_5d * 3.0 * ret_mult + ret_1d * 2.0
        volume_score = (vol_5d - 0.7) * 10.0
        # Clamp flow_bias to prevent score explosion from tiny main inflows
        flow_bias = max(-2.0, min(2.0, flow_bias))
        flow_bias = 0.0 if abs(flow_bias) > 100 else flow_bias  # NaN guard
        flow_score = (flow_ratio * 0.5) + (flow_bias * 1.5)  # reduced from 3.0
        return {
            "total": round(price_score + volume_score + flow_score, 2),
            "price": round(price_score, 2),
            "volume": round(volume_score, 2),
            "flow": round(flow_score, 2),
        }


    def _build_context(self, sector_rows: List[Dict[str, Any]], docs: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        lines.append("=== 知识库板块证据（按综合评分排序，每个板块列出关联文档标题） ===")
        lines.append("")
        for idx, row in enumerate(sector_rows, 1):
            lines.append(
                f"{idx}. {row['sector']} | 综合评分={row.get('score', 0):.1f} | 文档数={row['doc_count']}"
                f" | 来源={', '.join(row.get('sources', [])[:5])}"
                f" | 文档类型={dict(row.get('doc_types', {}))}"
            )
            titles = row.get("titles", [])
            if titles:
                lines.append(f"   关联文档:")
                for t in titles:
                    lines.append(f"     · {t}")
            lines.append("")
        lines.append(f"样本文档类型分布: {dict(Counter(str(doc.get('doc_type') or 'unknown') for doc in docs))}")
        return "\n".join(lines)

    def _build_theme_context(self, theme_rows: List[Dict[str, Any]]) -> str:
        if not theme_rows:
            return "暂无主题层证据。"
        lines: List[str] = ["以下是最近一周按主题/风格聚合后的证据摘要："]
        for idx, row in enumerate(theme_rows[:8], 1):
            lines.append(
                f"{idx}. 主题={row['theme']} | score={row['score']} | doc_count={row['doc_count']} | sources={', '.join(row['sources'][:4])}"
            )
            for title in row.get("titles", [])[:3]:
                lines.append(f"   - {title}")
        return "\n".join(lines)

    def _load_recent_sector_features(self, *, limit: int = 50) -> Dict[str, Dict[str, Any]]:
        rows = self.feature_store.list_sector_features(limit=limit)
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sector = str(row.get("sector_name") or "").strip()
            if sector and sector not in out:
                out[sector] = row
        return out

    def _load_advanced_features(self) -> Dict[str, Any]:
        margin_rows = self.advanced_store.list_margin_financing_latest(limit=3)
        etf_rows = self.advanced_store.get_latest_etf_flows(limit=100)
        etf_by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in etf_rows:
            sector = str(row.get("linked_sector") or "").strip()
            if sector:
                etf_by_sector[sector].append(row)
        return {"margin": margin_rows, "etf_by_sector": etf_by_sector}

    def _backfill_industry_flows(self, etf_codes: List[str], store: Any) -> None:
        """Fetch historical fund flow for a list of industry ETFs via Eastmoney push2his."""
        import requests
        from datetime import datetime

        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://data.eastmoney.com/",
        })

        for code in etf_codes:
            # Skip if already has recent data
            existing = store.get_latest_etf_flow(etf_code=code, limit=5)
            if existing and len(existing) >= 3:
                continue

            secid = f"1.{code}" if code.startswith(("6", "51", "56", "58")) else f"0.{code}"
            try:
                r = session.get(url, params={
                    "secid": secid, "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56",
                    "lmt": "20", "klt": "101", "fqt": "0",
                }, timeout=8)
                if r.status_code != 200:
                    continue
                klines = (r.json().get("data") or {}).get("klines") or []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) < 6:
                        continue
                    date_str = parts[0]
                    if not date_str or date_str == "-":
                        continue
                    main = float(parts[1] or 0)
                    sm = float(parts[2] or 0)
                    md = float(parts[3] or 0)
                    lg = float(parts[4] or 0)
                    sl = float(parts[5] or 0)
                    total = abs(main) if abs(main) > 0 else 1
                    store.upsert_etf_flow(
                        market="CNStock", etf_code=code, etf_name="",
                        as_of_date=date_str,
                        payload={
                            "net_inflow_main": main,
                            "net_inflow_super_large": sl,
                            "net_inflow_large": lg,
                            "net_inflow_medium": md,
                            "net_inflow_small": sm,
                            "net_inflow_ratio": (main / total) * 100,
                            "metadata": {"flow_bias": sl / total},
                        },
                    )
            except Exception:
                pass

    def _load_fund_flow(self) -> Dict[str, Dict[str, float]]:
        """Load latest ETF fund flow and map to sector-level aggregates."""
        result: Dict[str, Dict[str, float]] = {}
        try:
            from app.services.sector_feature_service import get_sector_feature_service
            from app.services.sector_feature_builder import INDUSTRY_TO_ETFS
            store = get_sector_feature_service()

            # Collect industry ETF codes and names
            industry_codes: List[str] = []
            code_names: Dict[str, str] = {}
            for sector, etf_list in INDUSTRY_TO_ETFS.items():
                if etf_list:
                    code = etf_list[0]["code"]
                    industry_codes.append(code)
                    code_names[code] = etf_list[0].get("name", "")

            # Backfill recent flow for industry ETFs via push2his (best-effort)
            self._backfill_industry_flows(industry_codes, store)

            # Ensure ALL industry ETFs have at least today's flow snapshot
            # (some may be below turnover threshold and skipped by universe capture)
            missing = [c for c in industry_codes if not store.get_latest_etf_flow(etf_code=c)]
            if missing:
                from app.services.etf_universe import get_etf_universe_service
                universe = get_etf_universe_service()
                logger.info("Capturing flow for %d industry ETFs below turnover threshold", len(missing))
                universe.capture_flow_for_codes(missing, code_names)

            # Read from DB
            for sector, etf_list in INDUSTRY_TO_ETFS.items():
                if not etf_list:
                    continue
                code = etf_list[0]["code"]
                rows = store.get_latest_etf_flow(etf_code=code)
                if rows:
                    row = rows[0]
                    main = float(row.get("net_inflow_main") or 0)
                    super_large = float(row.get("net_inflow_super_large") or 0)
                    ratio = float(row.get("net_inflow_ratio") or 0)
                    flow_bias = (super_large / abs(main)) if abs(main) > 0 else 0.0
                    result[sector] = {
                        "net_inflow_main": main,
                        "net_inflow_ratio": ratio,
                        "flow_bias": flow_bias,  # >0.5 means institution-driven
                    }
        except Exception as exc:
            logger.warning("Fund flow loading skipped: %s", exc)
        return result

    def _merge_structured_features(
        self,
        sector_rows: List[Dict[str, Any]],
        sector_features: Dict[str, Dict[str, Any]],
        advanced: Optional[Dict[str, Any]] = None,
        fund_flow: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[Dict[str, Any]]:
        advanced = advanced or {}
        fund_flow = fund_flow or {}
        etf_by_sector = advanced.get("etf_by_sector") or {}
        margin_rows = advanced.get("margin") or []
        margin_note = ""
        if margin_rows:
            m = margin_rows[0]
            margin_note = f"最新融资余额={m.get('total_balance')} | 融资买入额={m.get('financing_buy_amount')}"

        out: List[Dict[str, Any]] = []
        for row in sector_rows:
            merged = dict(row)
            feature = sector_features.get(str(row.get("sector") or ""), {})
            etfs = etf_by_sector.get(str(row.get("sector") or ""), [])
            flow_data = fund_flow.get(str(row.get("sector") or ""), {})
            etf_activity = ""
            if etfs:
                best = etfs[0]
                etf_activity = f"ETF={best.get('etf_code')} | amount_ratio_5d={best.get('amount_ratio_5d')} | amount_ratio_20d={best.get('amount_ratio_20d')}"

            merged["structured"] = feature
            merged["margin_note"] = margin_note
            merged["etf_activity"] = etf_activity
            merged["fund_flow"] = flow_data

            # ── 评分公式 v3: 行情信号 85%，新闻 15% ──
            # 行情分 = 涨跌幅 + 成交量 + 资金流向
            # 新闻分 = 知识库文档得分（仅作辅助参考）
            ret_5d = float(feature.get("return_5d") or 0)
            ret_1d = float(feature.get("return_1d") or 0)
            vol_5d = float(feature.get("amount_ratio_5d") or 0)
            raw_doc_score = float(merged.get("score") or 0)
            heat = float(feature.get("theme_heat_score") or 0)

            # Flow data
            flow_main = float(flow_data.get("net_inflow_main", 0) or 0) if flow_data else 0.0
            flow_ratio = float(flow_data.get("net_inflow_ratio", 0) or 0) if flow_data else 0.0
            flow_bias = float(flow_data.get("flow_bias", 0) or 0) if flow_data else 0.0

            # Adjustment event
            meta = feature.get("metadata") or {}
            is_adjusted = bool(meta.get("adj_event_detected")) if isinstance(meta, dict) else False
            ret_mult = 0.3 if is_adjusted else 1.0

            # 行情分 (85%)
            price_score = ret_5d * 3.0 * ret_mult + ret_1d * 2.0
            volume_score = (vol_5d - 0.7) * 10.0
            flow_score = (flow_ratio * 0.5) + (flow_bias * 3.0)  # 净占比 + 机构主导度
            market_score = price_score + volume_score + flow_score

            # 新闻分 (0%) — 暂时关闭，代码保留以备后用
            news_score = (raw_doc_score + heat) * 0.0

            merged["score"] = round(market_score + news_score, 2)
            merged["market_score"] = round(market_score, 2)
            merged["news_score"] = round(news_score, 2)
            merged["price_score"] = round(price_score, 2)
            merged["volume_score"] = round(volume_score, 2)
            merged["flow_score"] = round(flow_score, 2)
            merged["ret_5d"] = ret_5d
            merged["vol_5d"] = vol_5d
            merged["flow_ratio"] = flow_ratio
            merged["is_adjusted"] = is_adjusted
            out.append(merged)
        out.sort(key=lambda item: (-float(item.get("score") or 0), -int(item.get("doc_count") or 0), str(item.get("sector") or "")))
        return out

    def _build_structured_context(self, sector_rows: List[Dict[str, Any]], *, advanced: Optional[Dict[str, Any]] = None) -> str:
        if not sector_rows:
            return "暂无结构化板块特征。"
        advanced = advanced or {}
        margin_rows = advanced.get("margin") or []
        lines = ["=== 结构化市场数据（必须逐字段引用，禁止推测） ==="]
        if margin_rows:
            m = margin_rows[0]
            lines.append(f"融资融券: 余额={m.get('total_balance')}元 | 融资买入额={m.get('financing_buy_amount')}元 | 融券余额={m.get('securities_lending_balance')}元")
        lines.append("")
        lines.append("以下是各行业板块近5日行情的原始数据（每个板块的涨跌幅来自其第一支关联ETF的K线）：")
        for idx, row in enumerate(sector_rows, 1):
            feature = row.get("structured") or {}
            sector = row.get("sector") or "?"
            
            # Get the actual ETF that generated this sector's return (from metadata)
            meta = feature.get("metadata") or {}
            linked_etfs = meta.get("linked_etfs", []) if isinstance(meta, dict) else []
            primary_etf = linked_etfs[0] if linked_etfs else "?"
            
            ret5 = feature.get("return_5d", 0)
            ret1 = feature.get("return_1d", 0)
            vol5 = feature.get("amount_ratio_5d", 0)
            
            # Extract adj info
            adj_note = ""
            if isinstance(meta, dict) and meta.get("adj_event_detected"):
                adj_note = f" [注意: 该ETF在{meta.get('adj_event_date', '?')}发生除权, 收益率仅统计除权后时段]"
            
            lines.append(
                f"{idx}. {sector}"
                f" | 代表ETF: {primary_etf}"
                f" | 近5日涨跌: {ret5:.2f}%"
                f" | 近1日涨跌: {ret1:.2f}%"
                f" | 5日成交额比: {vol5:.2f}{adj_note}"
            )
            
            # Fund flow data
            flow_data = row.get("fund_flow") or {}
            if flow_data:
                flow_main = float(flow_data.get("net_inflow_main", 0) or 0)
                flow_ratio = float(flow_data.get("net_inflow_ratio", 0) or 0)
                flow_bias = float(flow_data.get("flow_bias", 0) or 0)
                bias_label = "机构主导" if flow_bias > 0.5 else "散户主导"
                lines.append(
                    f"   | 主力资金: {_fmt_flow(flow_main)}"
                    f" | 净占比: {flow_ratio:.1f}%"
                    f" | 方向: {bias_label}"
                )
            
            # Score breakdown  
            lines.append(
                f"   | 行情分={row.get('market_score', 0):.1f} (涨跌={row.get('price_score', 0):.1f} "
                f"量比={row.get('volume_score', 0):.1f} 资金流={row.get('flow_score', 0):.1f})"
                f" | 新闻分={row.get('news_score', 0):.1f} | 综合={row.get('score', 0):.1f}"
            )
            
            # Volume context
            if vol5 > 1.2:
                lines.append(f"   → 成交放量（>1.2），资金关注度上升")
            elif vol5 < 0.7:
                lines.append(f"   → 成交萎缩（<0.7），交投清淡")
            
            # Doc evidence (last, supplementary)
            doc_count = row.get("doc_count", 0)
            if doc_count > 0:
                lines.append(f"   | 辅助参考: {doc_count}篇关联文档")
        
        lines.append("")
        lines.append("=== 数据引用规则 ===")
        lines.append("1. 研判优先级: 行情信号(涨跌+量比+资金流) >> 基本面/新闻。新闻仅作辅助参考。")
        lines.append("2. 板块涨跌幅来自其代表ETF的K线收盘价")
        lines.append("3. 5日成交额比 = 当日ETF成交额 / 近5日日均成交额，>1放量 <1缩量")
        lines.append("4. 主力资金 = 超大单+大单净流入。机构主导度 = 超大单占比，>0.5说明机构驱动")
        lines.append("5. 综合评分 = 行情分(100%)+新闻分(0%，已关闭)。买入信号必须由行情分驱动")
        lines.append("6. 除权板块的行情分权重降低，不作为趋势判断依据")
        return "\n".join(lines)

    def _ensure_recent_embeddings(self, docs: List[Dict[str, Any]], *, max_docs: int) -> Dict[str, Any]:
        processed = 0
        skipped = 0
        errors: List[str] = []
        for doc in docs[: max(0, int(max_docs or 0))]:
            document_id = int(doc.get("id") or 0)
            if not document_id:
                continue
            try:
                existing = self.repo.list_embeddings(
                    document_id=document_id,
                    provider=self.embedding_service.LOCAL_PROVIDER,
                    model=self.embedding_service.LOCAL_MODEL_NAME,
                    limit=1,
                )
                if existing:
                    skipped += 1
                    continue
                self.embedding_service.embed_document(document_id=document_id, chunk_size=600, overlap=80)
                processed += 1
            except Exception as exc:
                errors.append(f"doc={document_id}: {exc}")
                logger.warning("Failed to pre-embed document %s: %s", document_id, exc, exc_info=True)
        return {
            "processed": processed,
            "skipped": skipped,
            "errors": errors[:5],
        }

    def _retrieve_similar_chunks(self, *, limit_per_query: int = 3) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            for query in self.TOPIC_QUERIES:
                provider, model, vector = self.embedding_service.get_embedding(text=query)
                found = self.repo.search_similar_chunks(
                    query_vector=vector,
                    provider=provider,
                    model=model,
                    limit=limit_per_query,
                )
                for item in found:
                    item = dict(item)
                    item["query"] = query
                    rows.append(item)
        except Exception as exc:
            logger.warning("WeeklySectorPipeline vector retrieval skipped: %s", exc, exc_info=True)
        # dedupe by chunk id while preserving order
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            chunk_id = int(row.get("chunk_id") or 0)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            deduped.append(row)
        return deduped

    def _build_retrieval_context(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "未检索到相似历史 chunk。"
        lines = ["以下是向量检索召回的相似历史/相关 chunk："]
        for idx, row in enumerate(rows[:10], 1):
            lines.append(
                f"{idx}. query={row.get('query','')} | distance={row.get('distance')} | chunk={str(row.get('chunk_text') or '')[:220]}"
            )
        return "\n".join(lines)

    def _build_output_views(self, sector_rows: List[Dict[str, Any]], theme_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        industry_mainline = []
        for row in sector_rows[:3]:
            feature = row.get("structured") or {}
            industry_mainline.append(
                {
                    "name": row.get("sector"),
                    "score": row.get("score"),
                    "doc_count": row.get("doc_count"),
                    "return_5d": feature.get("return_5d"),
                    "amount_ratio_5d": feature.get("amount_ratio_5d"),
                    "heat": feature.get("theme_heat_score"),
                }
            )

        theme_mainline = []
        for row in theme_rows[:3]:
            theme_mainline.append(
                {
                    "name": row.get("theme"),
                    "score": row.get("score"),
                    "doc_count": row.get("doc_count"),
                    "sources": row.get("sources", [])[:3],
                }
            )

        etf_candidates = []
        seen = set()
        for row in sector_rows[:5]:
            linked = ((row.get("structured") or {}).get("metadata") or {}).get("linked_etfs") or []
            for code in linked:
                if code in seen:
                    continue
                seen.add(code)
                etf_candidates.append(
                    {
                        "etf_code": code,
                        "linked_sector": row.get("sector"),
                        "sector_score": row.get("score"),
                        "etf_activity": row.get("etf_activity"),
                    }
                )
        for row in theme_rows[:5]:
            for etf in THEME_TO_ETFS.get(str(row.get("theme") or ""), []):
                code = etf["code"]
                if code in seen:
                    continue
                seen.add(code)
                etf_candidates.append(
                    {
                        "etf_code": code,
                        "linked_theme": row.get("theme"),
                        "theme_score": row.get("score"),
                        "etf_name": etf.get("name"),
                    }
                )
        return {
            "industry_mainline": industry_mainline,
            "theme_mainline": theme_mainline,
            "etf_candidates": etf_candidates,
        }

    def _fallback_report(self, sector_rows: List[Dict[str, Any]], lookback_days: int) -> Dict[str, Any]:
        analysis = []
        for i, row in enumerate(sector_rows[:5], 1):
            analysis.append({
                "sector_name": row.get("sector", "?"),
                "etf_codes": [],
                "ranking": i,
                "confidence": "关注",
                "detailed_reasons": [
                    f"知识库关联{row.get('doc_count', 0)}篇文档，综合评分{row.get('score', 0):.1f}",
                    f"来源: {', '.join(row.get('sources', [])[:4])}",
                ],
                "detailed_risks": [
                    "此为规则聚合草稿，尚未结合LLM深度分析",
                    "涨跌幅和成交额数据请参考下方ETF候选池的结构化数据",
                ],
            })
        return {
            "report_type": "weekly_sector_rotation",
            "lookback_days": lookback_days,
            "summary": "本报告为基于知识库文档热度与来源权重生成的板块周报草稿。",
            "sector_analysis": analysis,
            "footnotes": [
                {"term": "综合评分", "definition": "知识库热度分+涨跌幅加分+成交额加分。知识库热度分=新闻1分+政策3分+ETF公告2分-论坛帖1分。"},
            ],
        }

    def _build_strategy_context(self, strategy_result: Dict[str, Any]) -> str:
        """Build strategy analysis context for LLM deep dive."""
        rankings = strategy_result.get("rankings", [])
        strategy_name = strategy_result.get("strategy", "")
        if not rankings:
            return "暂无策略数据。"

        if strategy_name == "triple_screen":
            lines = [
                "=== 策略引擎：三重滤网（MACD+RSI+突破确认） ===",
                "",
                f"信号说明: oversold_bounce=上升趋势+超卖+突破=最佳买点, breakout=放量突破, avoid=下降趋势不参与",
                "",
                f"  {'代码':<10} {'名称':<20} {'收盘':>8} {'趋势':>8} {'RSI':>6} {'信号':>20} {'量比':>6} {'评分':>6}",
            ]
            for r in rankings[:30]:
                name = (r.get("name") or "")[:18]
                close_val = r.get("close", 0)
                vol_r = r.get("vol_ratio", 0)
                lines.append(
                    f"  {r['code']:<10} {name:<20} {close_val:>8.3f} {r.get('trend',''):>8} "
                    f"{r.get('rsi',0):>6.1f} {r.get('signal',''):>20} {vol_r:>5.2f} "
                    f"{r.get('composite_score',0):>6.1f}"
                )
            return "\n".join(lines)

        if strategy_name == "super_trend":
            lines = [
                "=== 策略引擎：超级趋势增强动量（SuperTrend+曲率拐点+动态止损） ===",
                "",
                f"信号: 曲率拐点+价格突破N日高低点+超趋方向确认=入场。动态止损随时间收紧(1.0→0.5)。",
                "",
                f"  {'代码':<10} {'名称':<18} {'收盘':>7} {'趋势':>6} {'曲率':>7} {'拐点':>4} {'入场':>10} {'止损%':>7} {'评分':>6}",
            ]
            for r in rankings[:30]:
                name = (r.get("name") or "")[:16]
                inf = "Y" if r.get("inflection") else ""
                entry = r.get("entry_type", "none")
                stop = f"{r['stop_pct']:.1f}%" if r.get("stop_pct") else ""
                lines.append(
                    f"  {r['code']:<10} {name:<18} {r.get('close',0):>7.3f} {r.get('trend',''):>6} "
                    f"{r.get('curve_momentum',0):>7.4f} {inf:>4} {entry:>10} {stop:>7} "
                    f"{r.get('composite_score',0):>6.1f}"
                )
            return "\n".join(lines)

        if strategy_name == "ma_slope":
            lines = [
                "=== 策略引擎：均线斜率（MA斜率+通道突破+自适应止损） ===",
                "",
                f"信号: MA斜率>0.1=上升趋势+价格突破N日高点=入场。止损K值0.07/bar衰减(1.0→0.3)。",
                f"加仓: 持有多单+收盘>入场价但<5MA+K线看涨形态=加仓。",
                "",
                f"  {'代码':<10} {'名称':<18} {'收盘':>7} {'趋势':>8} {'斜率%':>7} {'强度':>6} {'入场':>10} {'加仓':>4} {'止损%':>7} {'评分':>6}",
            ]
            for r in rankings[:30]:
                name = (r.get("name") or "")[:16]
                entry = r.get("entry_type", "none")
                add = "Y" if r.get("add_signal") else ""
                stop = f"{r['stop_pct']:.1f}%" if r.get("stop_pct") else ""
                lines.append(
                    f"  {r['code']:<10} {name:<18} {r.get('close',0):>7.3f} {r.get('trend',''):>8} "
                    f"{r.get('ma_slope',0):>7.4f} {r.get('slope_strength',''):>6} {entry:>10} {add:>4} {stop:>7} "
                    f"{r.get('composite_score',0):>6.1f}"
                )
            return "\n".join(lines)

        if strategy_name == "tank300":
            lines = [
                "=== 策略引擎：Tank300（防追高+小市值轮动+复合止损） ===",
                "",
                f"信号: 排除20日涨超40%或5日涨超30%的ETF，按成交额从小到大取前8支。",
                f"复合止损: 10%硬止损 + 5%市场趋势止损。",
                "",
                f"  {'代码':<10} {'名称':<18} {'收盘':>7} {'20日%':>7} {'5日%':>6} {'量比':>6} {'止损%':>7} {'评分':>6}",
            ]
            for r in rankings[:12]:
                name = (r.get("name") or "")[:16]
                sl = (r.get("close",0)-r.get("stop_loss_hard",0))/r.get("close",0)*100 if r.get("close",0)>0 else 0
                lines.append(
                    f"  {r['code']:<10} {name:<18} {r.get('close',0):>7.3f} "
                    f"{r.get('ret_20d',0):>7.1f}% {r.get('ret_5d',0):>6.1f}% "
                    f"{r.get('vol_5d',0):>6.2f} {sl:>6.1f}% "
                    f"{r.get('composite_score',0):>6.1f}"
                )
            return "\n".join(lines)

        if strategy_name == "dynamic_etf":
            lines = [
                "=== 策略引擎：动态ETF轮动（25日对数收益线性拟合+动量评分） ===",
                "",
                f"信号: R²过滤(>{r2_thresh}), 年化收益>={min_ann}%, 成交量+跌幅风控。",
                f"按动量得分从高到低排名。95%固定止损。",
                "",
                f"  {'代码':<10} {'名称':<18} {'收盘':>7} {'年化%':>7} {'R²':>7} {'动量分':>8} {'止损':>7}",
            ]
            for r in rankings[:12]:
                name = (r.get("name") or "")[:16]
                lines.append(
                    f"  {r['code']:<10} {name:<18} {r.get('close',0):>7.3f} "
                    f"{r.get('ann_ret',0):>7.1f}% {r.get('r2',0):>7.3f} "
                    f"{r.get('momentum_score',0):>8.1f} {r.get('stop_loss_95',0):>7.3f}"
                )
            return "\n".join(lines)

        # Default: momentum rotation format
        lines = [
            "=== 策略引擎：动量轮动排名（用于深度分析） ===",
            "",
            f"市场状态: {strategy_result.get('market_regime', '?')}",
            f"研判逻辑: {strategy_result.get('reasoning', '?')}",
            "",
            "以下ETF按动量从高到低排列。20d/10d/5d为各周期的总收益率，加速=5d日均涨速-20d日均涨速(>0=趋势加速中)。",
            "",
            f"  {'代码':<10} {'名称':<20} {'动量分':>6} {'20日':>7} {'10日':>7} {'5日':>7} {'量比':>6} {'加速/天':>8}",
        ]

        for r in rankings[:30]:
            avg5 = r.get("ret_5d", 0) / 5 if r.get("ret_5d") else 0
            avg20 = r.get("ret_20d", 0) / 20 if r.get("ret_20d") else 0
            accel = avg5 - avg20
            accel_str = f"{accel:+.1f}%" if abs(accel) > 0.05 else "—"
            name = (r.get("name") or "")[:18]
            lines.append(
                f"  {r['code']:<10} {name:<20} "
                f"{r.get('momentum_score', 0):>6.1f} "
                f"{r.get('ret_20d', 0):>6.1f}% "
                f"{r.get('ret_10d', 0):>6.1f}% "
                f"{r.get('ret_5d', 0):>6.1f}% "
                f"{r.get('vol_5d', 0):>5.2f} "
                f"{accel_str:>8}"
            )

        return "\n".join(lines)

    def _build_etf_context(self, groups: List[Dict[str, Any]], docs: List[Dict[str, Any]]) -> str:
        """Build grouped ETF context for the LLM prompt (cluster-deduplicated)."""
        lines = ["=== ETF分组排名（同簇/同主题ETF已合并为一个推荐位）===", ""]
        lines.append("评分公式: 综合分 = 涨跌分 + 量比分 + 资金流分")
        lines.append("每组只取最高分ETF作为主推荐，其余放related_etfs")
        lines.append("")

        for i, g in enumerate(groups[:30], 1):
            p = g["primary"]
            s = p["score"]
            adj = " [除权]" if p["is_adjusted"] else ""
            cluster = f" cluster_{g.get('cluster_id')}" if g.get("cluster_id") else ""
            lines.append(
                f"组{i}. {p['code']} {p['name']}{adj}{cluster}"
                f" | 评分={s['total']:.1f} (涨跌={s['price']:.1f} 量比={s['volume']:.1f} 资金={s['flow']:.1f})"
                f" | 5日涨跌={p['ret_5d']:.2f}% 近1日={p['ret_1d']:.2f}%"
                f" | 成交额比={p['vol_5d']:.2f}"
            )
            if g["related"]:
                related_info = ", ".join(
                    f"{r['code']}({r['score']['total']:.1f})" for r in g["related"]
                )
                lines.append(f"   同组ETF(已去重): {related_info}")
            lines.append("")
        return "\n".join(lines)

    def _build_deep_analysis_data(self, strategy_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pre-compute deep analysis data from strategy rankings with REAL numbers.
        
        Returns structured dicts that the LLM will enrich with narrative text.
        All numbers come from the database/strategy engine, NEVER from LLM.
        """
        data: List[Dict[str, Any]] = []
        
        # ── Hilbert Regime (special: market-state, not ETF recommendations) ──
        hs_wrapper = strategy_results.get("hilbert_regime", {})
        hs = hs_wrapper.get("rankings", {}) if isinstance(hs_wrapper, dict) else {}
        if isinstance(hs, dict) and hs.get("avg_period", 0) > 0:
            regime = hs.get("regime", "?")
            period = hs.get("avg_period", 0)
            dt = hs.get("dominant_trend", "?")
            weights = hs.get("strategy_weights", {})
            
            # Rich signals for the regime section
            signals = [
                f"市场周期: {period:.1f}根K线。周期>25为趋势市，<25为震荡市。当前判定: {regime}。",
                f"主导方向: {dt}（基于{hs.get('broad_etfs',0)}支宽基ETF的希尔伯特变换共识）。",
            ]
            if weights:
                w_str = ", ".join(f"{k}={v:.1f}x" for k, v in weights.items())
                signals.append(f"策略权重调整: {w_str}。趋势市中趋势策略（超级趋势/均线斜率）权重放大，震荡市权重收缩。")
            
            detail = hs.get("detail", "")
            signals.append(f"技术细节: {detail}。")
            signals.append(f"操作建议: {hs.get('suggestion', '')}")
            
            data.append({
                "strategy": "hilbert_regime",
                "theme": "希尔伯特择时",
                "code": "",
                "name": "市场状态研判",
                "close": 0,
                "trend_status": f"{regime}(周期{period:.1f}bar,{dt})",
                "signals": signals,
                "warnings": [],
                "entry_suggestion": "",
                "is_regime": True,
            })
        
        strategy_labels = {
            "dynamic_etf": "动态ETF轮动",
            "super_trend": "超级趋势增强动量",
            "triple_screen": "三重滤网",
            "ma_slope": "均线斜率",
        }
        for sname in ["dynamic_etf", "super_trend", "triple_screen", "ma_slope"]:
            sr = strategy_results.get(sname, {})
            rankings = sr.get("rankings", [])
            label = strategy_labels.get(sname, sname)
            
            # Take top 4 with unique themes
            seen_themes = set()
            for r in rankings:
                name = r.get("name", "")
                code = r.get("code", "")
                close = r.get("close", 0)
                # Skip non-equity ETFs
                skip_kw = ["货币", "添利", "华宝添", "银华日", "国债", "债"]
                if any(kw in name for kw in skip_kw) or close > 50:
                    continue
                # Simple theme extraction
                theme = name[:4] if len(name) >= 4 else name
                if theme in seen_themes:
                    continue
                seen_themes.add(theme)
                
                code = r.get("code", "")
                close = r.get("close", 0)
                
                # Build base data with REAL numbers
                item = {
                    "strategy": label,
                    "theme": theme,
                    "code": code,
                    "name": name,
                    "close": close,
                }
                
                if sname == "super_trend":
                    item.update({
                        "trend": r.get("trend", ""),
                        "curve_momentum": r.get("curve_momentum", 0),
                        "entry_type": r.get("entry_type", "none"),
                        "stop_pct": r.get("stop_pct"),
                        "vol_ratio": r.get("vol_ratio", 0),
                        "composite_score": r.get("composite_score", 0),
                    })
                elif sname == "triple_screen":
                    item.update({
                        "trend": r.get("trend", ""),
                        "rsi": r.get("rsi", 0),
                        "signal": r.get("signal", ""),
                        "vol_ratio": r.get("vol_ratio", 0),
                        "composite_score": r.get("composite_score", 0),
                    })
                elif sname == "ma_slope":
                    item.update({
                        "trend": r.get("trend", ""),
                        "ma_slope": r.get("ma_slope", 0),
                        "slope_strength": r.get("slope_strength", ""),
                        "entry_type": r.get("entry_type", "none"),
                        "add_signal": r.get("add_signal", False),
                        "stop_pct": r.get("stop_pct"),
                        "vol_ratio": r.get("vol_ratio", 0),
                        "composite_score": r.get("composite_score", 0),
                    })
                
                # Add fund flow data if available
                try:
                    flow_rows = self.feature_store.get_latest_etf_flow(etf_code=code, limit=1)
                    if flow_rows:
                        f = flow_rows[0]
                        item["flow_main"] = float(f.get("net_inflow_main") or 0)
                        item["flow_ratio"] = float(f.get("net_inflow_ratio") or 0)
                except Exception:
                    pass
                
                # Add ETF features
                try:
                    feats = self.feature_store.list_etf_features(etf_code=code, limit=1)
                    if feats:
                        ft = feats[0]
                        item["ret_5d"] = float(ft.get("return_5d") or 0)
                        item["ret_1d"] = float(ft.get("return_1d") or 0)
                        item["ret_20d"] = float(ft.get("return_20d") or 0)
                        item["amount_ratio_5d"] = float(ft.get("amount_ratio_5d") or 0)
                except Exception:
                    pass
                
                data.append(item)
                if len([x for x in data if x["strategy"] == label]) >= 4:
                    break
        
        return data

    def _llm_deep_analysis(self, deep_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ask LLM to write narrative text. Merges LLM output with original data."""
        if not deep_data:
            return []
        
        prompt = self._build_llm_deep_prompt(deep_data)
        try:
            result = self.llm.safe_call_llm(
                system_prompt="你是ETF分析助手。为每个ETF输出narrative字段(trend_status/signals/warnings/entry_suggestion)。只输出JSON数组，不要修改其他字段。",
                user_prompt=prompt,
                default_structure=[{"trend_status":"","signals":[],"warnings":[],"entry_suggestion":""}]*len(deep_data),
            )
            if isinstance(result, list):
                # Merge LLM narrative back into original data
                for i, item in enumerate(deep_data):
                    if i < len(result):
                        llm_out = result[i]
                        # LLM might wrap in "narrative" key
                        narr = llm_out.get("narrative", llm_out)
                        item["trend_status"] = narr.get("trend_status", "")
                        item["signals"] = narr.get("signals", [])
                        item["warnings"] = narr.get("warnings", [])
                        item["entry_suggestion"] = narr.get("entry_suggestion", "")
                return deep_data
        except Exception as exc:
            logger.warning("LLM deep analysis failed: %s", exc)
        
        # Fallback
        for item in deep_data:
            item.setdefault("trend_status", "待分析")
            item.setdefault("signals", [f"close={item.get('close',0)}"])
            item.setdefault("warnings", ["数据不足"])
            item.setdefault("entry_suggestion", f"当前价格{item.get('close',0)}")
        return deep_data

    def _build_llm_deep_prompt(self, deep_data: List[Dict[str, Any]]) -> str:
        """Build a prompt that asks LLM to write narrative for pre-computed data.
        
        The LLM sees real numbers and only writes text analysis, never invents data.
        """
        import json as _json
        
        lines = [
            "以下是预计算的ETF深度分析数据（所有数字均为真实数据，严禁修改）：",
            "",
            _json.dumps(deep_data, ensure_ascii=False, indent=2),
            "",
            "=== 任务 ===",
            "为上面每个ETF补充以下字段（只修改这些字段，不要改任何数字字段）：",
            "- trend_status: 根据数据判断趋势状态(如'MA斜率强劲上升'或'震荡偏弱')",
            "- signals: 字符串数组，每条30-80字。用上面提供的真实数据来写信号描述。",
            "  格式: 'close={close}, 5日收益={ret_5d}%, 主力净流入={flow_main}万, 净占比={flow_ratio}%'",
            "  严禁编造任何数据，只使用上面JSON中已有的数字。",
            "- warnings: 字符串数组，每条30-80字。基于数据写风险提示。",
            "- entry_suggestion: 50字以上。用close写当前价格，基于stop_pct或均线写回调位和止损位。",
            "",
            "只输出完整的JSON数组，不要额外文字。",
        ]
        return "\n".join(lines)
        """Build grouped ETF context for the LLM prompt (cluster-deduplicated)."""
        lines = ["=== ETF分组排名（同簇/同主题ETF已合并为一个推荐位）===", ""]
        lines.append("评分公式: 综合分 = 涨跌分 + 量比分 + 资金流分")
        lines.append("每组只取最高分ETF作为主推荐，其余放related_etfs")
        lines.append("")

        for i, g in enumerate(groups[:30], 1):
            p = g["primary"]
            s = p["score"]
            fb = "机构主导" if p["flow_bias"] > 0.5 else "散户主导"
            adj = " [除权]" if p["is_adjusted"] else ""
            cluster = f" cluster_{g.get('cluster_id')}" if g.get("cluster_id") else ""
            themes = ", ".join(g.get("themes", [])) if g.get("themes") else ""
            lines.append(
                f"组{i}. {p['code']} {p['name']}{adj}{cluster}"
                f" | 评分={s['total']:.1f} (涨跌={s['price']:.1f} 量比={s['volume']:.1f} 资金={s['flow']:.1f})"
                f" | 5日涨跌={p['ret_5d']:.2f}% 近1日={p['ret_1d']:.2f}%"
                f" | 成交额比={p['vol_5d']:.2f}"
                f" | 主力净流入={_fmt_flow(p['flow_main'])} 净占比={p['flow_ratio']:.1f}% {fb}"
            )
            if themes:
                lines.append(f"   主题: {themes}")
            if g["related"]:
                related_info = ", ".join(
                    f"{r['code']}({r['score']['total']:.1f})" for r in g["related"]
                )
                lines.append(f"   同组ETF(已去重): {related_info}")
            lines.append("")
        return "\n".join(lines)

    def _llm_etf_report(self, etf_context: str, strategy_context: str, groups, lookback_days: int):
        """Generate ETF rankings section. Deep analysis is handled separately."""
        if not groups:
            return None

        prompt = (
            "你是A股ETF投资研究助手。输出JSON。\n"
            "=== 字段 ===\n"
            "report_type, lookback_days, summary(100字), rankings(15个), footnotes\n"
            "=== rankings格式 ===\n"
            "{\"rank\":1,\"primary_etf\":\"512760\",\"primary_name\":\"芯片ETF\",\"score\":66.3,\"reason\":\"基于行情数据\",\"risk\":\"风险提示\"}\n"
            + etf_context[:3000]
        )
        try:
            result = self.llm.safe_call_llm(
                system_prompt="You are an ETF research assistant. Output strict JSON.",
                user_prompt=prompt,
                default_structure={
                    "report_type": "weekly_etf_rotation",
                    "lookback_days": lookback_days,
                    "summary": "",
                    "rankings": [],
                    "footnotes": [],
                },
            )
            return result if isinstance(result, dict) else None
        except Exception as exc:
            logger.warning("ETF LLM report failed: %s", exc)
            return None

    def _fallback_etf_report(self, groups, lookback_days: int):
        """Rule-based ETF report fallback (group-aware)."""
        recs = []
        for i, g in enumerate(groups[:20], 1):
            p = g["primary"]
            s = p["score"]
            recs.append({
                "rank": i, "primary_etf": p["code"], "primary_name": p["name"],
                "related_etfs": [r["code"] for r in g.get("related", [])],
                "score": s["total"],
                "reason": f"涨跌{s['price']} 量比{s['volume']} 资金{s['flow']}",
                "risk": "除权失真" if p["is_adjusted"] else ("资金流出" if p["flow_main"] < 0 else ""),
            })
        return {
            "report_type": "weekly_etf_rotation",
            "lookback_days": lookback_days,
            "summary": "基于行情+资金流+聚类去重的ETF周报。",
            "recommendations": recs,
            "footnotes": [{"term": "综合评分", "definition": "涨跌分+量比分+资金流分。行情100%，新闻0%。"}],
        }

    def _llm_report(
        self,
        *,
        context_text: str,
        structured_text: str,
        sector_rows: List[Dict[str, Any]],
        lookback_days: int,
    ) -> Optional[Dict[str, Any]]:
        if not sector_rows:
            return None

        prompt = f"""
你是A股板块轮动研究助手。你必须严格遵守以下规则，输出一份结构化JSON周报。

=== 硬性规则（违反任何一条即为不合格） ===

R0. 研判优先级（强制）: 行情信号(涨跌+量比+资金流) >> 基本面/新闻。买入推荐必须由行情数据驱动，新闻仅作为背景补充，严禁以新闻热度作为主要推荐理由。具体：
    - detailed_reasons 的 a) 先写资金面信号（主力资金流向和成交额），新闻标题放末尾
    - 若某板块仅有新闻热度但量价和资金流为负，confidence 必须为"关注"
    - 综合评分中新闻分权重暂为0%，行情分占100%

R1. 只输出合法JSON，JSON外不得有任何文字。
R2. JSON必须包含字段: report_type, lookback_days, summary, sector_analysis, footnotes。
   sector_analysis 是一个数组，包含所有有ETF候选的板块（不限3个）。
   footnotes 是一个数组，每项是 {{"term": "术语", "definition": "定义"}}。
   不再输出 top_sectors / top_themes / next_actions / industry_mainline / theme_mainline 字段。

R3. sector_analysis 中每个板块字段: sector_name, etf_codes, ranking, confidence, detailed_reasons, detailed_risks。
   ranking 为整数，1=最强推荐，按综合评分从高到低。
   detailed_reasons 和 detailed_risks 必须是字符串数组，每条至少25个中文字。

R4. detailed_reasons 必须包含:
   a) 基本面信号: 从知识库文档中提取的具体新闻/政策标题和内容概要，至少引用2个文档
   b) 行情信号: 引用代表ETF的涨跌幅和成交额比数据
   c) 逻辑关联: 解释基本面信号与行情数据之间的关联（例如"政策利好尚未反映在价格中"或"消息面热度与成交放量共振"）
    d) 综合评分说明: "{{sector_name}}综合评分{{score}}（行情分{{market_score}}+新闻分{{news_score}}，行情权重70%）
   行情分 = 涨跌分 + 量比分 + 资金流分。涨跌分=5日涨跌×3.0+1日涨跌×2.0。量比分=(5日成交额比-0.7)×10.0。资金流分=主力净占比×0.5+机构主导度×1.5（clamp到[-2,2]）"

R5. detailed_risks 必须包含:
   a) 如果存在除权事件，首先声明
   b) 如果代表ETF近5日涨跌为负，说明回调风险
   c) 如果5日成交额比<0.7，说明流动性不足风险
   d) 如果文档来源单一或数量<3篇，说明信息可靠性风险
   e) 不要笼统写"需关注风险"，必须写出具体数据支撑的风险判断

R6. confidence取值: "强烈推荐"=行情分>10且近5日涨跌>3%且主力净流入>0, "推荐"=行情分>0且近5日涨跌>0, "关注"=其余（含纯新闻驱动板块）。

R7. summary应控制在150字内，概括: 强势板块及其驱动因素、弱势板块及风险来源、整体市场基调。

R8. footnotes必须包含以下术语解释:
   - 综合评分: "综合评分 = 行情分(70%) + 新闻分(30%)。行情分 = 涨跌分 + 量比分 + 资金流分。涨跌分=5日涨跌×3.0+1日涨跌×2.0。量比分=(5日成交额比-0.7)×10.0。资金流分=主力净占比×0.5+机构主导度×1.5（clamp到[-2,2]）。新闻分 = (知识库文档得分+热度分)×0.3。正分=行情强势，负分=弱势。除权板块行情分权重减半。"
   - 5日成交额比: "代表ETF当日成交额 ÷ 该ETF近5个交易日日均成交额。>1.0表示当日放量，<1.0表示缩量。"
   - 近5日涨跌: "代表ETF最近5个交易日收盘价涨跌幅(%)， = (今日收盘 - 5个交易日前的收盘) ÷ 5个交易日前的收盘 × 100。"
   - 除权事件: "ETF发生份额拆分/合并或分红导致价格跳空。标注除权的板块，其收益率不含除权前时段，不作为趋势判断依据。"
   如果未来报告中出现新术语，也必须在此解释。

=== 指标速查 ===
- 5日成交额比 = 代表ETF当日成交额÷该ETF近5日日均成交额。>1.0=放量，<1.0=缩量，<0.7=明显萎缩，>1.3=显著放大
- 综合评分 = 行情分(100%) + 新闻分(0%，已关闭)。行情分=涨跌分+量比分+资金流分。涨跌分=5日涨跌×3.0+1日涨跌×2.0。量比分=(5日成交额比-0.7)×10.0。资金流分=主力净占比×0.5+机构主导度×1.5（clamp到[-2,2]）。新闻分=(文档得分+热度)×0.15

=== 输入数据 ===

{context_text}

{structured_text}

（注：只使用上述数据进行分析，不需要引用主题/风格层数据）
        """.strip()

        try:
            default_structure = {
                "report_type": "weekly_sector_rotation",
                "lookback_days": lookback_days,
                "summary": "",
                "sector_analysis": [],
                "footnotes": [],
            }
            result = self.llm.safe_call_llm(
                system_prompt="You are a disciplined A-share sector research assistant that outputs strict JSON.",
                user_prompt=prompt,
                default_structure=default_structure,
            )
            if isinstance(result, dict):
                return result
        except Exception as exc:
            logger.warning("WeeklySectorPipeline LLM draft failed: %s", exc, exc_info=True)
        return None

    def run(
        self,
        *,
        user_id: Optional[int] = None,
        lookback_days: int = 7,
        doc_limit: int = DEFAULT_DOC_LIMIT,
        refresh_etf_universe: bool = True,
        backfill_etf_data: bool = False,  # Full ETF backfill is a separate weekend job
    ) -> Dict[str, Any]:
        # ── Phase 0: ETF Universe Refresh ────────────────────────
        universe_info = {"etf_count": 0, "refreshed": False, "flow_snapshot": None}
        if refresh_etf_universe:
            try:
                from app.services.etf_universe import get_etf_universe_service
                universe = get_etf_universe_service()
                etfs = universe.refresh(force=False)
                universe_info = {
                    "etf_count": len(etfs),
                    "refreshed": True,
                    "threshold": universe.turnover_threshold,
                    "last_refresh": universe.last_refresh,
                }
                logger.info(
                    "ETF universe: %d ETFs (turnover >= %.0f亿)",
                    len(etfs), universe.turnover_threshold / 1e8,
                )

                # Capture ETF fund flow (today + recent cumulative)
                flow_result = universe.capture_flow_history(days=30)
                universe_info["flow_snapshot"] = flow_result
                if flow_result.get("success"):
                    logger.info(
                        "ETF flow snapshot: %d/%d ETFs stored",
                        flow_result.get("stored"), flow_result.get("etf_count"),
                    )
            except Exception as exc:
                logger.warning("ETF universe refresh skipped: %s", exc)

        # ── Phase 1: ETF Data Backfill ──────────────────────────
        if backfill_etf_data and universe_info["etf_count"] > 0:
            try:
                from app.services.etf_universe import get_etf_universe_service
                from app.services.kline import KlineService
                from app.services.sector_feature_service import get_sector_feature_service
                from app.utils.trading_calendar import get_trading_days_between

                universe = get_etf_universe_service()
                all_etfs = universe.get_etf_list()
                today = datetime.now().strftime("%Y-%m-%d")
                # Backfill last 10 calendar days (covers ~7 trading days)
                start_backfill = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
                trading_days = get_trading_days_between(start_backfill, today)

                if trading_days and all_etfs:
                    kline = KlineService()
                    feature_store = get_sector_feature_service()
                    etf_done = 0
                    for etf in all_etfs[: min(len(all_etfs), 500)]:  # safety cap
                        code = etf["code"]
                        name = etf["name"]
                        for as_of_date in trading_days:
                            try:
                                bt = int((datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)).timestamp())
                                rows = kline.get_kline(
                                    market="CNStock", symbol=code,
                                    timeframe="1D", limit=60, before_time=bt,
                                )
                                if not rows or len(rows) < 2:
                                    continue
                                # Store raw bars and ETF features (same logic as sector_feature_builder)
                                from app.services.sector_feature_builder import _pct_change
                                normalized = []
                                for row in rows:
                                    cv = float(row.get("close") or 0)
                                    if cv <= 0:
                                        continue
                                    tv = int(row.get("time") or 0)
                                    bd = datetime.fromtimestamp(tv).strftime("%Y-%m-%d") if tv else as_of_date
                                    bp = {
                                        "close_price": cv,
                                        "open_price": float(row.get("open") or 0),
                                        "high_price": float(row.get("high") or 0),
                                        "low_price": float(row.get("low") or 0),
                                        "volume": float(row.get("volume") or 0),
                                        "turnover_amount": float(row.get("amount") or row.get("volume") or 0),
                                    }
                                    feature_store.upsert_etf_market_bar("CNStock", code, bd, bp)
                                    normalized.append({"close_price": cv, "turnover_amount": bp["turnover_amount"], "as_of_date": bd})

                                if len(normalized) >= 2:
                                    closes = [b["close_price"] for b in normalized]
                                    amounts = [b["turnover_amount"] for b in normalized]
                                    adj_idx = 0
                                    for i in range(1, len(closes)):
                                        if abs(_pct_change(closes[i], closes[i - 1])) > 20:
                                            adj_idx = i
                                            break
                                    eff_c = closes[adj_idx:] if adj_idx else closes
                                    eff_a = amounts[adj_idx:] if adj_idx else amounts
                                    feature = {
                                        "close_price": eff_c[-1] if eff_c else 0,
                                        "return_1d": _pct_change(eff_c[-1], eff_c[-2]) if len(eff_c) >= 2 else 0,
                                        "return_5d": _pct_change(eff_c[-1], eff_c[-6]) if len(eff_c) >= 6 else 0,
                                        "return_20d": _pct_change(eff_c[-1], eff_c[-21]) if len(eff_c) >= 21 else 0,
                                        "turnover_amount": eff_a[-1] if eff_a else 0,
                                        "etf_avg_amount_5d": sum(eff_a[-5:]) / max(1, len(eff_a[-5:])),
                                        "amount_ratio_5d": (eff_a[-1] / (sum(eff_a[-5:]) / max(1, len(eff_a[-5:])))) if sum(eff_a[-5:]) > 0 else 0,
                                    }
                                    if adj_idx:
                                        feature["adj_event_detected"] = True
                                    feature_store.upsert_etf_feature("CNStock", code, name, "", as_of_date, feature)
                                    etf_done += 1
                            except Exception:
                                pass
                    logger.info("ETF backfill: %d ETF-day features stored", etf_done)
            except Exception as exc:
                logger.warning("ETF data backfill skipped: %s", exc)

        # ── Phase 2: ETF Ranking & LLM Report ───────────────────
        docs = self._fetch_recent_documents(lookback_days=lookback_days, limit=doc_limit)
        embed_prep = self._ensure_recent_embeddings(docs, max_docs=self.DEFAULT_EMBED_WARM_DOCS)

        # Build ETF rankings from universe + features + flow
        ranked = self._load_etf_rankings(etfs) if etfs else []
        groups = self._group_etfs(ranked)

        # ── Phase 2.5: Strategy Engines ──────────────────────────
        strategy_results: Dict[str, Any] = {}
        strategies_to_run = ["hilbert_regime", "dynamic_etf", "super_trend", "triple_screen", "ma_slope"]
        try:
            from app.services.llm_advisor import suggest_params
            from app.services.strategy_engine import run_strategy

            for sname in strategies_to_run:
                try:
                    advisor_output = suggest_params(strategy_name=sname)
                    merged_params = {**advisor_output.get("params", {}),
                                   "early_signals": advisor_output.get("early_signals", [])}
                    sr = run_strategy(strategy_name=sname, params=merged_params)
                    sr["market_regime"] = advisor_output.get("market_regime", "unknown")
                    sr["reasoning"] = advisor_output.get("reasoning", "")
                    strategy_results[sname] = sr
                    logger.info("Strategy %s: regime=%s, rankings=%d",
                               sname, advisor_output.get("market_regime"), len(sr.get("rankings", [])))
                except Exception as exc:
                    logger.warning("Strategy %s skipped: %s", sname, exc)
        except Exception as exc:
            logger.warning("Strategy engines skipped: %s", exc)

        # ── Deep Analysis: Python pre-computes all numbers, LLM writes narrative ──
        deep_data = self._build_deep_analysis_data(strategy_results)
        deep_report = self._llm_deep_analysis(deep_data) if deep_data else []

        # Build context for LLM
        etf_context = self._build_etf_context(groups, docs)
        report = self._llm_etf_report(etf_context, "", groups, lookback_days)
        if not report:
            report = self._fallback_etf_report(groups, lookback_days)
        # Merge Python-computed deep analysis with LLM narrative
        if isinstance(report, dict) and deep_report:
            report["deep_analysis"] = deep_report

        result = {
            "success": True,
            "user_id": user_id,
            "generated_at": _to_iso(datetime.now(timezone.utc)),
            "etf_universe": universe_info,
            "window": {
                "lookback_days": lookback_days,
                "doc_limit": doc_limit,
                "doc_count": len(docs),
                "etf_count": len(ranked),
            },
            "embedding_prep": embed_prep,
            "etf_rankings": ranked[:30],
            "etf_groups": groups[:20],
            "strategy": strategy_results,
            "report": report,
        }

        self._save_report(result)
        return result

    def _save_report(self, result: Dict[str, Any]) -> None:
        """Persist the weekly report to JSON and readable text files."""
        import json
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[3]
        json_path = backend_dir / "weekly_report_output.json"
        txt_path = backend_dir / "weekly_report_readable.txt"

        try:
            json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Weekly report JSON saved to %s", json_path)
        except Exception as exc:
            logger.warning("Failed to save weekly report JSON: %s", exc)

        try:
            report = result.get("report", {})
            if isinstance(report, str):
                import json as _json
                report = _json.loads(report)
            recs = report.get("recommendations") or report.get("rankings", [])
            lines = [
                "=" * 60,
                "        ETF 周度推荐报告",
                "=" * 60,
                f"生成时间: {result['generated_at']}",
                f"ETF池: {result['window'].get('etf_count', '-')} 支 (A股, 成交额>=1亿)",
                "",
                "【摘要】",
                str(report.get("summary", "N/A")),
                "",
            ]

            lines.append("【ETF推荐】（按综合评分+主题多样性排列）")
            for r in recs:
                rank = r.get("rank", "?")
                code = r.get("primary_etf", "?")
                name = r.get("primary_name", "")
                score = r.get("score", 0)
                reason = r.get("reason", "")
                risk = r.get("risk", "")
                related = r.get("related_etfs", [])

                lines.append(f"\n{'─' * 60}")
                lines.append(f" #{rank}  {code} {name}  |  评分: {score}")
                lines.append(f"    推荐理由: {reason}")
                if risk:
                    lines.append(f"    风险提示: {risk}")
                if related:
                    lines.append(f"    同主题ETF: {', '.join(related)}")

            # Deep analysis - grouped by strategy
            deep = report.get("deep_analysis", [])
            if deep:
                # Group by strategy
                from collections import defaultdict
                by_strategy = defaultdict(list)
                for da in deep:
                    sname = da.get("strategy", "其他策略")
                    by_strategy[sname].append(da)

                strategy_labels = {
                    "super_trend": "超级趋势增强动量",
                    "triple_screen": "三重滤网",
                }
                lines.append("")
                lines.append(f"{'─' * 60}")
                lines.append("")
                lines.append("【深度分析】")
                for sname in ["super_trend", "triple_screen"]:
                    items = by_strategy.get(sname, [])
                    if not items:
                        continue
                    label = strategy_labels.get(sname, sname)
                    lines.append(f"\n  --- {label} ---")
                    for da in items:
                        theme = da.get("theme", "")
                        trend = da.get("trend_status", "")
                        lines.append(f"\n    ■ {theme} — {trend}")
                        for sig in da.get("signals", []):
                            lines.append(f"      + {sig}")
                        for warn in da.get("warnings", []):
                            lines.append(f"      ! {warn}")
                        entry = da.get("entry_suggestion", "")
                        if entry:
                            lines.append(f"      → 入场建议: {entry}")

            # Footnotes
            footnotes = report.get("footnotes", [])
            if footnotes:
                lines.append("")
                lines.append(f"{'─' * 60}")
                lines.append("")
                lines.append("【术语注释】")
                for fn in footnotes:
                    lines.append(f"  · {fn.get('term', '')}: {fn.get('definition', '')}")

            lines.append("")
            lines.append("=" * 60)
            lines.append("报告结束")
            lines.append("=" * 60)

            txt_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Weekly report text saved to %s", txt_path)
        except Exception as exc:
            logger.warning("Failed to save weekly report text: %s", exc)


_daily_report_pipeline: Optional[DailyReportPipeline] = None


def get_daily_report_pipeline() -> DailyReportPipeline:
    global _daily_report_pipeline
    if _daily_report_pipeline is None:
        _daily_report_pipeline = DailyReportPipeline()
    return _daily_report_pipeline


# Backward compatibility: keep old names as aliases while callers migrate.
WeeklySectorPipeline = DailyReportPipeline


def get_weekly_sector_pipeline() -> DailyReportPipeline:
    return get_daily_report_pipeline()
