"""Focused media ingestor for curated financial media sources."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.services.rag_ingest.news_ingestor import NewsIngestor
from app.services.rag_ingest.source_registry import SourceDefinition, list_sources


class MediaIngestor:
    """Collect curated financial media/news sources via search-driven queries."""

    def __init__(self) -> None:
        self.news_ingestor = NewsIngestor()

    def get_enabled_sources(self) -> List[SourceDefinition]:
        return [
            source
            for source in list_sources(region="CN", category="media", enabled_only=True)
            if source.source_id in {"cn_cls", "cn_stcn", "cn_cs", "cn_cnstock", "cn_wallstreetcn", "cn_eastmoney_news"}
        ]

    def ingest_registry_sources(
        self,
        *,
        user_id: Optional[int] = None,
        days: int = 2,
        max_results: int = 6,
    ) -> Dict[str, object]:
        return self.news_ingestor.ingest_registry_sources(
            user_id=user_id,
            days=days,
            max_results=max_results,
        )


_media_ingestor: Optional[MediaIngestor] = None


def get_media_ingestor() -> MediaIngestor:
    global _media_ingestor
    if _media_ingestor is None:
        _media_ingestor = MediaIngestor()
    return _media_ingestor
