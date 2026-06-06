"""
Hormozi Brain — private FastAPI web server.

Run:
  uvicorn backend.server:app --reload --host 127.0.0.1 --port 8000

Dev (API + Vite):
  scripts/run_web.bat
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import load_env
from backend.core import DOMAIN_TYPE_MAP, get_brain
from backend.paths import VAULT_DIR, WEB_DIST
from backend.runtime import is_vercel
from backend.viz import (
    TYPE_COLORS,
    apply_retrieval_highlights,
    build_full_vault_graph,
    normalize_key,
)

load_env()

WEB_TOKEN = os.getenv("HORMOZI_WEB_TOKEN", "").strip()
_bearer = HTTPBearer(auto_error=False)

_full_graph_cache: dict | None = None


def require_auth(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    if not WEB_TOKEN:
        return
    if creds is None or creds.credentials != WEB_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


class SearchRequest(BaseModel):
    query: str
    domain: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class AskRequest(BaseModel):
    question: str
    domain: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    history: list[dict[str, str]] = Field(default_factory=list)


class GraphHighlightRequest(BaseModel):
    chunks: list[dict[str, Any]]
    question: str = ""
    session_hits: dict[str, int] = Field(default_factory=dict)


def get_full_graph() -> dict:
    global _full_graph_cache
    if _full_graph_cache is None:
        vault = Path(VAULT_DIR)
        if not vault.exists():
            raise HTTPException(status_code=500, detail="Vault directory not found")
        _full_graph_cache = build_full_vault_graph(vault)
    return _full_graph_cache


def graph_for_api(graph: dict) -> dict:
    """react-force-graph expects `links` not `edges`."""
    return {
        "nodes": graph["nodes"],
        "links": [
            {
                "source": e["from"],
                "target": e["to"],
                "type": e.get("type", "wikilink"),
                "label": e.get("label", ""),
            }
            for e in graph.get("edges", [])
        ],
        "stats": graph.get("stats", {}),
        "typeColors": TYPE_COLORS,
    }


app = FastAPI(
    title="Hormozi Brain",
    description="Private RAG web API for the Hormozi knowledge vault",
    version="1.0.0",
)

def _cors_origins() -> list[str]:
    defaults = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    extra = os.getenv("CORS_ORIGINS", "").strip()
    if not extra:
        return defaults
    return defaults + [o.strip() for o in extra.split(",") if o.strip()]


def _cors_origin_regex() -> str | None:
    raw = os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app").strip()
    return raw or None


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats", dependencies=[Depends(require_auth)])
def stats() -> dict:
    try:
        return get_brain().stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/domains", dependencies=[Depends(require_auth)])
def domains() -> dict:
    return {"domains": sorted(DOMAIN_TYPE_MAP.keys())}


@app.get("/api/graph", dependencies=[Depends(require_auth)])
def full_graph() -> dict:
    return graph_for_api(get_full_graph())


@app.post("/api/graph/highlight", dependencies=[Depends(require_auth)])
def highlight_graph(body: GraphHighlightRequest) -> dict:
    base = get_full_graph()
    merged = apply_retrieval_highlights(
        base, body.chunks, body.question, body.session_hits
    )
    return graph_for_api(merged)


@app.post("/api/search", dependencies=[Depends(require_auth)])
def search(body: SearchRequest) -> dict:
    try:
        chunks = get_brain().search(body.query, domain=body.domain, top_k=body.top_k)
        base = get_full_graph()
        graph = apply_retrieval_highlights(base, chunks, body.query)
        return {
            "chunks": chunks,
            "query": body.query,
            "domain": body.domain,
            "graph": graph_for_api(graph),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/ask", dependencies=[Depends(require_auth)])
def ask(body: AskRequest) -> dict:
    try:
        result = get_brain().ask(
            body.question,
            domain=body.domain,
            history=body.history,
            top_k=body.top_k,
        )
        base = get_full_graph()
        graph = apply_retrieval_highlights(
            base, result["chunks"], result["question"]
        )
        result["graph"] = graph_for_api(graph)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/note", dependencies=[Depends(require_auth)])
def read_note(path: str = Query(..., description="Vault-relative path to .md file")) -> dict:
    safe = normalize_key(path.strip())
    if ".." in safe or safe.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    vault = Path(VAULT_DIR).resolve()
    note_path = (vault / safe).resolve()
    if not str(note_path).startswith(str(vault)) or not note_path.exists():
        raise HTTPException(status_code=404, detail="Note not found")

    return {
        "path": safe,
        "title": note_path.stem,
        "content": note_path.read_text(encoding="utf-8"),
    }


@app.post("/api/graph/refresh", dependencies=[Depends(require_auth)])
def refresh_graph_cache() -> dict:
    global _full_graph_cache
    _full_graph_cache = None
    g = get_full_graph()
    return {"refreshed": True, "nodes": g["stats"]["total_nodes"]}


if WEB_DIST.exists() and not is_vercel():
    assets_dir = WEB_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
