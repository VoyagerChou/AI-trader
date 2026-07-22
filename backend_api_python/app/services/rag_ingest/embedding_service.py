"""Embedding service for first-stage RAG vectorization.

This service upgrades normalized RAG documents into chunked + embedded content.
It stores vectors in PostgreSQL JSONB first, keeping the design compatible with
future pgvector migration.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from app.config import APIKeys
from app.services.rag_ingest.rag_document_repository import get_rag_document_repository
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _clean_text(text: Any) -> str:
    return str(text or "").replace("\r", "\n").strip()


def _normalize_whitespace(text: str) -> str:
    import re

    value = _clean_text(text)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    value = _normalize_whitespace(text)
    if not value:
        return []
    if len(value) <= chunk_size:
        return [value]

    chunks: List[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(value):
        end = min(len(value), start + chunk_size)
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(value):
            break
        start += step
    return chunks


class EmbeddingService:
    """Chunk and embed stored RAG documents."""

    DEFAULT_PROVIDER = "openai-compatible"
    DEFAULT_MODEL = "text-embedding-3-small"
    LOCAL_PROVIDER = "local-sentence-transformers"
    LOCAL_MODEL_NAME = "BAAI/bge-m3"
    TIMEOUT = 45

    def __init__(self) -> None:
        self.repo = get_rag_document_repository()
        self._local_model = None

    def _local_model_path(self) -> str:
        value = (os.getenv("LOCAL_EMBEDDING_MODEL_PATH") or "").strip()
        if value:
            return value
        return r"D:\Models\bge-m3"

    def _load_local_model(self):
        if self._local_model is not None:
            return self._local_model
        os.environ.setdefault("USE_TF", "0")
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self._local_model_path(), trust_remote_code=True)
        self._local_model = model
        return model

    def _embedding_credentials(self) -> tuple[str, str, str]:
        openai_key = (APIKeys.OPENAI_API_KEY or "").strip()
        if openai_key:
            return ("https://api.openai.com/v1", openai_key, self.DEFAULT_MODEL)

        custom_key = (APIKeys.CUSTOM_API_KEY or "").strip()
        custom_url = (APIKeys.CUSTOM_API_URL or "").strip()
        custom_model = (APIKeys.CUSTOM_MODEL or "").strip() or self.DEFAULT_MODEL
        if custom_key and custom_url:
            return (custom_url.rstrip("/"), custom_key, custom_model)

        atlas_key = (APIKeys.ATLASCLOUD_API_KEY or "").strip()
        if atlas_key:
            return ("https://api.atlascloud.ai/v1", atlas_key, self.DEFAULT_MODEL)

        openrouter_key = (APIKeys.OPENROUTER_API_KEY or "").strip()
        if openrouter_key:
            return ("https://openrouter.ai/api/v1", openrouter_key, self.DEFAULT_MODEL)

        raise RuntimeError(
            "No embedding-capable provider configured. Set OPENAI_API_KEY or CUSTOM_API_URL + CUSTOM_API_KEY."
        )

    def _request_embedding(self, *, text: str) -> tuple[str, str, List[float]]:
        base_url, api_key, model = self._embedding_credentials()
        url = f"{base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": text,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError("Embedding API returned empty data")
        vector = rows[0].get("embedding") or []
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Embedding API returned invalid vector")
        return (self.DEFAULT_PROVIDER, model, [float(x) for x in vector])

    def _local_embedding(self, *, text: str) -> tuple[str, str, List[float]]:
        model = self._load_local_model()
        vector = model.encode([text], normalize_embeddings=True)
        row = vector[0].tolist() if hasattr(vector[0], "tolist") else list(vector[0])
        return (self.LOCAL_PROVIDER, self.LOCAL_MODEL_NAME, [float(x) for x in row])

    def get_embedding(self, *, text: str) -> tuple[str, str, List[float]]:
        try:
            return self._local_embedding(text=text)
        except Exception as local_exc:
            logger.warning("Local embedding unavailable, falling back to API provider: %s", local_exc, exc_info=True)
        return self._request_embedding(text=text)

    def chunk_document(
        self,
        *,
        document_id: int,
        chunk_size: int = 800,
        overlap: int = 120,
    ) -> Dict[str, Any]:
        docs = self.repo.list_recent_documents(limit=500)
        target = next((doc for doc in docs if int(doc.get("id") or 0) == int(document_id)), None)
        if not target:
            raise ValueError(f"Document not found: {document_id}")

        text = target.get("clean_text") or target.get("raw_text") or target.get("summary") or ""
        chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        self.repo.replace_chunks(
            document_id=document_id,
            chunks=chunks,
            base_metadata={
                "doc_type": target.get("doc_type"),
                "source": target.get("source"),
            },
        )
        return {
            "document_id": int(document_id),
            "chunk_count": len(chunks),
            "chunk_size": chunk_size,
            "overlap": overlap,
        }

    def embed_document(
        self,
        *,
        document_id: int,
        chunk_size: int = 800,
        overlap: int = 120,
    ) -> Dict[str, Any]:
        chunk_info = self.chunk_document(document_id=document_id, chunk_size=chunk_size, overlap=overlap)
        chunks = self.repo.list_chunks(document_id=document_id, limit=5000)
        embedded = 0
        model_used = ""
        provider_used = ""
        for chunk in chunks:
            text = _clean_text(chunk.get("chunk_text"))
            if not text:
                continue
            provider_used, model_used, vector = self.get_embedding(text=text)
            self.repo.upsert_embedding(
                chunk_id=int(chunk.get("id")),
                provider=provider_used,
                model=model_used,
                vector=vector,
                metadata={
                    "document_id": int(document_id),
                    "chunk_index": chunk.get("chunk_index"),
                },
            )
            embedded += 1
        return {
            "document_id": int(document_id),
            "chunk_count": int(chunk_info.get("chunk_count") or 0),
            "embedded_count": embedded,
            "provider": provider_used,
            "model": model_used,
        }


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
