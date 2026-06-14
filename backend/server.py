"""
Hormozi Brain — private FastAPI web server.

Run:
  uvicorn backend.server:app --reload --host 127.0.0.1 --port 8000

Dev (API + Vite):
  scripts/run_web.bat

MCP (Claude.ai):
  Add https://hormozi-s-transcripts.onrender.com/mcp
  in Claude.ai → Settings → Integrations → Add custom MCP server

Cofounder API:
  GET  /api/cofounder/briefing   → morning audit
  POST /api/cofounder/ask        → ask cofounder a question
  POST /api/cofounder/log        → log a decision
  POST /api/cofounder/update     → update startup context
  GET  /api/cofounder/context    → read current startup state
  GET  /api/cofounder/decisions  → read decision log

ENV VARS REQUIRED:
  OLLAMA_API_KEY        → Ollama Cloud API key (chat + cofounder)
  OLLAMA_CHAT_MODEL     → optional chat model (default: glm-4.7:cloud, free tier)
  EMBED_BACKEND         → fastembed (default) or ollama for local embed API
  FASTEMBED_MODEL       → optional FastEmbed model (default: BAAI/bge-small-en-v1.5)
  HORMOZI_WEB_TOKEN     → optional auth token
  CORS_ORIGINS          → optional extra CORS origins (comma separated)
  CORS_ORIGIN_REGEX     → optional regex for CORS (default: vercel.app)
  HORMOZI_BACKEND_URL   → override backend URL (optional)
"""

from __future__ import annotations

import asyncio
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
from backend.health import collect_health, format_brain_stats, format_health_report
from backend.paths import VAULT_DIR, WEB_DIST
from backend.runtime import is_vercel
from backend.viz import (
    TYPE_COLORS,
    apply_retrieval_highlights,
    build_full_vault_graph,
    normalize_key,
)
from cofounder.cofounder import (
    ask_cofounder,
    daily_briefing,
    get_context,
    get_decisions,
    log_decision,
    update_context,
)

load_env()

WEB_TOKEN = os.getenv("HORMOZI_WEB_TOKEN", "").strip()
_bearer   = HTTPBearer(auto_error=False)

_full_graph_cache: dict | None = None


def require_auth(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    if not WEB_TOKEN:
        return
    if creds is None or creds.credentials != WEB_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


# ════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ════════════════════════════════════════════════════════════════

class SearchRequest(BaseModel):
    query:  str
    domain: str | None = None
    top_k:  int = Field(default=8, ge=1, le=20)


class AskRequest(BaseModel):
    question: str
    domain:   str | None = None
    top_k:    int = Field(default=8, ge=1, le=20)
    history:  list[dict[str, str]] = Field(default_factory=list)


class GraphHighlightRequest(BaseModel):
    chunks:       list[dict[str, Any]]
    question:     str = ""
    session_hits: dict[str, int] = Field(default_factory=dict)


# ── Cofounder models ──────────────────────────────────────────

class CofoundAskRequest(BaseModel):
    question: str
    domain:   str | None = None


class CofoundLogRequest(BaseModel):
    question:               str
    options_considered:     list[str]
    hormozi_recommendation: str
    decision_made:          str
    category:               str = "strategy"
    outcome:                str | None = None
    follow_up:              str | None = None


class CofoundUpdateRequest(BaseModel):
    field_path: str
    value:      Any


# ════════════════════════════════════════════════════════════════
#  GRAPH HELPERS
# ════════════════════════════════════════════════════════════════

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
                "type":   e.get("type", "wikilink"),
                "label":  e.get("label", ""),
            }
            for e in graph.get("edges", [])
        ],
        "stats":      graph.get("stats", {}),
        "typeColors": TYPE_COLORS,
    }


# ════════════════════════════════════════════════════════════════
#  MCP TOOL DEFINITIONS
# ════════════════════════════════════════════════════════════════

DOMAIN_ENUM = sorted(DOMAIN_TYPE_MAP.keys())

