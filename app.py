"""Vercel FastAPI entrypoint (auto-detected; do not use api/ + functions config)."""

from backend.server import app

__all__ = ["app"]
