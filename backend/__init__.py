"""Hormozi Brain backend — RAG engine, API, MCP, graph viz."""

from backend.core import get_brain
from backend.paths import INDEX_DIR, PROJECT_ROOT, VAULT_DIR

__all__ = ["get_brain", "PROJECT_ROOT", "VAULT_DIR", "INDEX_DIR"]