MCP_TOOLS = [
    # ── Brain tools ───────────────────────────────────────────
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
        "name": "hormozi_health",
        "description": (
            "Ping brain + embeddings + Ollama AI in one call. "
            "Use to verify the vault index, search embeddings, and chat model are all working."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_ai": {
                    "type": "boolean",
                    "description": "Send a tiny test prompt to Ollama Cloud (default true).",
                    "default": True,
                }
            },
            "required": [],
        },
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
            "Use paths like '01 Frameworks/Value Equation' or "
            "'02 Mental Models/Theory of Constraints'."
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
    },

    # ── Cofounder tools ───────────────────────────────────────
    {
        "name": "ask_cofounder",
        "description": (
            "Ask Hormozi a question as your AI business cofounder. "
            "He knows your startup context, stage, goals, constraints, "
            "and every decision made so far. Answers are grounded in his "
            "extracted knowledge vault with citations. Always ends with "
            "one specific action to take today. Use for strategy, offers, "
            "pricing, hiring, sales, mindset, and any business decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Your question for your cofounder Hormozi."
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter.",
                    "enum": DOMAIN_ENUM
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "cofounder_daily_briefing",
        "description": (
            "Get Hormozi's daily cofounder audit. No question needed. "
            "He reviews your startup state and tells you: what to do today, "
            "what risk you're ignoring, whether your strategy is on track, "
            "and what decision has been delayed too long. Run this every morning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "cofounder_log_decision",
        "description": (
            "Log a major startup decision to the permanent decision log. "
            "Hormozi will reference past decisions in future answers. "
            "Use whenever a major decision is made: strategy pivots, "
            "pricing changes, hiring decisions, market selection, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The decision that needed to be made."
                },
                "options_considered": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of options that were on the table."
                },
                "hormozi_recommendation": {
                    "type": "string",
                    "description": "What Hormozi recommended."
                },
                "decision_made": {
                    "type": "string",
                    "description": "What was actually decided."
                },
                "category": {
                    "type": "string",
                    "description": "Decision category.",
                    "enum": ["strategy", "product", "market", "hiring", "finance"]
                },
                "outcome": {
                    "type": "string",
                    "description": "Result of the decision (fill in later)."
                },
                "follow_up": {
                    "type": "string",
                    "description": "Next action required from this decision."
                }
            },
            "required": [
                "question", "options_considered",
                "hormozi_recommendation", "decision_made"
            ]
        }
    },
    {
        "name": "cofounder_update_context",
        "description": (
            "Update your startup context so Hormozi stays current. "
            "Use dot-notation field paths. Examples: "
            "'startup.name', 'startup.revenue', 'startup.target_industries', "
            "'goals.current_focus', 'strategy.current_blockers'. "
            "Call this whenever something meaningful changes in your startup."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_path": {
                    "type": "string",
                    "description": (
                        "Dot-notation path e.g. 'startup.name' "
                        "or 'goals.current_focus'"
                    )
                },
                "value": {
                    "description": "New value (string, number, or array)."
                }
            },
            "required": ["field_path", "value"]
        }
    },
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
    result  = get_brain().ask(
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
            f"— {src.get('relevance','?')} "
            f"— from: {', '.join(videos) if videos else 'Unknown'}"
        )
    return "\n".join(lines)


def _mcp_stats() -> str:
    return format_brain_stats(get_brain().stats())


def _mcp_health(args: dict) -> str:
    report = collect_health(probe_ai=args.get("probe_ai", True))
    return format_health_report(report)


def _mcp_read_note(args: dict) -> str:
    note_path = args.get("note_path", "")
    safe      = normalize_key(note_path.strip())
    if ".." in safe or safe.startswith("/"):
        return "Invalid path."
    vault     = Path(VAULT_DIR).resolve()
    full_path = (vault / safe).resolve()
    if not str(full_path).startswith(str(vault)):
        return "Invalid path."
    for candidate in [full_path, Path(str(full_path) + ".md")]:
        if candidate.exists():
            return f"# {candidate.stem}\n\n{candidate.read_text(encoding='utf-8')}"
    return f"Note not found: '{note_path}'"


def _mcp_graph_summary() -> str:
    graph = get_full_graph()
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    lines = [
        "HORMOZI BRAIN — KNOWLEDGE GRAPH SUMMARY\n",
        f"  Total nodes : {len(nodes)}",
        f"  Total edges : {len(edges)}",
    ]
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
    type_counts: dict[str, int] = {}
    for node in nodes:
        t = node.get("type", node.get("group", "unknown"))
        type_counts[t] = type_counts.get(t, 0) + 1
    lines.append("\n  By node type:")
    for t, cnt in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"    {t:<20} {cnt}")
    return "\n".join(lines)


def _mcp_ask_cofounder(args: dict) -> str:
    result = ask_cofounder(args["question"], domain=args.get("domain"))
    return result.get("answer", "No answer returned.")


def _mcp_cofounder_briefing() -> str:
    result = daily_briefing()
    return f"📋 DAILY BRIEFING — {result['date']}\n\n{result['briefing']}"


def _mcp_cofounder_log(args: dict) -> str:
    result = log_decision(
        question=args["question"],
        options_considered=args.get("options_considered", []),
        hormozi_recommendation=args.get("hormozi_recommendation", ""),
        decision_made=args.get("decision_made", ""),
        category=args.get("category", "strategy"),
        outcome=args.get("outcome"),
        follow_up=args.get("follow_up"),
    )
    return f"✓ Decision #{result['decision_id']} logged to decision_log.json"


def _mcp_cofounder_update(args: dict) -> str:
    result = update_context(args["field_path"], args["value"])
    return f"✓ Updated {result['field']} = {result['value']}"


