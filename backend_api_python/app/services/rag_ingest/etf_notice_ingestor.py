"""ETF and fund notice ingestor.

First-stage implementation now prefers direct collection for exchange / ETF
pages and uses search-driven fallback where direct parsing is not yet stable.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import requests

from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.services.rag_ingest.source_registry import SourceDefinition, list_sources
from app.services.rag_ingest.tagging_service import build_tags
from app.services.search import get_search_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ETFNoticeIngestor:
    """Collect ETF/fund notices from official exchange and disclosure channels."""

    DIRECT_TIMEOUT = 15

    DIRECT_ENDPOINTS: Dict[str, Dict[str, str]] = {
        "cn_sse_etf": {
            "url": "https://etf.sse.com.cn/fundtrends/",
            "kind": "html_links",
        },
        "cn_sse": {
            "url": "https://www.sse.com.cn/assortment/fund/etf/home/",
            "kind": "html_links",
        },
        "cn_szse": {
            "url": "https://www.szse.cn/disclosure/fund/index.html",
            "kind": "html_links",
        },
        "cn_cninfo": {
            "url": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
            "kind": "html_links",
        },
        "cn_fund_company": {
            "url": "https://fund.eastmoney.com/ETF/",
            "kind": "html_links",
        },
    }

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()

    def get_enabled_sources(self) -> List[SourceDefinition]:
        categories = {"etf_notice", "disclosure", "exchange"}
        return [
            source
            for source in list_sources(region="CN", enabled_only=True)
            if source.category in categories and source.source_id in {"cn_sse_etf", "cn_sse", "cn_szse", "cn_cninfo", "cn_fund_company"}
        ]

    def _headers(self, source: SourceDefinition) -> Dict[str, str]:
        return {
            "User-Agent": f"Mozilla/5.0 (compatible; AI-TraderETFNoticeIngestor/1.0; {source.source_id})",
            "Accept": "application/json, text/html, */*",
            "Referer": source.base_url or "https://www.ai-trader.com/",
        }

    def _extract_links_from_html(self, html: str, source: SourceDefinition) -> List[Dict[str, str]]:
        link_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        rows: List[Dict[str, str]] = []
        seen = set()
        for href, title_html in link_pattern.findall(html or ""):
            title = re.sub(r"<[^>]+>", "", title_html or "")
            title = re.sub(r"\s+", " ", title).strip()
            if not href or not title or len(title) < 6:
                continue
            if href.startswith("javascript:") or href.startswith("#"):
                continue
            if source.base_url and href.startswith("/"):
                href = source.base_url.rstrip("/") + href
            if not href.startswith("http") and source.base_url:
                href = source.base_url.rstrip("/") + "/" + href.lstrip("/")
            if href in seen:
                continue
            seen.add(href)
            rows.append({"title": title[:300], "url": href, "summary": title[:300]})
            if len(rows) >= 10:
                break
        return rows

    def _direct_fetch(self, source: SourceDefinition) -> List[Dict[str, str]]:
        cfg = self.DIRECT_ENDPOINTS.get(source.source_id)
        if not cfg:
            return []
        try:
            resp = requests.get(
                cfg["url"],
                headers=self._headers(source),
                timeout=self.DIRECT_TIMEOUT,
            )
            resp.raise_for_status()
            return self._extract_links_from_html(resp.text, source)
        except Exception as exc:
            logger.warning("Direct ETF notice fetch failed for %s: %s", source.source_id, exc, exc_info=True)
            return []

    def _save_direct_rows(
        self,
        *,
        source: SourceDefinition,
        rows: List[Dict[str, str]],
        user_id: Optional[int],
    ) -> int:
        inserted = 0
        for row in rows:
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            summary = str(row.get("summary") or title).strip()
            body = "\n\n".join([part for part in [title, summary] if part])
            tags = build_tags(body)
            self.repo.upsert_document(
                user_id=user_id,
                market="CNStock",
                doc_type="etf_notice",
                title=title,
                source=source.name,
                url=url,
                published_at=None,
                lang="zh-CN",
                raw_text=body,
                clean_text=body,
                summary=summary,
                sector_tags=tags["sector_tags"],
                industry_tags=tags["industry_tags"],
                theme_tags=tags["theme_tags"],
                symbol_tags=[],
                etf_tags=tags["etf_tags"],
                metadata={
                    "source_id": source.source_id,
                    "tier": source.tier,
                    "mode": "direct",
                    "category": source.category,
                },
            )
            inserted += 1
        return inserted

    def ingest_registry_sources(
        self,
        *,
        user_id: Optional[int] = None,
        days: int = 7,
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
            "cn_sse_etf": [
                "site:etf.sse.com.cn ETF 公告 最新",
                "site:etf.sse.com.cn 基金 公告 最新",
            ],
            "cn_sse": [
                "site:sse.com.cn 基金公告 ETF 最新",
                "site:sse.com.cn ETF 申购赎回 清单 最新",
            ],
            "cn_szse": [
                "site:szse.cn 基金公告 ETF 最新",
                "site:szse.cn ETF 基金 公告 最新",
            ],
            "cn_cninfo": [
                "site:cninfo.com.cn ETF 公告 最新",
                "site:cninfo.com.cn 基金 公告 最新",
            ],
            "cn_fund_company": [
                "ETF 基金公司 公告 最新",
                "基金 管理人 ETF 公告 最新",
            ],
        }

        ingested = 0
        source_stats: List[Dict[str, Any]] = []
        for source in self.get_enabled_sources():
            source_count = 0
            query_stats: List[Dict[str, Any]] = []

            if source.mode == "direct":
                direct_rows = self._direct_fetch(source)
                if direct_rows:
                    source_count += self._save_direct_rows(source=source, rows=direct_rows, user_id=user_id)
                    ingested += source_count
                    source_stats.append(
                        {
                            "source_id": source.source_id,
                            "source_name": source.name,
                            "tier": source.tier,
                            "ingested": source_count,
                            "mode": "direct",
                            "queries": [],
                        }
                    )
                    continue

            queries = source_queries.get(source.source_id)
            if not queries:
                continue

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
                        tags = build_tags(body)
                        self.repo.upsert_document(
                            user_id=user_id,
                            market="CNStock",
                            doc_type="etf_notice",
                            title=title,
                            source=source.name,
                            url=url,
                            published_at=published or None,
                            lang="zh-CN",
                            raw_text=body,
                            clean_text=body,
                            summary=snippet,
                            sector_tags=tags["sector_tags"],
                            industry_tags=tags["industry_tags"],
                            theme_tags=tags["theme_tags"],
                            symbol_tags=[],
                            etf_tags=tags["etf_tags"],
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
                    logger.warning("ETF notice ingest failed for %s / %s: %s", source.source_id, query, exc, exc_info=True)
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
                    "mode": "search_fallback",
                    "queries": query_stats,
                }
            )

        return {
            "success": True,
            "message": "ETF notice ingest completed",
            "ingested": ingested,
            "sources": source_stats,
        }


_etf_notice_ingestor: Optional[ETFNoticeIngestor] = None


def get_etf_notice_ingestor() -> ETFNoticeIngestor:
    global _etf_notice_ingestor
    if _etf_notice_ingestor is None:
        _etf_notice_ingestor = ETFNoticeIngestor()
    return _etf_notice_ingestor
