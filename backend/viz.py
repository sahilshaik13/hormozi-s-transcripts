"""
Obsidian-style graph visualization for Hormozi Brain RAG retrievals.
Generates a self-contained HTML file — no extra pip packages needed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

TYPE_COLORS = {
    "moc":          "#a78bfa",
    "framework":    "#60a5fa",
    "mental-model": "#34d399",
    "tactic":       "#fbbf24",
    "mindset":      "#f472b6",
    "story":        "#fb923c",
    "quotes":       "#94a3b8",
    "source-note":  "#64748b",
    "index":        "#e2e8f0",
    "note":         "#9ca3af",
}

TYPE_LABELS = {
    "moc": "MOC",
    "mental-model": "Mental Model",
    "source-note": "Source Note",
}


def normalize_key(value: str) -> str:
    """Use forward slashes so Windows paths don't create duplicate nodes."""
    return value.replace("\\", "/").strip()


def normalize_wikilink_target(raw: str) -> str:
    """Obsidian-style link target: path only, no alias/heading/block/nested brackets."""
    t = raw.strip().replace("\\", "/")
    while t.startswith("["):
        t = t[1:]
    while t.endswith("]"):
        t = t[:-1]
    t = t.strip()
    if not t:
        return ""
    # [[Note#Heading]] and [[Note^block]]
    t = t.split("#", 1)[0].split("^", 1)[0].strip()
    return t.rstrip("/")


def parse_frontmatter_title(text: str, fallback: str) -> str:
    if not text.startswith("---"):
        return fallback
    end = text.find("---", 3)
    if end == -1:
        return fallback
    for line in text[3:end].splitlines():
        if line.startswith("title:"):
            return line.partition(":")[2].strip().strip('"')
    return fallback


def build_vault_index(vault_dir: Path) -> dict[str, dict]:
    """Map note titles and link targets to vault metadata."""
    index: dict[str, dict] = {}

    for path in vault_dir.rglob("*.md"):
        raw = path.read_text(encoding="utf-8")
        title = parse_frontmatter_title(raw, path.stem)
        rel = str(path.relative_to(vault_dir)).replace("\\", "/")
        note_type = "note"
        if raw.startswith("---"):
            end = raw.find("---", 3)
            if end != -1:
                for line in raw[3:end].splitlines():
                    if line.startswith("type:"):
                        note_type = line.partition(":")[2].strip().strip('"')
                        break

        entry = {
            "title": title,
            "path": rel,
            "type": note_type,
            "stem": path.stem,
        }

        for key in {title, path.stem, rel, rel.removesuffix(".md")}:
            index[key.lower()] = entry

        parts = rel.split("/")
        if len(parts) > 1:
            index[f"{parts[0]}/{path.stem}".lower()] = entry

    return index


def resolve_link(target: str, vault_index: dict[str, dict]) -> dict | None:
    clean = normalize_wikilink_target(target)
    if not clean:
        return None

    stem = Path(clean).stem
    candidates = [
        clean,
        clean.removesuffix(".md"),
        clean.split("/")[-1],
        stem,
    ]
    if stem.lower().startswith("the "):
        candidates.append(stem[4:])

    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        hit = vault_index.get(key)
        if hit:
            return hit
    return None


def extract_wikilinks(note_path: Path) -> list[str]:
    if not note_path.exists():
        return []
    text = note_path.read_text(encoding="utf-8")
    targets: list[str] = []
    for m in WIKILINK_RE.finditer(text):
        target = normalize_wikilink_target(m.group(1))
        if target:
            targets.append(target)
    return targets


def build_full_vault_graph(vault_dir: Path) -> dict:
    """Full Obsidian-style vault graph — all notes and wikilink edges."""
    vault_index = build_vault_index(vault_dir)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[str] = set()

    for path in sorted(vault_dir.rglob("*.md")):
        rel = normalize_key(str(path.relative_to(vault_dir)))
        raw = path.read_text(encoding="utf-8")
        title = parse_frontmatter_title(raw, path.stem)
        note_type = "note"
        if raw.startswith("---"):
            end = raw.find("---", 3)
            if end != -1:
                for line in raw[3:end].splitlines():
                    if line.startswith("type:"):
                        note_type = line.partition(":")[2].strip().strip('"')
                        break

        nodes[rel] = {
            "id": rel,
            "title": title,
            "type": note_type,
            "path": rel,
            "retrieved": False,
            "relevance": 0.0,
            "hit_count": 0,
        }

        for link_target in extract_wikilinks(path):
            resolved = resolve_link(link_target, vault_index)
            if not resolved:
                continue
            target_key = normalize_key(resolved["path"])
            edge_id = f"{rel}|{target_key}|wikilink"
            if edge_id in edge_keys or rel == target_key:
                continue
            edge_keys.add(edge_id)
            edges.append({
                "from": rel,
                "to": target_key,
                "type": "wikilink",
                "label": "",
            })

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "retrieved": 0,
            "question": "",
        },
    }


