"""Forum and community sentiment ingestor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.rag_ingest.source_registry import SourceDefinition, list_sources
from app.services.search import get_search_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ForumIngestor:
    """Collect second-phase community/forum sentiment documents."""

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()

    def get_enabled_sources(self) -> List[SourceDefinition]:
        return list_sources(region="CN", category="forum", enabled_only=True)

    def ingest_registry_sources(
        self,
        *,
        user_id: Optional[int] = None,
        days: int = 2,
        max_results: int = 6,
    ) -> Dict[str, Any]:
        search_service = get_search_service()
        if not search_service.is_available:
            return {
                "success": False,
                "message": "Search service is not available",
                "ingested": 0,
                "sources": [],
            }

        source_queries: Dict[str, List[str]] = {
            "cn_xueqiu": [
                "site:xueqiu.com A股 板块 热门 讨论",
                "site:xueqiu.com ETF 热门 讨论 A股",
            ],
            "cn_guba": [
                "site:eastmoney.com 股吧 A股 热门 板块",
                "site:eastmoney.com 股吧 ETF 热门 讨论",
            ],
            "cn_10jqka_forum": [
                "site:10jqka.com.cn A股 社区 热门 板块",
                "site:10jqka.com.cn ETF 社区 热门 讨论",
            ],
        }

        ingested = 0
        source_stats: List[Dict[str, Any]] = []
        for source in self.get_enabled_sources():
            queries = source_queries.get(source.source_id)
            if not queries:
                continue

            source_count = 0
            query_stats: List[Dict[str, Any]] = []
            for query in queries:
                try:
                    response = search_service.search_with_fallback(query, max_results=max_results, days=days)
                    query_count = 0
                    for item in response.to_list():
                        title = str(item.get("title") or "").strip()
                        snippet = str(item.get("snippet") or "").strip()
                        url = str(item.get("link") or "").strip()
                        published = str(item.get("published") or "").strip()
                        body = "\n\n".join([part for part in [title, snippet] if part])
                        self.repo.upsert_document(
                            user_id=user_id,
                            market="CNStock",
                            doc_type="forum",
                            title=title,
                            source=source.name,
                            url=url,
                            published_at=published or None,
                            lang="zh-CN",
                            raw_text=body,
                            clean_text=body,
                            summary=snippet,
                            sector_tags=[],
                            symbol_tags=[],
                            etf_tags=[],
                            metadata={
                                "source_id": source.source_id,
                                "tier": source.tier,
                                "query": query,
                                "provider": response.provider,
                                "category": source.category,
                            },
                        )
                        query_count += 1
                        source_count += 1
                        ingested += 1
                    query_stats.append(
                        {
                            "query": query,
                            "provider": response.provider,
                            "success": response.success,
                            "ingested_count": query_count,
                        }
                    )
                except Exception as exc:
                    logger.warning("Forum ingest failed for %s / %s: %s", source.source_id, query, exc, exc_info=True)
                    query_stats.append(
                        {
                            "query": query,
                            "provider": "unknown",
                            "success": False,
                            "ingested_count": 0,
                            "error": str(exc),
                        }
                    )

            source_stats.append(
                {
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "tier": source.tier,
                    "ingested": source_count,
                    "queries": query_stats,
                }
            )

        return {
            "success": True,
            "message": "Forum ingest completed",
            "ingested": ingested,
            "sources": source_stats,
        }


_forum_ingestor: Optional[ForumIngestor] = None


def get_forum_ingestor() -> ForumIngestor:
    global _forum_ingestor
    if _forum_ingestor is None:
        _forum_ingestor = ForumIngestor()
    return _forum_ingestor
