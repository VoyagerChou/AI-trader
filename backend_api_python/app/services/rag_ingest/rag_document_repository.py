"""RAG document repository.

First-stage persistence layer for a lightweight research knowledge base.
Stores normalized documents and optional text chunks in PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


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


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _clean_text(text: Any) -> str:
    value = str(text or "")
    value = value.replace("\r", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _build_doc_key(*, doc_type: str, source: str, url: str, title: str, published_at: str) -> str:
    base = "|".join([
        str(doc_type or "").strip().lower(),
        str(source or "").strip().lower(),
        str(url or "").strip(),
        str(title or "").strip(),
        str(published_at or "").strip(),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class RAGDocumentRepository:
    """Persistence helper for normalized RAG documents and chunks."""

    def __init__(self) -> None:
        self.ensure_schema()

    def ensure_schema(self) -> None:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_rag_documents (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER,
                        market VARCHAR(50) NOT NULL DEFAULT 'CNStock',
                        doc_type VARCHAR(50) NOT NULL,
                        title TEXT NOT NULL DEFAULT '',
                        source VARCHAR(255) NOT NULL DEFAULT '',
                        url TEXT NOT NULL DEFAULT '',
                        published_at TIMESTAMP,
                        lang VARCHAR(20) NOT NULL DEFAULT 'zh-CN',
                        raw_text TEXT NOT NULL DEFAULT '',
                        clean_text TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL DEFAULT '',
                        sector_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        industry_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        theme_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        symbol_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        etf_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        doc_key VARCHAR(64) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_qd_rag_documents_doc_key UNIQUE (doc_key)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qd_rag_documents_type_time ON qd_rag_documents(doc_type, published_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qd_rag_documents_market_time ON qd_rag_documents(market, published_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qd_rag_documents_source ON qd_rag_documents(source)"
                )
                cur.execute(
                    "ALTER TABLE qd_rag_documents ADD COLUMN IF NOT EXISTS industry_tags JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE qd_rag_documents ADD COLUMN IF NOT EXISTS theme_tags JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_rag_chunks (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER NOT NULL REFERENCES qd_rag_documents(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        chunk_text TEXT NOT NULL DEFAULT '',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_qd_rag_chunks_doc_idx UNIQUE (document_id, chunk_index)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qd_rag_chunks_document_id ON qd_rag_chunks(document_id)"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_rag_embeddings (
                        id SERIAL PRIMARY KEY,
                        chunk_id INTEGER NOT NULL REFERENCES qd_rag_chunks(id) ON DELETE CASCADE,
                        provider VARCHAR(80) NOT NULL DEFAULT '',
                        model VARCHAR(255) NOT NULL DEFAULT '',
                        dimensions INTEGER NOT NULL DEFAULT 0,
                        vector JSONB NOT NULL DEFAULT '[]'::jsonb,
                        embedding vector,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_qd_rag_embeddings_chunk_model UNIQUE (chunk_id, provider, model)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qd_rag_embeddings_chunk_id ON qd_rag_embeddings(chunk_id)"
                )
                cur.execute(
                    "ALTER TABLE qd_rag_embeddings ADD COLUMN IF NOT EXISTS embedding vector"
                )
                db.commit()
                cur.close()
        except Exception as exc:
            logger.error("Failed to ensure RAG document schema: %s", exc, exc_info=True)
            raise

    def upsert_document(
        self,
        *,
        user_id: Optional[int] = None,
        market: str = "CNStock",
        doc_type: str,
        title: str,
        source: str,
        url: str,
        published_at: Optional[str] = None,
        lang: str = "zh-CN",
        raw_text: str = "",
        clean_text: str = "",
        summary: str = "",
        sector_tags: Optional[List[str]] = None,
        industry_tags: Optional[List[str]] = None,
        theme_tags: Optional[List[str]] = None,
        symbol_tags: Optional[List[str]] = None,
        etf_tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        sector_tags = sector_tags or []
        industry_tags = industry_tags or list(sector_tags)
        theme_tags = theme_tags or []
        symbol_tags = symbol_tags or []
        etf_tags = etf_tags or []
        metadata = metadata or {}

        final_raw_text = _clean_text(raw_text)
        final_clean_text = _clean_text(clean_text or raw_text)
        final_summary = _clean_text(summary)
        doc_key = _build_doc_key(
            doc_type=doc_type,
            source=source,
            url=url,
            title=title,
            published_at=published_at or "",
        )

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_rag_documents (
                    user_id, market, doc_type, title, source, url, published_at,
                    lang, raw_text, clean_text, summary,
                    sector_tags, industry_tags, theme_tags, symbol_tags, etf_tags, metadata, doc_key
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, NULLIF(%s, '')::timestamp,
                    %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s
                )
                ON CONFLICT (doc_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    source = EXCLUDED.source,
                    url = EXCLUDED.url,
                    published_at = COALESCE(EXCLUDED.published_at, qd_rag_documents.published_at),
                    lang = EXCLUDED.lang,
                    raw_text = EXCLUDED.raw_text,
                    clean_text = EXCLUDED.clean_text,
                    summary = EXCLUDED.summary,
                    sector_tags = EXCLUDED.sector_tags,
                    industry_tags = EXCLUDED.industry_tags,
                    theme_tags = EXCLUDED.theme_tags,
                    symbol_tags = EXCLUDED.symbol_tags,
                    etf_tags = EXCLUDED.etf_tags,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    user_id,
                    market,
                    doc_type,
                    title or "",
                    source or "",
                    url or "",
                    published_at or "",
                    lang or "zh-CN",
                    final_raw_text,
                    final_clean_text,
                    final_summary,
                    _json_dump(sector_tags),
                    _json_dump(industry_tags),
                    _json_dump(theme_tags),
                    _json_dump(symbol_tags),
                    _json_dump(etf_tags),
                    _json_dump(metadata),
                    doc_key,
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def replace_chunks(
        self,
        *,
        document_id: int,
        chunks: List[str],
        base_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata = base_metadata or {}
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("DELETE FROM qd_rag_chunks WHERE document_id = %s", (int(document_id),))
            for idx, chunk_text in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO qd_rag_chunks (document_id, chunk_index, chunk_text, metadata)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (
                        int(document_id),
                        idx,
                        _clean_text(chunk_text),
                        _json_dump({**metadata, "chunk_index": idx}),
                    ),
                )
            db.commit()
            cur.close()

    def list_chunks(
        self,
        *,
        document_id: Optional[int] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, document_id, chunk_index, chunk_text, metadata, created_at, updated_at "
            "FROM qd_rag_chunks WHERE 1=1"
        )
        params: List[Any] = []
        if document_id is not None:
            sql += " AND document_id = %s"
            params.append(int(document_id))
        sql += " ORDER BY document_id, chunk_index LIMIT %s"
        params.append(max(1, min(int(limit or 200), 2000)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            out.append(item)
        return out

    def upsert_embedding(
        self,
        *,
        chunk_id: int,
        provider: str,
        model: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        payload = [float(x) for x in (vector or [])]
        dimensions = len(payload)
        metadata = metadata or {}

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_rag_embeddings (
                    chunk_id, provider, model, dimensions, vector, embedding, metadata
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector, %s::jsonb)
                ON CONFLICT (chunk_id, provider, model) DO UPDATE SET
                    dimensions = EXCLUDED.dimensions,
                    vector = EXCLUDED.vector,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    int(chunk_id),
                    provider or "",
                    model or "",
                    int(dimensions),
                    _json_dump(payload),
                    "[" + ",".join(str(x) for x in payload) + "]",
                    _json_dump(metadata),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            if isinstance(row, dict):
                return int(row.get("id"))
            return int(row[0])

    def list_embeddings(
        self,
        *,
        document_id: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT e.id, e.chunk_id, c.document_id, e.provider, e.model, e.dimensions, e.vector, e.embedding::text AS embedding_text, e.metadata, e.created_at, e.updated_at "
            "FROM qd_rag_embeddings e "
            "JOIN qd_rag_chunks c ON c.id = e.chunk_id "
            "WHERE 1=1"
        )
        params: List[Any] = []
        if document_id is not None:
            sql += " AND c.document_id = %s"
            params.append(int(document_id))
        if provider:
            sql += " AND e.provider = %s"
            params.append(provider)
        if model:
            sql += " AND e.model = %s"
            params.append(model)
        sql += " ORDER BY e.id LIMIT %s"
        params.append(max(1, min(int(limit or 200), 5000)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            item["vector"] = _json_list(item.get("vector"))
            emb_text = item.pop("embedding_text", None)
            if emb_text:
                try:
                    item["embedding"] = [float(x) for x in str(emb_text).strip("[]").split(",") if str(x).strip()]
                except Exception:
                    item["embedding"] = []
            else:
                item["embedding"] = []
            out.append(item)
        return out

    def search_similar_chunks(
        self,
        *,
        query_vector: List[float],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        vec_literal = "[" + ",".join(str(float(x)) for x in (query_vector or [])) + "]"
        sql = (
            "SELECT e.id, e.chunk_id, c.document_id, c.chunk_index, c.chunk_text, e.provider, e.model, e.dimensions, "
            "e.embedding::text AS embedding_text, e.metadata, (e.embedding <=> %s::vector) AS distance "
            "FROM qd_rag_embeddings e "
            "JOIN qd_rag_chunks c ON c.id = e.chunk_id "
            "WHERE e.embedding IS NOT NULL"
        )
        params: List[Any] = [vec_literal]
        if provider:
            sql += " AND e.provider = %s"
            params.append(provider)
        if model:
            sql += " AND e.model = %s"
            params.append(model)
        sql += " ORDER BY e.embedding <=> %s::vector LIMIT %s"
        params.append(vec_literal)
        params.append(max(1, min(int(limit or 10), 200)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            emb_text = item.pop("embedding_text", None)
            if emb_text:
                try:
                    item["embedding"] = [float(x) for x in str(emb_text).strip("[]").split(",") if str(x).strip()]
                except Exception:
                    item["embedding"] = []
            else:
                item["embedding"] = []
            out.append(item)
        return out

    def update_document_tags(
        self,
        *,
        document_id: int,
        sector_tags: Optional[List[str]] = None,
        etf_tags: Optional[List[str]] = None,
    ) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_rag_documents
                SET sector_tags = %s::jsonb,
                    etf_tags = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    _json_dump(sector_tags or []),
                    _json_dump(etf_tags or []),
                    int(document_id),
                ),
            )
            db.commit()
            cur.close()

    def list_recent_documents(
        self,
        *,
        doc_type: Optional[str] = None,
        market: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, doc_type, title, source, url, published_at, lang, summary, "
            "sector_tags, industry_tags, theme_tags, symbol_tags, etf_tags, metadata, created_at, updated_at "
            "FROM qd_rag_documents WHERE 1=1"
        )
        params: List[Any] = []
        if doc_type:
            sql += " AND doc_type = %s"
            params.append(doc_type)
        if market:
            sql += " AND market = %s"
            params.append(market)
        sql += " ORDER BY COALESCE(published_at, created_at) DESC LIMIT %s"
        params.append(max(1, min(int(limit or 20), 200)))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            item["metadata"] = _json_dict(item.get("metadata"))
            item["sector_tags"] = _json_list(item.get("sector_tags"))
            item["industry_tags"] = _json_list(item.get("industry_tags"))
            item["theme_tags"] = _json_list(item.get("theme_tags"))
            item["symbol_tags"] = _json_list(item.get("symbol_tags"))
            item["etf_tags"] = _json_list(item.get("etf_tags"))
            out.append(item)
        return out


_rag_document_repository: Optional[RAGDocumentRepository] = None


def get_rag_document_repository() -> RAGDocumentRepository:
    global _rag_document_repository
    if _rag_document_repository is None:
        _rag_document_repository = RAGDocumentRepository()
    return _rag_document_repository
