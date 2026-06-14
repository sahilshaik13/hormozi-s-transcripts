"""
╔══════════════════════════════════════════════════════════════════════╗
║              HORMOZI BRAIN — MCP Server                             ║
║              Wraps: https://hormozi-s-transcripts.onrender.com      ║
║              Transport: stdio (Claude Desktop)                      ║
╚══════════════════════════════════════════════════════════════════════╝

TOOLS EXPOSED TO CLAUDE:
  search_hormozi_brain   → semantic search, returns cited chunks
  ask_hormozi_brain      → full Hormozi-voice answer with citations
  hormozi_health          → ping brain + embeddings + AI
  hormozi_brain_stats    → vault stats (notes, chunks, domains)
  read_hormozi_note      → read any vault note by title
  hormozi_graph          → full knowledge graph (nodes + edges)

CLAUDE DESKTOP CONFIG (already set — just verify paths):
  {
    "hormozi-brain": {
      "command": "F:/something_new/alex_hormozi/hormozi's transcripts/venv/Scripts/python.exe",
      "args": [
        "F:/something_new/alex_hormozi/hormozi's transcripts/hormozi_mcp.py"
      ],
      "cwd": "F:/something_new/alex_hormozi/hormozi's transcripts"
    }
  }
"""

# ════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════

BACKEND_URL  = "https://hormozi-s-transcripts.onrender.com"
AUTH_TOKEN   = None   # set to "your-token" if HORMOZI_WEB_TOKEN is enabled
                      # e.g. AUTH_TOKEN = "mysecrettoken"

# ════════════════════════════════════════════════════════════════
#  IMPORTS
# ════════════════════════════════════════════════════════════════

import sys
import json
import urllib.request
import urllib.error
from typing import Any

# ════════════════════════════════════════════════════════════════
#  HTTP HELPERS  (stdlib only — zero dependencies)
# ════════════════════════════════════════════════════════════════

def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if AUTH_TOKEN:
        h["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return h


def _get(path: str) -> dict:
    url = BACKEND_URL.rstrip("/") + path
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, payload: dict) -> dict:
    url = BACKEND_URL.rstrip("/") + path
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════════════════════════════════
#  TOOL IMPLEMENTATIONS
# ════════════════════════════════════════════════════════════════

def search_hormozi_brain(query: str, domain: str = None,
                          top_k: int = 8) -> str:
    """
    Semantic search across the Hormozi brain vault.
    Returns relevant chunks with note titles, types, and source videos.
    """
    payload = {"query": query, "top_k": top_k}
    if domain:
        payload["domain"] = domain

    result = _post("/api/search", payload)

    if "error" in result:
        return f"Search failed: {result['error']}\n{result.get('detail', '')}"

    chunks = result.get("results", result.get("chunks", []))
    if not chunks:
        return "No relevant chunks found for that query."

    lines = [f"SEARCH RESULTS for: '{query}'\n"]
    for i, chunk in enumerate(chunks, 1):
        title    = chunk.get("note_title", "Unknown")
        ntype    = chunk.get("note_type", "note")
        videos   = chunk.get("source_videos", [])
        relevance = chunk.get("relevance", chunk.get("score", "?"))
        text     = chunk.get("text", chunk.get("content", ""))

        video_str = ", ".join(videos) if videos else "Unknown"
        lines.append(f"[{i}] {title} ({ntype}) — relevance: {relevance}")
        lines.append(f"     Source: {video_str}")
        lines.append(f"     {text[:400]}{'...' if len(text) > 400 else ''}\n")

    return "\n".join(lines)


def ask_hormozi_brain(question: str, domain: str = None) -> str:
    """
    Ask the Hormozi brain a question.
    Returns a full answer in Hormozi's voice with citations.
    """
    payload = {"question": question, "history": []}
    if domain:
        payload["domain"] = domain

    result = _post("/api/ask", payload)

    if "error" in result:
        return f"Ask failed: {result['error']}\n{result.get('detail', '')}"

    answer  = result.get("answer", result.get("response", "No answer returned."))
    sources = result.get("sources", result.get("chunks", []))

    output = [answer, "\n---", "📎 CITATIONS:"]
    for i, src in enumerate(sources, 1):
        title   = src.get("note_title", src.get("title", "Unknown"))
        ntype   = src.get("note_type", src.get("type", "note"))
        videos  = src.get("source_videos", [])
        score   = src.get("relevance", src.get("score", "?"))
        video_str = ", ".join(videos) if videos else "Unknown"
        output.append(f"  [{i}] {title} ({ntype}) — {score} — from: {video_str}")

    return "\n".join(output)


