"""News ingestor for the first-stage RAG knowledge base.

This service pulls A-share relevant news via the existing SearchService,
normalizes the results, and upserts them into qd_rag_documents.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.rag_ingest.source_registry import SourceDefinition, list_sources
from app.services.rag_ingest.tagging_service import build_tags, clean_text
from app.services.search import get_search_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


DEFAULT_CN_NEWS_QUERIES = [
    "A股 市场热点 最新消息",
    "A股 板块轮动 最新消息",
    "A股 政策 利好 最新",
    "ETF 市场 热点 A股",
    "半导体 算力 新能源 证券 板块 A股 最新",
]


SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "半导体": ["半导体", "芯片", "晶圆", "光刻", "封装"],
    "算力": ["算力", "光模块", "CPO", "GPU", "AI服务器", "液冷"],
    "新能源车": ["新能源车", "锂电", "电池", "充电桩", "智驾"],
    "券商": ["券商", "证券", "两融", "投行"],
    "军工": ["军工", "航空发动机", "卫星", "导弹"],
    "医药": ["医药", "创新药", "CRO", "医疗器械"],
    "消费电子": ["消费电子", "苹果链", "折叠屏", "面板"],
    "电力设备": ["电网", "特高压", "储能", "风电", "光伏"],
}


class NewsIngestor:
    """Fetch and persist A-share relevant news documents."""

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()

    def get_enabled_sources(self) -> List[SourceDefinition]:
        return list_sources(region="CN", category="media", enabled_only=True)

    def ingest_queries(
        self,
        *,
        queries: Optional[List[str]] = None,
        days: int = 1,
        max_results: int = 8,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        search_service = get_search_service()
        if not search_service.is_available:
            return {
                "success": False,
                "message": "Search service is not available",
                "ingested": 0,
                "queries": [],
            }

        all_queries = queries or list(DEFAULT_CN_NEWS_QUERIES)
        ingested = 0
        query_stats: List[Dict[str, Any]] = []

        for query in all_queries:
            try:
                response = search_service.search_with_fallback(
                    query,
                    max_results=max_results,
                    days=max(1, min(int(days or 1), 30)),
                )
                inserted_for_query = 0
                for item in response.to_list():
                    title = clean_text(item.get("title"))
                    snippet = clean_text(item.get("snippet"))
                    source = clean_text(item.get("source"))
                    url = clean_text(item.get("link"))
                    published = clean_text(item.get("published"))
                    body = "\n\n".join(x for x in [title, snippet] if x)

                    tags = build_tags(body)
                    sector_tags = tags["sector_tags"]
                    etf_tags = tags["etf_tags"]
                    metadata = {
                        "query": query,
                        "provider": response.provider,
                        "sentiment": item.get("sentiment") or "neutral",
                        "ingestor": "NewsIngestor",
                    }

                    self.repo.upsert_document(
                        user_id=user_id,
                        market="CNStock",
                        doc_type="news",
                        title=title,
                        source=source,
                        url=url,
                        published_at=published or None,
                        lang="zh-CN",
                        raw_text=body,
                        clean_text=body,
                        summary=snippet,
                        sector_tags=sector_tags,
                        industry_tags=tags["industry_tags"],
                        theme_tags=tags["theme_tags"],
                        symbol_tags=[],
                        etf_tags=etf_tags,
                        metadata=metadata,
                    )
                    inserted_for_query += 1
                    ingested += 1

                query_stats.append(
                    {
                        "query": query,
                        "provider": response.provider,
                        "success": response.success,
                        "result_count": len(response.results or []),
                        "ingested_count": inserted_for_query,
                    }
                )
            except Exception as exc:
                logger.warning("News ingest failed for query %s: %s", query, exc, exc_info=True)
                query_stats.append(
                    {
                        "query": query,
                        "provider": "unknown",
                        "success": False,
                        "result_count": 0,
                        "ingested_count": 0,
                        "error": str(exc),
                    }
                )

        return {
            "success": True,
            "message": "News ingest completed",
            "ingested": ingested,
            "queries": query_stats,
        }

    def ingest_registry_sources(
        self,
        *,
        user_id: Optional[int] = None,
        days: int = 1,
        max_results: int = 6,
    ) -> Dict[str, Any]:
        source_queries: Dict[str, List[str]] = {
            "cn_cls": [
                "site:cls.cn A股 快讯 最新",
                "site:cls.cn 板块 轮动 A股",
            ],
            "cn_stcn": [
                "site:stcn.com A股 板块 最新",
                "site:stcn.com e公司 板块 轮动",
            ],
            "cn_cs": [
                "site:cs.com.cn A股 板块 最新",
                "site:cs.com.cn 中证快讯 A股",
            ],
            "cn_cnstock": [
                "site:cnstock.com A股 板块 最新",
                "site:cnstock.com 产业资讯 A股",
            ],
            "cn_wallstreetcn": [
                "site:wallstreetcn.com A股 科技 板块",
                "site:wallstreetcn.com 中国市场 最新",
            ],
            "cn_eastmoney_news": [
                "site:eastmoney.com A股 板块 最新",
                "site:eastmoney.com 财经 快讯 A股",
            ],
        }

        total_ingested = 0
        details: List[Dict[str, Any]] = []
        for source in self.get_enabled_sources():
            queries = source_queries.get(source.source_id)
            if not queries:
                continue
            result = self.ingest_queries(
                queries=queries,
                days=days,
                max_results=max_results,
                user_id=user_id,
            )
            total_ingested += int(result.get("ingested") or 0)
            details.append(
                {
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "tier": source.tier,
                    "ingested": int(result.get("ingested") or 0),
                    "queries": result.get("queries") or [],
                }
            )

        return {
            "success": True,
            "message": "Registry media ingest completed",
            "ingested": total_ingested,
            "sources": details,
        }


_news_ingestor: Optional[NewsIngestor] = None


def get_news_ingestor() -> NewsIngestor:
    global _news_ingestor
    if _news_ingestor is None:
        _news_ingestor = NewsIngestor()
    return _news_ingestor
