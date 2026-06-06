"""Serverless runtime helpers (Vercel / AWS Lambda-style environments)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.paths import PROJECT_ROOT


def is_vercel() -> bool:
    return os.getenv("VERCEL") == "1"


def bundled_index_dir() -> Path:
    raw = os.getenv("HORMOZI_INDEX_DIR", "").strip()
    if raw:
        return Path(raw)
    return PROJECT_ROOT / "hormozi-index"


def bundled_vault_dir() -> Path:
    raw = os.getenv("HORMOZI_VAULT_DIR", "").strip()
    if raw:
        return Path(raw)
    return PROJECT_ROOT / "hormozi-brain"


def get_writable_index_dir() -> Path:
    """
    ChromaDB needs a writable directory. On Vercel only /tmp is writable,
    so copy the bundled index there once per function instance.
    """
    bundled = bundled_index_dir()
    if not is_vercel():
        return bundled

    tmp = Path("/tmp/hormozi-index")
    ready = tmp / ".vercel-ready"
    if ready.exists():
        return tmp

    if not bundled.exists():
        return bundled

    if tmp.exists():
        shutil.rmtree(tmp)

    shutil.copytree(bundled, tmp)
    ready.touch()
    return tmp
