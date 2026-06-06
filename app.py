"""Vercel entrypoint — FastAPI backend on the same deployment as the web UI."""

from backend.server import app

__all__ = ["app"]