def execute_mcp_tool(name: str, args: dict) -> str:
    """Route a tool call to the right executor."""
    # Brain tools
    if name == "hormozi_health":          return _mcp_health(args)
    if name == "search_hormozi_brain":    return _mcp_search(args)
    if name == "ask_hormozi_brain":       return _mcp_ask(args)
    if name == "hormozi_brain_stats":     return _mcp_stats()
    if name == "read_hormozi_note":       return _mcp_read_note(args)
    if name == "hormozi_graph_summary":   return _mcp_graph_summary()
    # Cofounder tools
    if name == "ask_cofounder":           return _mcp_ask_cofounder(args)
    if name == "cofounder_daily_briefing":return _mcp_cofounder_briefing()
    if name == "cofounder_log_decision":  return _mcp_cofounder_log(args)
    if name == "cofounder_update_context":return _mcp_cofounder_update(args)
    raise ValueError(f"Unknown tool: {name}")


# ════════════════════════════════════════════════════════════════
#  MCP SSE HELPERS
# ════════════════════════════════════════════════════════════════

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


# ════════════════════════════════════════════════════════════════
#  APP SETUP
# ════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Hormozi Brain",
    description="Private RAG web API + AI Cofounder for the Hormozi knowledge vault",
    version="2.0.0",
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


# ════════════════════════════════════════════════════════════════
#  EXISTING API ROUTES
# ════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health(quick: bool = Query(True, description="If true, liveness only (for Render)")) -> dict:
    if quick:
        return {"status": "ok", "version": "2.0.0"}
    return collect_health(probe_ai=True)


@app.get("/api/health/full")
def health_full(probe_ai: bool = Query(True)) -> dict:
    return collect_health(probe_ai=probe_ai)


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
        chunks = get_brain().search(
            body.query, domain=body.domain, top_k=body.top_k
        )
        base  = get_full_graph()
        graph = apply_retrieval_highlights(base, chunks, body.query)
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
    vault     = Path(VAULT_DIR).resolve()
    note_path = (vault / safe).resolve()
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
#  COFOUNDER API ROUTES
# ════════════════════════════════════════════════════════════════

@app.get("/api/cofounder/briefing", dependencies=[Depends(require_auth)])
def cofounder_briefing() -> dict:
    """Morning audit — no question needed. Hormozi reviews the startup state."""
    try:
        return daily_briefing()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/cofounder/ask", dependencies=[Depends(require_auth)])
def cofounder_ask(body: CofoundAskRequest) -> dict:
    """Ask Hormozi a question as your cofounder. Full startup context injected."""
    try:
        return ask_cofounder(body.question, domain=body.domain)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/cofounder/log", dependencies=[Depends(require_auth)])
def cofounder_log(body: CofoundLogRequest) -> dict:
    """Log a major decision to the permanent decision log."""
    try:
        return log_decision(
            question=body.question,
            options_considered=body.options_considered,
            hormozi_recommendation=body.hormozi_recommendation,
            decision_made=body.decision_made,
            category=body.category,
            outcome=body.outcome,
            follow_up=body.follow_up,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/cofounder/update", dependencies=[Depends(require_auth)])
def cofounder_update(body: CofoundUpdateRequest) -> dict:
    """Update a field in startup_context.json using dot-notation path."""
    try:
        return update_context(body.field_path, body.value)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/cofounder/context", dependencies=[Depends(require_auth)])
def cofounder_context() -> dict:
    """Read the full current startup context."""
    try:
        return get_context()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/cofounder/decisions", dependencies=[Depends(require_auth)])
def cofounder_decisions() -> dict:
    """Read the full decision log."""
    try:
        return get_decisions()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ════════════════════════════════════════════════════════════════
#  MCP SSE ENDPOINT
# ════════════════════════════════════════════════════════════════

@app.get("/mcp")
async def mcp_sse(request: Request) -> StreamingResponse:
    """
    MCP SSE endpoint for Claude.ai integration.
    Add in Claude.ai → Settings → Integrations:
      https://hormozi-s-transcripts.onrender.com/mcp
    """
    async def event_stream():
        post_url = str(request.base_url).rstrip("/") + "/mcp"
        yield _sse("endpoint", post_url)
        while True:
            if await request.is_disconnected():
                break
            yield ": keep-alive\n\n"
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
    """MCP JSON-RPC handler — brain tools + cofounder tools."""
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error")

    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return _jsonrpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "hormozi-brain", "version": "2.0.0"},
        })

    if method in ("notifications/initialized", "ping"):
        return _jsonrpc_result(req_id, {})

    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": MCP_TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            output = execute_mcp_tool(tool_name, arguments)
            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": output}],
                "isError": False,
            })
        except ValueError as exc:
            return _jsonrpc_error(req_id, -32601, str(exc))
        except Exception as exc:
            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                "isError": True,
            })

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


# ════════════════════════════════════════════════════════════════
#  SPA STATIC SERVING
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