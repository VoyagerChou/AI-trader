"""RAG ingestion services.

This package contains the first-stage building blocks for a lightweight
research knowledge base: document persistence and source-specific ingestors.
"""

from app.services.rag_ingest.rag_document_repository import (
    RAGDocumentRepository,
    get_rag_document_repository,
)
from app.services.rag_ingest.news_ingestor import (
    NewsIngestor,
    get_news_ingestor,
)
from app.services.rag_ingest.policy_ingestor import (
    PolicyIngestor,
    get_policy_ingestor,
)
from app.services.rag_ingest.media_ingestor import (
    MediaIngestor,
    get_media_ingestor,
)
from app.services.rag_ingest.etf_notice_ingestor import (
    ETFNoticeIngestor,
    get_etf_notice_ingestor,
)
from app.services.rag_ingest.forum_ingestor import (
    ForumIngestor,
    get_forum_ingestor,
)
from app.services.rag_ingest.embedding_service import (
    EmbeddingService,
    get_embedding_service,
)
from app.services.rag_ingest.tagging_service import (
    build_tags,
    extract_etf_tags,
    extract_sector_tags,
    extract_theme_tags,
)
from app.services.rag_ingest.source_registry import (
    SourceDefinition,
    SOURCES,
    get_source,
    group_sources_by_category,
    group_sources_by_region,
    list_sources,
)


def get_weekly_sector_pipeline():
    from app.services.rag_ingest.weekly_sector_pipeline import get_weekly_sector_pipeline as _getter

    return _getter()

__all__ = [
    "RAGDocumentRepository",
    "get_rag_document_repository",
    "NewsIngestor",
    "get_news_ingestor",
    "PolicyIngestor",
    "get_policy_ingestor",
    "MediaIngestor",
    "get_media_ingestor",
    "ETFNoticeIngestor",
    "get_etf_notice_ingestor",
    "ForumIngestor",
    "get_forum_ingestor",
    "get_weekly_sector_pipeline",
    "EmbeddingService",
    "get_embedding_service",
    "build_tags",
    "extract_etf_tags",
    "extract_sector_tags",
    "extract_theme_tags",
    "SourceDefinition",
    "SOURCES",
    "get_source",
    "group_sources_by_category",
    "group_sources_by_region",
    "list_sources",
]
