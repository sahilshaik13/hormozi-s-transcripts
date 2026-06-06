"""Project root and data paths — single source of truth."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VAULT_DIR = PROJECT_ROOT / "hormozi-brain"
INDEX_DIR = PROJECT_ROOT / "hormozi-index"
TRANSCRIPTS_DIR = PROJECT_ROOT / "transcripts"
CACHE_DIR = PROJECT_ROOT / ".brain_cache"
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