def hormozi_brain_stats() -> str:
    """
    Returns stats about the Hormozi brain vault.
    Includes note count, chunk count, domain breakdown.
    """
    result = _get("/api/stats")

    if "error" in result:
        return f"Stats failed: {result['error']}"

    # Inline formatter — avoids importing backend package in stdio MCP
    lines = ["HORMOZI BRAIN — VAULT STATS\n"]
    notes = result.get("note_count", result.get("total_notes", result.get("notes", "?")))
    chunks = result.get("chunk_count", result.get("total_chunks", result.get("chunks", "?")))
    lines.append(f"  Notes  : {notes}")
    lines.append(f"  Chunks : {chunks}")

    by_type = result.get("by_type", result.get("note_types"))
    if isinstance(by_type, dict) and by_type:
        lines.append("\n  By type:")
        for ntype, count in by_type.items():
            lines.append(f"    {ntype:<20} {count}")

    domains = result.get("by_domain", result.get("domains"))
    if isinstance(domains, list) and domains:
        lines.append(f"\n  Domains ({len(domains)}):")
        for domain in domains:
            lines.append(f"    #{domain}")
    elif isinstance(domains, dict) and domains:
        lines.append("\n  By domain:")
        for domain, count in domains.items():
            lines.append(f"    #{domain:<18} {count}")

    return "\n".join(lines)


def hormozi_health(probe_ai: bool = True) -> str:
    """
    Ping brain, embeddings, and Ollama AI in one report.
    """
    path = "/api/health/full"
    if not probe_ai:
        path += "?probe_ai=false"
    result = _get(path)

    if "error" in result:
        return f"Health check failed: {result['error']}\n{result.get('detail', '')}"

    lines = [
        f"HORMOZI BRAIN HEALTH — {result.get('status', '?').upper()}",
        f"  version: {result.get('version', '?')}\n",
    ]
    for name, check in result.get("checks", {}).items():
        status = check.get("status", "?")
        lines.append(f"  [{status.upper():^7}] {name}")
        if name == "brain" and check.get("note_count") is not None:
            lines.append(
                f"           notes={check.get('note_count')} "
                f"chunks={check.get('chunk_count')}"
            )
        if name == "embeddings" and check.get("backend"):
            lines.append(
                f"           backend={check['backend']} "
                f"model={check.get('model', '?')} "
                f"dims={check.get('dimensions', '?')}"
            )
        if name == "ai" and check.get("model"):
            lines.append(f"           model={check['model']}")
            if check.get("probe_reply"):
                lines.append(f"           probe: {check['probe_reply'][:80]}")
        if check.get("error"):
            lines.append(f"           error: {check['error']}")
        lines.append("")

    return "\n".join(lines).rstrip()


def read_hormozi_note(note_path: str) -> str:
    """
    Read a specific vault note by its path.
    e.g. '01 Frameworks/More, Better, New'
    """
    import urllib.parse
    encoded = urllib.parse.quote(note_path)
    result = _get(f"/api/note?path={encoded}")

    if "error" in result:
        return f"Note not found: {result['error']}"

    content = result.get("content", result.get("markdown", ""))
    title   = result.get("title", note_path)

    if not content:
        return f"Note '{note_path}' exists but has no content."

    return f"# {title}\n\n{content}"


def hormozi_graph_summary() -> str:
    """
    Returns a summary of the Hormozi knowledge graph.
    Includes node count, edge count, and top connected nodes.
    """
    result = _get("/api/graph")

    if "error" in result:
        return f"Graph failed: {result['error']}"

    nodes = result.get("nodes", [])
    edges = result.get("edges", result.get("links", []))

    lines = [
        "HORMOZI BRAIN — KNOWLEDGE GRAPH SUMMARY\n",
        f"  Total nodes : {len(nodes)}",
        f"  Total edges : {len(edges)}",
    ]

    # Find top connected nodes by link count
    if nodes:
        # Count connections per node
        connection_count: dict[str, int] = {}
        for node in nodes:
            nid = node.get("id", node.get("name", ""))
            connection_count[nid] = 0

        for edge in edges:
            src = edge.get("source", edge.get("from", ""))
            tgt = edge.get("target", edge.get("to", ""))
            if isinstance(src, dict):
                src = src.get("id", "")
            if isinstance(tgt, dict):
                tgt = tgt.get("id", "")
            if src in connection_count:
                connection_count[src] += 1
            if tgt in connection_count:
                connection_count[tgt] += 1

        top_nodes = sorted(connection_count.items(),
                           key=lambda x: x[1], reverse=True)[:10]

        lines.append("\n  Top 10 most connected nodes:")
        for name, count in top_nodes:
            lines.append(f"    {name[:50]:<50} {count} links")

    # Node type breakdown
    type_counts: dict[str, int] = {}
    for node in nodes:
        ntype = node.get("type", node.get("group", "unknown"))
        type_counts[ntype] = type_counts.get(ntype, 0) + 1

    if type_counts:
        lines.append("\n  By node type:")
        for ntype, count in sorted(type_counts.items(),
                                    key=lambda x: x[1], reverse=True):
            lines.append(f"    {ntype:<20} {count}")

    return "\n".join(lines)