def apply_retrieval_highlights(
    graph: dict,
    chunks: list[dict],
    question: str = "",
    session_hits: dict[str, int] | None = None,
) -> dict:
    """Merge retrieval state onto a full (or partial) graph for the web UI."""
    session_hits = session_hits or {}
    node_map = {n["id"]: dict(n) for n in graph.get("nodes", [])}
    edges = list(graph.get("edges", []))
    edge_keys = {f"{e['from']}|{e['to']}|{e['type']}" for e in edges}

    if question:
        node_map["__query__"] = {
            "id": "__query__",
            "title": f"❓ {question[:72]}",
            "type": "query",
            "path": "",
            "retrieved": True,
            "relevance": 1.0,
            "hit_count": 1,
        }

    for chunk in chunks:
        note_path = normalize_key(chunk.get("note_path", "") or chunk.get("note_title", ""))
        if not note_path:
            continue
        hit = max(
            session_hits.get(note_path, 0),
            session_hits.get(chunk.get("note_path", ""), 0),
            1,
        )
        relevance = chunk.get("relevance", 0)
        if note_path in node_map:
            node = node_map[note_path]
            node["retrieved"] = True
            node["relevance"] = max(node.get("relevance", 0), relevance)
            node["hit_count"] = max(node.get("hit_count", 0), hit)
            node["snippet"] = chunk.get("text", "")[:220]
        else:
            node_map[note_path] = {
                "id": note_path,
                "title": chunk.get("note_title", note_path),
                "type": chunk.get("note_type", "note"),
                "path": note_path,
                "retrieved": True,
                "relevance": relevance,
                "hit_count": hit,
                "snippet": chunk.get("text", "")[:220],
            }

        if question:
            eid = f"__query__|{note_path}|retrieval"
            if eid not in edge_keys:
                edge_keys.add(eid)
                edges.append({
                    "from": "__query__",
                    "to": note_path,
                    "type": "retrieval",
                    "label": f"{int(relevance * 100)}%",
                })

    return {
        "nodes": list(node_map.values()),
        "edges": edges,
        "stats": {
            "total_nodes": len(node_map),
            "total_edges": len(edges),
            "retrieved": sum(1 for n in node_map.values() if n.get("retrieved")),
            "question": question,
        },
    }


def build_retrieval_graph(
    chunks: list[dict],
    vault_dir: Path,
    question: str = "",
    session_hits: dict[str, int] | None = None,
) -> dict:
    """Build nodes/edges for an Obsidian-style retrieval graph."""
    vault_index = build_vault_index(vault_dir)
    session_hits = session_hits or {}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[str] = set()

    def add_node(key: str, title: str, note_type: str, path: str,
                 retrieved: bool = False, relevance: float = 0.0,
                 snippet: str = "", hit_count: int = 0):
        if key in nodes:
            node = nodes[key]
            if retrieved:
                node["retrieved"] = True
                node["relevance"] = max(node.get("relevance", 0), relevance)
            node["hit_count"] = max(node.get("hit_count", 0), hit_count)
            return

        nodes[key] = {
            "id": key,
            "title": title,
            "type": note_type,
            "path": path,
            "retrieved": retrieved,
            "relevance": relevance,
            "snippet": snippet[:220] + ("…" if len(snippet) > 220 else ""),
            "hit_count": hit_count,
        }

    def add_edge(source: str, target: str, edge_type: str, label: str = ""):
        edge_id = f"{source}|{target}|{edge_type}"
        if edge_id in edge_keys or source == target:
            return
        edge_keys.add(edge_id)
        edges.append({
            "from": source,
            "to": target,
            "type": edge_type,
            "label": label,
        })

    if question:
        add_node("__query__", f"❓ {question[:60]}", "query", "", retrieved=True, relevance=1.0)

    retrieved_keys: list[str] = []
    for chunk in chunks:
        title = chunk.get("note_title", "Unknown")
        note_type = chunk.get("note_type", "note")
        note_path = normalize_key(chunk.get("note_path", ""))
        relevance = chunk.get("relevance", 0)
        snippet = chunk.get("text", "")
        key = normalize_key(note_path or title)
        hit_count = max(
            session_hits.get(key, 0),
            session_hits.get(note_path, 0),
            session_hits.get(chunk.get("note_path", ""), 0),
            1 if question else 0,
        )

        add_node(
            key, title, note_type, note_path,
            retrieved=True, relevance=relevance,
            snippet=snippet, hit_count=hit_count,
        )
        retrieved_keys.append(key)

        if question:
            add_edge("__query__", key, "retrieval",
                     label=f"{int(relevance * 100)}%")

        full_path = vault_dir / note_path if note_path else None
        if full_path and full_path.exists():
            for link_target in extract_wikilinks(full_path):
                resolved = resolve_link(link_target, vault_index)
                if not resolved:
                    continue
                neighbor_key = normalize_key(resolved["path"])
                add_node(
                    neighbor_key, resolved["title"], resolved["type"],
                    neighbor_key, retrieved=False,
                )
                add_edge(key, neighbor_key, "wikilink")

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "retrieved": len(retrieved_keys),
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "question": question,
        },
    }


