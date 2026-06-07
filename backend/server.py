"""
Hormozi Brain — private FastAPI web server.

Run:
  uvicorn backend.server:app --reload --host 127.0.0.1 --port 8000

Dev (API + Vite):
  scripts/run_web.bat

MCP (Claude.ai):
  Add https://hormozi-s-transcripts.onrender.com/mcp
  in Claude.ai → Settings → Integrations → Add custom MCP server
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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


# ── Pydantic models (unchanged) ───────────────────────────────

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


# ── Graph helpers (unchanged) ─────────────────────────────────

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


# ════════════════════════════════════════════════════════════════
#  MCP TOOL DEFINITIONS
# ════════════════════════════════════════════════════════════════

DOMAIN_ENUM = sorted(DOMAIN_TYPE_MAP.keys())

MCP_TOOLS = [
    {
        "name": "search_hormozi_brain",
        "description": (
            "Semantic search across Alex Hormozi's extracted knowledge vault. "
            "839 notes built from 211 YouTube videos and his books ($100M Offers, $100M Leads). "
            "Returns relevant chunks with note titles, types, relevance scores, and source videos. "
            "Use this to find specific frameworks, tactics, quotes, or mental models."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in the Hormozi brain vault."
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter.",
                    "enum": DOMAIN_ENUM
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to return (default 8, max 20).",
                    "default": 8
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "ask_hormozi_brain",
        "description": (
            "Ask the Hormozi brain a question and get a full answer in Alex Hormozi's voice. "
            "Grounded in his actual extracted knowledge with citations to exact notes and videos. "
            "Use for business advice, offer construction, pricing, hiring, scaling, mindset coaching."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask Hormozi."
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain to focus the answer.",
                    "enum": DOMAIN_ENUM
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "hormozi_brain_stats",
        "description": (
            "Get stats about the Hormozi brain vault: total notes, chunks, "
            "breakdown by note type and domain."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "read_hormozi_note",
        "description": (
            "Read the full markdown content of a specific Hormozi brain note. "
            "Use paths like '01 Frameworks/Value Equation' or '02 Mental Models/Theory of Constraints'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_path": {
                    "type": "string",
                    "description": "Path to the note relative to vault root."
                }
            },
            "required": ["note_path"]
        }
    },
    {
        "name": "hormozi_graph_summary",
        "description": (
            "Get a summary of the Hormozi knowledge graph: total nodes, edges, "
            "top 10 most connected concepts, and breakdown by node type."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# ════════════════════════════════════════════════════════════════
#  MCP TOOL EXECUTORS
# ════════════════════════════════════════════════════════════════

def _mcp_search(args: dict) -> str:
    chunks = get_brain().search(
        args["query"],
        domain=args.get("domain"),
        top_k=args.get("top_k", 8)
    )
    if not chunks:
        return "No relevant chunks found for that query."
    lines = [f"SEARCH RESULTS for: '{args['query']}'\n"]
    for i, chunk in enumerate(chunks, 1):
        videos = chunk.get("source_videos", [])
        lines.append(
            f"[{i}] {chunk.get('note_title','?')} ({chunk.get('note_type','?')}) "
            f"— relevance: {chunk.get('relevance','?')}"
        )
        lines.append(f"     Source: {', '.join(videos) if videos else 'Unknown'}")
        text = chunk.get("text", chunk.get("content", ""))
        lines.append(f"     {text[:400]}{'...' if len(text) > 400 else ''}\n")
    return "\n".join(lines)


def _mcp_ask(args: dict) -> str:
    result = get_brain().ask(
        args["question"],
        domain=args.get("domain"),
        history=[],
        top_k=8,
    )
    answer  = result.get("answer", result.get("response", "No answer returned."))
    sources = result.get("chunks", [])
    lines   = [answer, "\n---", "📎 CITATIONS:"]
    for i, src in enumerate(sources, 1):
        videos = src.get("source_videos", [])
        lines.append(
            f"  [{i}] {src.get('note_title','?')} ({src.get('note_type','?')}) "
            f"— {src.get('relevance','?')} — from: {', '.join(videos) if videos else 'Unknown'}"
        )
    return "\n".join(lines)


def _mcp_stats() -> str:
    data   = get_brain().stats()
    lines  = ["HORMOZI BRAIN — VAULT STATS\n"]
    lines.append(f"  Notes  : {data.get('total_notes', data.get('notes','?'))}")
    lines.append(f"  Chunks : {data.get('total_chunks', data.get('chunks','?'))}")
    by_type = data.get("by_type", data.get("note_types", {}))
    if by_type:
        lines.append("\n  By type:")
        for k, v in by_type.items():
            lines.append(f"    {k:<20} {v}")
    by_domain = data.get("by_domain", data.get("domains", {}))
    if by_domain:
        lines.append("\n  By domain:")
        for k, v in by_domain.items():
            lines.append(f"    #{k:<18} {v}")
    return "\n".join(lines)


def _mcp_read_note(args: dict) -> str:
    note_path = args.get("note_path", "")
    safe      = normalize_key(note_path.strip())
    if ".." in safe or safe.startswith("/"):
        return "Invalid path."
    vault      = Path(VAULT_DIR).resolve()
    full_path  = (vault / safe).resolve()
    if not str(full_path).startswith(str(vault)):
        return "Invalid path."
    # Try with and without .md extension
    for candidate in [full_path, Path(str(full_path) + ".md")]:
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8")
            return f"# {candidate.stem}\n\n{content}"
    return f"Note not found: '{note_path}'"


def _mcp_graph_summary() -> str:
    graph  = get_full_graph()
    nodes  = graph.get("nodes", [])
    edges  = graph.get("edges", [])
    lines  = [
        "HORMOZI BRAIN — KNOWLEDGE GRAPH SUMMARY\n",
        f"  Total nodes : {len(nodes)}",
        f"  Total edges : {len(edges)}",
    ]
    # Connection counts
    counts: dict[str, int] = {n.get("id", n.get("name", "")): 0 for n in nodes}
    for edge in edges:
        for key in ("from", "source"):
            if edge.get(key) in counts:
                counts[edge[key]] += 1
        for key in ("to", "target"):
            if edge.get(key) in counts:
                counts[edge[key]] += 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    lines.append("\n  Top 10 most connected nodes:")
    for name, cnt in top:
        lines.append(f"    {name[:50]:<50} {cnt} links")
    # Type breakdown
    type_counts: dict[str, int] = {}
    for node in nodes:
        t = node.get("type", node.get("group", "unknown"))
        type_counts[t] = type_counts.get(t, 0) + 1
    lines.append("\n  By node type:")
    for t, cnt in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"    {t:<20} {cnt}")
    return "\n".join(lines)


def execute_mcp_tool(name: str, args: dict) -> str:
    """Route a tool call to the right executor."""
    if name == "search_hormozi_brain":
        return _mcp_search(args)
    if name == "ask_hormozi_brain":
        return _mcp_ask(args)
    if name == "hormozi_brain_stats":
        return _mcp_stats()
    if name == "read_hormozi_note":
        return _mcp_read_note(args)
    if name == "hormozi_graph_summary":
        return _mcp_graph_summary()
    raise ValueError(f"Unknown tool: {name}")


# ════════════════════════════════════════════════════════════════
#  MCP SSE HELPERS
# ════════════════════════════════════════════════════════════════

def _sse(event: str, data: Any) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


# ════════════════════════════════════════════════════════════════
#  APP SETUP  (unchanged from original)
# ════════════════════════════════════════════════════════════════

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
    raw = os.getenv("CORS_ORIGIN_REGEX",
                    r"https://.*\.vercel\.app").strip()
    return raw or None


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════
#  EXISTING API ROUTES  (all unchanged)
# ════════════════════════════════════════════════════════════════

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
    base   = get_full_graph()
    merged = apply_retrieval_highlights(
        base, body.chunks, body.question, body.session_hits
    )
    return graph_for_api(merged)


@app.post("/api/search", dependencies=[Depends(require_auth)])
def search(body: SearchRequest) -> dict:
    try:
        chunks = get_brain().search(body.query, domain=body.domain, top_k=body.top_k)
        base   = get_full_graph()
        graph  = apply_retrieval_highlights(base, chunks, body.query)
        return {
            "chunks": chunks,
            "query":  body.query,
            "domain": body.domain,
            "graph":  graph_for_api(graph),
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
        base          = get_full_graph()
        graph         = apply_retrieval_highlights(
            base, result["chunks"], result["question"]
        )
        result["graph"] = graph_for_api(graph)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/note", dependencies=[Depends(require_auth)])
def read_note(
    path: str = Query(..., description="Vault-relative path to .md file")
) -> dict:
    safe = normalize_key(path.strip())
    if ".." in safe or safe.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    vault      = Path(VAULT_DIR).resolve()
    note_path  = (vault / safe).resolve()
    if not str(note_path).startswith(str(vault)) or not note_path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "path":    safe,
        "title":   note_path.stem,
        "content": note_path.read_text(encoding="utf-8"),
    }


@app.post("/api/graph/refresh", dependencies=[Depends(require_auth)])
def refresh_graph_cache() -> dict:
    global _full_graph_cache
    _full_graph_cache = None
    g = get_full_graph()
    return {"refreshed": True, "nodes": g["stats"]["total_nodes"]}


# ════════════════════════════════════════════════════════════════
#  MCP ENDPOINT  (new)
# ════════════════════════════════════════════════════════════════

@app.get("/mcp")
async def mcp_sse(request: Request) -> StreamingResponse:
    """
    MCP SSE endpoint for Claude.ai integration.
    Claude.ai connects here via GET and receives:
      1. An 'endpoint' event pointing to POST /mcp
      2. Stays open for server-initiated messages (not used here)

    Add this URL in Claude.ai → Settings → Integrations:
      https://hormozi-s-transcripts.onrender.com/mcp
    """
    async def event_stream():
        # Tell Claude where to POST tool calls
        post_url = str(request.base_url).rstrip("/") + "/mcp"
        yield _sse("endpoint", post_url)
        # Keep connection alive
        while True:
            if await request.is_disconnected():
                break
            yield ": keep-alive\n\n"
            import asyncio
            await asyncio.sleep(15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/mcp")
async def mcp_post(request: Request) -> dict:
    """
    MCP JSON-RPC handler.
    Claude.ai POSTs tool calls here after connecting via GET /mcp.
    No auth required — tools only read your vault, never write.
    """
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error")

    method  = body.get("method", "")
    req_id  = body.get("id")
    params  = body.get("params", {})

    # ── Handshake ─────────────────────────────────────────────
    if method == "initialize":
        return _jsonrpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "hormozi-brain", "version": "1.0.0"},
        })

    if method in ("notifications/initialized", "ping"):
        return _jsonrpc_result(req_id, {})

    # ── Tool list ─────────────────────────────────────────────
    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": MCP_TOOLS})

    # ── Tool call ─────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            output = execute_mcp_tool(tool_name, arguments)
            return _jsonrpc_result(req_id, {
                "content":  [{"type": "text", "text": output}],
                "isError":  False,
            })
        except ValueError as exc:
            return _jsonrpc_error(req_id, -32601, str(exc))
        except Exception as exc:
            return _jsonrpc_result(req_id, {
                "content":  [{"type": "text", "text": f"Tool error: {exc}"}],
                "isError":  True,
            })

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


# ════════════════════════════════════════════════════════════════
#  SPA STATIC SERVING  (unchanged)
# ════════════════════════════════════════════════════════════════

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