# ════════════════════════════════════════════════════════════════
#  MCP PROTOCOL — stdio JSON-RPC 2.0
# ════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "search_hormozi_brain",
        "description": (
            "Semantic search across Alex Hormozi's extracted knowledge vault. "
            "839 notes built from 211 YouTube videos and his books ($100M Offers, $100M Leads). "
            "Returns relevant chunks with note titles, types, relevance scores, and source videos. "
            "Use this when you need to find specific frameworks, tactics, quotes, or mental models."
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
                    "enum": [
                        "sales", "offers", "pricing", "marketing", "hiring",
                        "operations", "mindset", "identity", "productivity",
                        "scaling", "money", "relationships", "content",
                        "persuasion", "leadership", "investing", "health", "learning"
                    ]
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
            "The answer is grounded in his actual extracted knowledge with citations. "
            "Use this for business advice, strategy questions, mindset coaching, "
            "offer construction, hiring decisions, pricing strategy, and scaling questions. "
            "Supports domain filtering for focused answers."
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
                    "enum": [
                        "sales", "offers", "pricing", "marketing", "hiring",
                        "operations", "mindset", "identity", "productivity",
                        "scaling", "money", "relationships", "content",
                        "persuasion", "leadership", "investing", "health", "learning"
                    ]
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "hormozi_health",
        "description": (
            "Ping brain vault, search embeddings, and Ollama chat model in one call. "
            "Use to verify everything is working before asking questions."
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
            "breakdown by note type (framework, tactic, mental model, mindset, story, quotes, source), "
            "and breakdown by domain. Use this to understand what's in the vault."
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
            "Use the note path like '01 Frameworks/More, Better, New' or "
            "'02 Mental Models/Theory of Constraints'. "
            "Use this after a search to read the full note behind a result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_path": {
                    "type": "string",
                    "description": "Path to the note relative to the vault root. e.g. '01 Frameworks/Value Equation'"
                }
            },
            "required": ["note_path"]
        }
    },
    {
        "name": "hormozi_graph_summary",
        "description": (
            "Get a summary of the Hormozi knowledge graph: total nodes, edges, "
            "top 10 most connected nodes, and breakdown by node type. "
            "Use this to understand which concepts are most central to Hormozi's thinking."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


def handle_request(req: dict) -> dict:
    """Route a JSON-RPC request to the appropriate handler."""
    method  = req.get("method", "")
    req_id  = req.get("id")
    params  = req.get("params", {})

    # ── Protocol handshake ────────────────────────────────────
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name":    "hormozi-brain",
                    "version": "1.0.0"
                }
            }
        }

    if method == "notifications/initialized":
        return None   # no response needed

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # ── Tool discovery ────────────────────────────────────────
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOLS}
        }

    # ── Tool execution ────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "search_hormozi_brain":
                output = search_hormozi_brain(
                    query=arguments["query"],
                    domain=arguments.get("domain"),
                    top_k=arguments.get("top_k", 8)
                )
            elif tool_name == "ask_hormozi_brain":
                output = ask_hormozi_brain(
                    question=arguments["question"],
                    domain=arguments.get("domain")
                )
            elif tool_name == "hormozi_health":
                output = hormozi_health(
                    probe_ai=arguments.get("probe_ai", True)
                )
            elif tool_name == "hormozi_brain_stats":
                output = hormozi_brain_stats()

            elif tool_name == "read_hormozi_note":
                output = read_hormozi_note(
                    note_path=arguments["note_path"]
                )
            elif tool_name == "hormozi_graph_summary":
                output = hormozi_graph_summary()

            else:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name}"
                    }
                }

            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                    "isError": False
                }
            }

        except KeyError as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32602, "message": f"Missing argument: {e}"}
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool error: {e}"}],
                    "isError": True
                }
            }

    # ── Unknown method ────────────────────────────────────────
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """
    stdio MCP server loop.
    Reads JSON-RPC requests line by line from stdin.
    Writes JSON-RPC responses to stdout.
    All logs go to stderr so stdout stays clean.
    """
    print("Hormozi Brain MCP server starting...", file=sys.stderr)
    print(f"Backend: {BACKEND_URL}", file=sys.stderr)

    # Verify backend is reachable
    health = _get("/api/health/full")
    if "error" in health:
        print(f"⚠  Backend unreachable: {health['error']}", file=sys.stderr)
        print("   Server will still start — backend may be cold-starting on Render.",
              file=sys.stderr)
    else:
        print(f"✓  Backend healthy: {health}", file=sys.stderr)

    print("✓  Ready. Listening on stdin.", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            error_resp = {
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }
            print(json.dumps(error_resp), flush=True)
            continue

        try:
            response = handle_request(req)
        except Exception as e:
            print(f"Handler error: {e}", file=sys.stderr)
            response = {
                "jsonrpc": "2.0", "id": req.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {e}"}
            }

        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()