def render_graph_html(graph: dict, output_path: Path, title: str = "Hormozi Brain — Retrieval Graph"):
    """Write a self-contained interactive HTML graph (no CDN dependencies)."""
    nodes_json = json.dumps(graph["nodes"])
    edges_json = json.dumps(graph["edges"])
    stats = graph["stats"]
    type_colors_json = json.dumps(TYPE_COLORS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; overflow: hidden; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #1e1e1e; color: #dcddde;
    display: flex; flex-direction: column;
  }}
  header {{
    height: 48px; padding: 0 20px; background: #252525;
    border-bottom: 1px solid #333; display: flex;
    align-items: center; justify-content: space-between; flex-shrink: 0;
  }}
  header h1 {{ font-size: 15px; font-weight: 600; color: #fff; }}
  header .stats {{ font-size: 12px; color: #999; }}
  #canvas-wrap {{
    flex: 1; min-height: 0; position: relative; background: #1a1a1a;
  }}
  canvas {{ display: block; width: 100%; height: 100%; cursor: grab; }}
  canvas:active {{ cursor: grabbing; }}
  #sidebar {{
    position: absolute; right: 0; top: 0; bottom: 0; width: 300px;
    background: #252525; border-left: 1px solid #333; padding: 16px;
    overflow-y: auto; transform: translateX(100%);
    transition: transform 0.2s; z-index: 10;
  }}
  #sidebar.open {{ transform: translateX(0); }}
  #sidebar h2 {{ font-size: 14px; margin-bottom: 8px; color: #fff; }}
  #sidebar .meta {{ font-size: 12px; color: #999; margin-bottom: 12px; }}
  #sidebar .snippet {{
    font-size: 12px; line-height: 1.5; color: #bbb;
    background: #1a1a1a; padding: 10px; border-radius: 6px;
    border-left: 3px solid #7c6af7;
  }}
  .badge {{
    display: inline-block; font-size: 10px; padding: 2px 7px;
    border-radius: 10px; margin-right: 4px; font-weight: 600;
  }}
  .badge.retrieved {{ background: #7c6af733; color: #a78bfa; border: 1px solid #7c6af7; }}
  .badge.neighbor {{ background: #333; color: #888; }}
  #legend {{
    position: absolute; bottom: 16px; left: 16px;
    background: #252525ee; border: 1px solid #333;
    border-radius: 8px; padding: 12px 14px; font-size: 11px; z-index: 5;
    pointer-events: none;
  }}
  #legend .row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
  #legend .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .hint {{
    position: absolute; bottom: 16px; right: 16px;
    font-size: 11px; color: #555; z-index: 5; pointer-events: none;
  }}
</style>
</head>
<body>
<header>
  <h1>🧠 {title}</h1>
  <div class="stats">{stats["retrieved"]} retrieved · {stats["total_nodes"]} nodes · {stats["total_edges"]} links</div>
