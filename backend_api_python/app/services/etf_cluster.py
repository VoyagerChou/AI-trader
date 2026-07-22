"""ETF cluster loader — reads pre-computed hierarchical clustering results.

Loads etf_clusters_runtime.json (exported from JoinQuant clustering scripts)
and provides cluster_id lookup for ETF correlation deduplication in the
weekly pipeline.

Format: cluster file maps ETF codes (JoinQuant: 512480.XSHG) to final cluster IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default cluster file (overridable via env CLUSTER_FILE)
_DEFAULT_CLUSTER_FILE = Path(r"D:\Quant\ETFcluster\etf_clusters_runtime.json")


class ETFClusterService:
    """Load and query pre-computed ETF clusters."""

    def __init__(self, cluster_file: Optional[str] = None) -> None:
        import os

        path = cluster_file or os.getenv("ETF_CLUSTER_FILE", str(_DEFAULT_CLUSTER_FILE))
        self._cluster_path = Path(path)
        self._code_to_cluster: Dict[str, str] = {}
        self._cluster_to_codes: Dict[str, List[str]] = {}
        self._loaded = False
        self._asof_date: Optional[str] = None
        self._n_clusters: int = 0
        self._n_etfs: int = 0

    # ── public API ──────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def asof_date(self) -> Optional[str]:
        return self._asof_date

    @property
    def n_clusters(self) -> int:
        return self._n_clusters

    @property
    def n_etfs(self) -> int:
        return self._n_etfs

    def load(self) -> bool:
        """Load cluster mappings from JSON. Returns True on success."""
        if not self._cluster_path.exists():
            logger.warning("Cluster file not found: %s", self._cluster_path)
            return False

        try:
            data = json.loads(self._cluster_path.read_text(encoding="utf-8"))
            raw_map: Dict[str, str] = data.get("etf_to_final_cluster", {})
            if not raw_map:
                raw_map = data.get("final_clusters", {})

            # Convert JoinQuant codes (512480.XSHG) → plain codes (512480)
            self._code_to_cluster = {}
            for code, cluster_id in raw_map.items():
                plain = _extract_code(code)
                if plain:
                    self._code_to_cluster[plain] = str(cluster_id)

            # Build reverse map
            self._cluster_to_codes = {}
            for code, cid in self._code_to_cluster.items():
                self._cluster_to_codes.setdefault(cid, []).append(code)

            self._asof_date = data.get("cluster_asof_date")
            self._n_clusters = len(self._cluster_to_codes)
            self._n_etfs = len(self._code_to_cluster)
            self._loaded = True

            logger.info(
                "ETF clusters loaded: %d ETFs → %d clusters (asof %s)",
                self._n_etfs, self._n_clusters, self._asof_date,
            )
            return True

        except Exception as exc:
            logger.error("Failed to load cluster file: %s", exc)
            self._loaded = False
            return False

    def get_cluster(self, etf_code: str) -> Optional[str]:
        """Get cluster ID for an ETF code, or None if not in clusters."""
        if not self._loaded:
            self.load()
        return self._code_to_cluster.get(etf_code)

    def get_peers(self, etf_code: str) -> List[str]:
        """Get all ETF codes in the same cluster (excluding the given code)."""
        if not self._loaded:
            self.load()
        cid = self._code_to_cluster.get(etf_code)
        if cid is None:
            return []
        return [c for c in self._cluster_to_codes.get(cid, []) if c != etf_code]


def _extract_code(joinquant_code: str) -> str:
    """Convert '512480.XSHG' → '512480', '159995.XSHE' → '159995'."""
    code = (joinquant_code or "").strip().upper()
    for suffix in (".XSHG", ".XSHE", ".SS", ".SZ"):
        if code.endswith(suffix):
            return code[: -len(suffix)]
    # Already plain (6 digits)
    if code.isdigit() and len(code) == 6:
        return code
    return ""


# ── singleton ──────────────────────────────────────────────────

_cluster_service: Optional[ETFClusterService] = None


def get_etf_cluster_service() -> ETFClusterService:
    global _cluster_service
    if _cluster_service is None:
        _cluster_service = ETFClusterService()
        _cluster_service.load()
    return _cluster_service
