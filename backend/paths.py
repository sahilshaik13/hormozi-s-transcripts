"""Project root and data paths — single source of truth."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else default


def _vault_dir() -> Path:
    return _path_from_env("HORMOZI_VAULT_DIR", PROJECT_ROOT / "hormozi-brain")


def _index_dir() -> Path:
    return _path_from_env("HORMOZI_INDEX_DIR", PROJECT_ROOT / "hormozi-index")


VAULT_DIR = _vault_dir()
INDEX_DIR = _index_dir()
TRANSCRIPTS_DIR = _path_from_env("HORMOZI_TRANSCRIPTS_DIR", PROJECT_ROOT / "transcripts")
CACHE_DIR = _path_from_env("HORMOZI_CACHE_DIR", PROJECT_ROOT / ".brain_cache")
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