</header>
<div id="canvas-wrap">
  <canvas id="graph"></canvas>
  <div id="sidebar">
    <h2 id="node-title">—</h2>
    <div class="meta" id="node-meta"></div>
    <div class="snippet" id="node-snippet"></div>
  </div>
  <div id="legend">
    <div style="font-weight:600;margin-bottom:6px;color:#ccc">Node types</div>
    <div class="row"><div class="dot" style="background:#7c6af7;border:2px solid #fff"></div> Retrieved chunk</div>
    <div class="row"><div class="dot" style="background:#7c6af7"></div> Query</div>
    <div class="row"><div class="dot" style="background:#a78bfa"></div> MOC</div>
    <div class="row"><div class="dot" style="background:#60a5fa"></div> Framework</div>
    <div class="row"><div class="dot" style="background:#34d399"></div> Mental Model</div>
    <div class="row"><div class="dot" style="background:#fbbf24"></div> Tactic</div>
    <div class="row"><div class="dot" style="background:#f472b6"></div> Mindset</div>
    <div class="row"><div class="dot" style="background:#64748b"></div> Source / Other</div>
    <div style="margin-top:8px;color:#666">— dashed = retrieval link</div>
  </div>
  <div class="hint">Click node · drag to move · scroll to zoom · drag bg to pan</div>
</div>
<script>
const TYPE_COLORS = {type_colors_json};
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};

const canvas = document.getElementById("graph");
const ctx = canvas.getContext("2d");
const sidebar = document.getElementById("sidebar");

const nodes = RAW_NODES.map((n, i) => {{
  const isQuery = n.id === "__query__";
  const angle = (i / RAW_NODES.length) * Math.PI * 2;
  const radius = isQuery ? 0 : 120 + Math.random() * 80;
  return {{
    ...n,
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    vx: 0, vy: 0,
    r: isQuery ? 22 : (n.retrieved ? 14 + (n.relevance || 0) * 8 : 8),
    color: isQuery ? "#7c6af7" : (TYPE_COLORS[n.type] || "#9ca3af"),
    label: n.title.length > 28 ? n.title.slice(0, 26) + "…" : n.title,
  }};
}});

const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
const edges = RAW_EDGES.filter(e => nodeById[e.from] && nodeById[e.to]);

let scale = 1, panX = 0, panY = 0;
let selected = null, hovered = null;
let draggingNode = null, draggingPan = false;
let lastMX = 0, lastMY = 0;

function resize() {{
  const wrap = document.getElementById("canvas-wrap");
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  panX = canvas.width / 2;
  panY = canvas.height / 2;
}}
window.addEventListener("resize", resize);
resize();

function screenToWorld(sx, sy) {{
  return {{ x: (sx - panX) / scale, y: (sy - panY) / scale }};
}}

function hitTest(sx, sy) {{
  const w = screenToWorld(sx, sy);
  for (let i = nodes.length - 1; i >= 0; i--) {{
    const n = nodes[i];
    const dx = w.x - n.x, dy = w.y - n.y;
    if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
  }}
  return null;
}}

function showSidebar(n) {{
  document.getElementById("node-title").textContent = n.title;
  const typeLabel = n.type === "query" ? "Query" : (n.type || "note");
  const badge = n.retrieved
    ? '<span class="badge retrieved">RETRIEVED</span>'
    : '<span class="badge neighbor">wikilink neighbor</span>';
  document.getElementById("node-meta").innerHTML =
    badge + typeLabel +
    (n.relevance ? " · " + Math.round(n.relevance * 100) + "% match" : "") +
    (n.path ? "<br><span style='color:#666'>" + n.path + "</span>" : "");
  document.getElementById("node-snippet").textContent =
    n.snippet || "(no snippet — neighbor node)";
  sidebar.classList.add("open");
}}

canvas.addEventListener("mousedown", e => {{
  const n = hitTest(e.offsetX, e.offsetY);
  if (n) {{ draggingNode = n; selected = n; showSidebar(n); }}
  else {{ draggingPan = true; sidebar.classList.remove("open"); selected = null; }}
  lastMX = e.offsetX; lastMY = e.offsetY;
}});
canvas.addEventListener("mousemove", e => {{
  hovered = hitTest(e.offsetX, e.offsetY);
  if (draggingNode) {{
    const w = screenToWorld(e.offsetX, e.offsetY);
    draggingNode.x = w.x; draggingNode.y = w.y;
    draggingNode.vx = 0; draggingNode.vy = 0;
  }} else if (draggingPan) {{
    panX += e.offsetX - lastMX; panY += e.offsetY - lastMY;
  }}
  lastMX = e.offsetX; lastMY = e.offsetY;
}});
window.addEventListener("mouseup", () => {{ draggingNode = null; draggingPan = false; }});
canvas.addEventListener("wheel", e => {{
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const mx = e.offsetX, my = e.offsetY;
  panX = mx - (mx - panX) * factor;
  panY = my - (my - panY) * factor;
  scale *= factor;
}}, {{ passive: false }});

