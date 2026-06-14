"""Hormozi Brain backend — RAG engine, API, MCP, graph viz."""

from backend.paths import INDEX_DIR, PROJECT_ROOT, VAULT_DIR

__all__ = ["get_brain", "PROJECT_ROOT", "VAULT_DIR", "INDEX_DIR"]


def get_brain():
    from backend.core import get_brain as _get_brain

    return _get_brain()