function simulate() {{
  const repulsion = 3200;
  const attraction = 0.004;
  const centerPull = 0.002;

  for (let i = 0; i < nodes.length; i++) {{
    for (let j = i + 1; j < nodes.length; j++) {{
      const a = nodes[i], b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = repulsion / (dist * dist);
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      if (a !== draggingNode) {{ a.vx += fx; a.vy += fy; }}
      if (b !== draggingNode) {{ b.vx -= fx; b.vy -= fy; }}
    }}
  }}

  for (const e of edges) {{
    const a = nodeById[e.from], b = nodeById[e.to];
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const force = dist * attraction;
    const fx = (dx / dist) * force, fy = (dy / dist) * force;
    if (a !== draggingNode) {{ a.vx += fx; a.vy += fy; }}
    if (b !== draggingNode) {{ b.vx -= fx; b.vy -= fy; }}
  }}

  for (const n of nodes) {{
    if (n === draggingNode) continue;
    n.vx -= n.x * centerPull;
    n.vy -= n.y * centerPull;
    n.vx *= 0.85; n.vy *= 0.85;
    n.x += n.vx; n.y += n.vy;
  }}
}}

function drawDashedLine(x1, y1, x2, y2) {{
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const dash = 6, gap = 4;
  let dist = 0;
  while (dist < len) {{
    const t1 = dist / len, t2 = Math.min((dist + dash) / len, 1);
    ctx.beginPath();
    ctx.moveTo(x1 + dx * t1, y1 + dy * t1);
    ctx.lineTo(x1 + dx * t2, y1 + dy * t2);
    ctx.stroke();
    dist += dash + gap;
  }}
}}

function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.translate(panX, panY);
  ctx.scale(scale, scale);

  for (const e of edges) {{
    const a = nodeById[e.from], b = nodeById[e.to];
    if (!a || !b) continue;
    const isRetrieval = e.type === "retrieval";
    ctx.strokeStyle = isRetrieval ? "rgba(124,106,247,0.55)" : "rgba(80,80,80,0.35)";
    ctx.lineWidth = isRetrieval ? 2 / scale : 1 / scale;
    if (isRetrieval) drawDashedLine(a.x, a.y, b.x, b.y);
    else {{
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }}
  }}

  for (const n of nodes) {{
    const isActive = n === selected || n === hovered;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    ctx.fillStyle = n.color;
    ctx.fill();
    ctx.strokeStyle = n.retrieved || n.id === "__query__"
      ? "#ffffff" : (isActive ? "#aaa" : "#444");
    ctx.lineWidth = (n.retrieved || n.id === "__query__" ? 2.5 : 1) / scale;
    ctx.stroke();

    if (n.retrieved || n.id === "__query__" || isActive) {{
      ctx.fillStyle = n.retrieved || n.id === "__query__" ? "#eee" : "#888";
      ctx.font = `${{11 / scale}}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(n.label, n.x, n.y + n.r + 14 / scale);
    }}
  }}

  ctx.restore();
}}

function tick() {{
  simulate();
  draw();
  requestAnimationFrame(tick);
}}
tick();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return output_path


def open_html_file(path: Path) -> None:
    """Open HTML in the system default browser (avoids Cursor's webbrowser hook)."""
    resolved = path.resolve()
    if sys.platform == "win32":
        os.startfile(str(resolved))  # noqa: S606 — Windows default app for .html
    elif sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
    else:
        subprocess.run(["xdg-open", str(resolved)], check=False)


def open_retrieval_graph(
    chunks: list[dict],
    vault_dir: str | Path,
    question: str = "",
    output_path: str | Path = "./brain-retrieval-graph.html",
    session_hits: dict[str, int] | None = None,
    open_browser: bool = False,
) -> Path:
    """Build the retrieval graph HTML; optionally open in system browser."""
    vault_dir = Path(vault_dir)
    out = Path(output_path)
    graph = build_retrieval_graph(chunks, vault_dir, question, session_hits)
    title = "Last Query" if question else "Session Retrieval Map"
    render_graph_html(graph, out, title=title)
    if open_browser:
        open_html_file(out)
    return out
