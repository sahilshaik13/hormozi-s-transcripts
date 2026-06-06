import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { forceCollide } from "d3-force-3d";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject } from "react-force-graph-2d";
import type { GraphData, GraphLink, GraphNode } from "../types";

const LAYOUT_VERSION = 8;
const NODE_RADIUS_SCALE = 2.25;
const NODE_GAP = 10;
const LINE_GAP = 6;
const EXPAND_FACTOR = 2.6;
const ORPHAN_RING = 560;

type FGNode = GraphNode & { x?: number; y?: number; val?: number; degree?: number };
type FGLink = LinkObject<FGNode, GraphLink>;

const DEFAULT_COLORS: Record<string, string> = {
  moc: "#a78bfa",
  framework: "#60a5fa",
  "mental-model": "#34d399",
  tactic: "#fbbf24",
  mindset: "#f472b6",
  story: "#fb923c",
  quotes: "#94a3b8",
  "source-note": "#64748b",
  index: "#e2e8f0",
  query: "#c084fc",
  note: "#6b7280",
};

const TYPE_LEGEND: { type: string; label: string }[] = [
  { type: "moc", label: "MOC" },
  { type: "framework", label: "Framework" },
  { type: "mental-model", label: "Mental model" },
  { type: "tactic", label: "Tactic" },
  { type: "mindset", label: "Mindset" },
  { type: "story", label: "Story" },
  { type: "quotes", label: "Quotes" },
  { type: "source-note", label: "Source" },
];

function nodeTypeColor(node: FGNode, palette: Record<string, string>): string {
  if (node.id === "__query__") return palette.query ?? "#c084fc";
  return palette[node.type] ?? palette.note ?? "#9ca3af";
}

function sizeFromDegree(deg: number): number {
  if (deg <= 0) return 0.4;
  return Math.min(1.6, 0.4 + Math.log2(deg + 1) * 0.2);
}

function nodeRadius(node: FGNode): number {
  return Math.sqrt(Math.max(0.4, node.val ?? 0.4)) * NODE_RADIUS_SCALE;
}

function collisionRadius(node: FGNode): number {
  return nodeRadius(node) + NODE_GAP;
}

function linkAlpha(link: FGLink, src: FGNode, tgt: FGNode): number {
  const hubDeg = Math.max(src.degree ?? 0, tgt.degree ?? 0);
  if (link.type === "retrieval") return 0.75;
  if (hubDeg > 40) return 0.04;
  if (hubDeg > 15) return 0.08;
  return 0.18;
}

function linkEndpointId(end: string | FGNode): string {
  return typeof end === "object" ? end.id : end;
}

function linkStrength(src: FGNode, tgt: FGNode): number {
  const hub = Math.max(src.degree ?? 0, tgt.degree ?? 0);
  if (hub > 50) return 0.008;
  if (hub > 20) return 0.025;
  if (hub > 8) return 0.06;
  return 0.14;
}

function expandFromCenter(nodes: FGNode[], factor: number) {
  let cx = 0;
  let cy = 0;
  let count = 0;
  for (const n of nodes) {
    if (n.x == null || n.y == null) continue;
    cx += n.x;
    cy += n.y;
    count += 1;
  }
  if (!count) return;
  cx /= count;
  cy /= count;
  for (const n of nodes) {
    if (n.x == null || n.y == null) continue;
    n.x = cx + (n.x - cx) * factor;
    n.y = cy + (n.y - cy) * factor;
  }
}

function placeOrphans(nodes: FGNode[], ring: number) {
  const orphans = nodes.filter((n) => (n.degree ?? 0) === 0 && n.id !== "__query__");
  const step = (Math.PI * 2) / Math.max(orphans.length, 1);
  orphans.forEach((n, i) => {
    const angle = i * step;
    n.x = Math.cos(angle) * ring;
    n.y = Math.sin(angle) * ring;
  });
}

function resolveNodeOverlaps(nodes: FGNode[], iterations: number): boolean {
  const placed = nodes.filter((n) => n.x != null && n.y != null);
  let anyMoved = false;

  for (let iter = 0; iter < iterations; iter++) {
    let moved = false;
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i];
        const b = placed[j];
        const dx = b.x! - a.x!;
        const dy = b.y! - a.y!;
        const dist = Math.hypot(dx, dy) || 0.001;
        const minDist = collisionRadius(a) + collisionRadius(b);
        if (dist >= minDist) continue;

        const push = (minDist - dist) / 2;
        const ux = dx / dist;
        const uy = dy / dist;
        if (a.id !== "__query__") {
          a.x! -= ux * push;
          a.y! -= uy * push;
        }
        if (b.id !== "__query__") {
          b.x! += ux * push;
          b.y! += uy * push;
        }
        moved = true;
        anyMoved = true;
      }
    }
    if (!moved) break;
  }

  return anyMoved;
}

function pointSegmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy || 1;
  let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
  t = Math.max(0.08, Math.min(0.92, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  const ox = px - cx;
  const oy = py - cy;
  const dist = Math.hypot(ox, oy);
  return { dist, ox, oy, cx, cy };
}

function nudgeNodesOffLinks(nodes: FGNode[], links: FGLink[], iterations: number) {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  for (let iter = 0; iter < iterations; iter++) {
    for (const node of nodes) {
      if (node.x == null || node.y == null || node.id === "__query__") continue;
      const margin = collisionRadius(node) + LINE_GAP;

      for (const link of links) {
        const srcId = linkEndpointId(link.source as string | FGNode);
        const tgtId = linkEndpointId(link.target as string | FGNode);
        if (node.id === srcId || node.id === tgtId) continue;

        const src = nodeById.get(srcId);
        const tgt = nodeById.get(tgtId);
        if (src?.x == null || src?.y == null || tgt?.x == null || tgt?.y == null) continue;

        const hit = pointSegmentDistance(node.x, node.y, src.x, src.y, tgt.x, tgt.y);
        if (hit.dist >= margin || hit.dist < 0.001) continue;

        const push = (margin - hit.dist) * 0.65;
        node.x += (hit.ox / hit.dist) * push;
        node.y += (hit.oy / hit.dist) * push;
      }
    }
    resolveNodeOverlaps(nodes, 3);
  }
}

function linkCurveControl(
  src: FGNode,
  tgt: FGNode,
  srcId: string,
  tgtId: string,
): { mx: number; my: number } {
  const dx = tgt.x! - src.x!;
  const dy = tgt.y! - src.y!;
  const len = Math.hypot(dx, dy) || 1;
  const hub = Math.max(src.degree ?? 0, tgt.degree ?? 0);
  const bowSign = (srcId.charCodeAt(0) + tgtId.charCodeAt(0)) % 2 === 0 ? 1 : -1;
  const bow = hub > 20
    ? Math.min(48, len * 0.14)
    : hub > 8
      ? Math.min(28, len * 0.09)
      : Math.min(14, len * 0.05);
  const px = -dy / len;
  const py = dx / len;
  return {
    mx: (src.x! + tgt.x!) / 2 + px * bow * bowSign,
    my: (src.y! + tgt.y!) / 2 + py * bow * bowSign,
  };
}

function polishLayout(nodes: FGNode[], links: FGLink[]) {
  expandFromCenter(nodes, EXPAND_FACTOR);
  placeOrphans(nodes, ORPHAN_RING * EXPAND_FACTOR);
  resolveNodeOverlaps(nodes, 32);
  nudgeNodesOffLinks(nodes, links, 10);
  resolveNodeOverlaps(nodes, 16);
}

type Props = {
  graph: GraphData;
  sessionHits: Record<string, number>;
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
};

export function BrainGraph({ graph, sessionHits, selectedId, onSelect }: Props) {
  const fgRef = useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined);
  const positionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const layoutKeyRef = useRef("");
  const layoutPolishedRef = useRef(false);
  const initialZoomDone = useRef(false);
  const [settling, setSettling] = useState(true);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const colors = { ...DEFAULT_COLORS, ...graph.typeColors };

  const linkId = linkEndpointId;

  const layoutKey = `${LAYOUT_VERSION}:${graph.nodes.length}:${graph.links.length}`;

  const data = useMemo(() => {
    const links = graph.links.map((l) => ({
      ...l,
      source: linkId(l.source as string | FGNode),
      target: linkId(l.target as string | FGNode),
    }));

    const degree = new Map<string, number>();
    for (const l of links) {
      const src = String(l.source);
      const tgt = String(l.target);
      degree.set(src, (degree.get(src) ?? 0) + 1);
      degree.set(tgt, (degree.get(tgt) ?? 0) + 1);
    }

    let scatterIdx = 0;
    const saved = positionsRef.current;
    const isNewLayout = layoutKey !== layoutKeyRef.current;
    if (isNewLayout) saved.clear();

    const golden = Math.PI * (3 - Math.sqrt(5));

    const nodes = graph.nodes.map((n) => {
      const deg = degree.get(n.id) ?? 0;
      const nodeSize = sizeFromDegree(deg);

      const cached = saved.get(n.id);
      let x = cached?.x;
      let y = cached?.y;

      if (x === undefined && isNewLayout && n.id !== "__query__") {
        if (deg === 0) {
          const angle = scatterIdx * golden;
          x = Math.cos(angle) * ORPHAN_RING;
          y = Math.sin(angle) * ORPHAN_RING;
        } else {
          const angle = scatterIdx * golden;
          const radius = 60 + Math.sqrt(scatterIdx + 1) * 38;
          x = Math.cos(angle) * radius;
          y = Math.sin(angle) * radius;
        }
        scatterIdx += 1;
      }

      return {
        ...n,
        x,
        y,
        fx: n.id === "__query__" ? 0 : undefined,
        fy: n.id === "__query__" ? 0 : undefined,
        degree: deg,
        val: n.id === "__query__"
          ? 2.2
          : n.retrieved
            ? Math.min(1.8, nodeSize * 1.2)
            : nodeSize,
      };
    });

    return { nodes, links };
  }, [graph, layoutKey]);

  const accessed = useMemo(() => {
    const set = new Set<string>();
    for (const n of graph.nodes) {
      if (n.retrieved || n.id === "__query__" || (sessionHits[n.id] ?? 0) > 0) {
        set.add(n.id);
      }
    }
    return set;
  }, [graph.nodes, sessionHits]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    const charge = fg.d3Force("charge");
    if (charge) {
      charge.strength((node: FGNode) => {
        const deg = node.degree ?? 0;
        if (node.id === "__query__") return -120;
        if (deg === 0) return -90;
        return -55 - Math.min(deg, 20) * 2.5;
      });
      charge.distanceMax(680);
    }

    const link = fg.d3Force("link");
    if (link) {
      link.distance((l: FGLink) => {
        const src = l.source as FGNode;
        const tgt = l.target as FGNode;
        const hub = Math.max(src.degree ?? 0, tgt.degree ?? 0);
        return hub > 30 ? 110 : hub > 10 ? 80 : 55;
      });
      link.strength((l: FGLink) => {
        const src = l.source as FGNode;
        const tgt = l.target as FGNode;
        return linkStrength(src, tgt);
      });
    }

    const center = fg.d3Force("center");
    if (center) center.strength(0.015);

    fg.d3Force(
      "collision",
      forceCollide<FGNode>()
        .radius((node) => collisionRadius(node) + 4)
        .strength(1)
        .iterations(6),
    );

    if (layoutKey !== layoutKeyRef.current) {
      layoutKeyRef.current = layoutKey;
      layoutPolishedRef.current = false;
      initialZoomDone.current = false;
      setSettling(true);
      fg.d3ReheatSimulation();
    }
  }, [layoutKey]);

  useEffect(() => {
    if (!settling) return;
    const timeout = window.setTimeout(() => setSettling(false), 10000);
    return () => window.clearTimeout(timeout);
  }, [layoutKey, settling]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !graph.stats.question) return;
    const t = setTimeout(() => {
      fg.zoomToFit(500, 64, (n) => Boolean(n.retrieved) || n.id === "__query__");
    }, 300);
    return () => clearTimeout(t);
  }, [graph.stats.question]);

  const savePositions = useCallback(() => {
    const positions = positionsRef.current;
    for (const node of data.nodes) {
      if (node.x != null && node.y != null) {
        positions.set(node.id, { x: node.x, y: node.y });
      }
    }
  }, [data.nodes]);

  const handleNodeDragEnd = useCallback(() => {
    resolveNodeOverlaps(data.nodes, 10);
    nudgeNodesOffLinks(data.nodes, data.links, 2);
    resolveNodeOverlaps(data.nodes, 6);
    savePositions();
    fgRef.current?.resumeAnimation();
  }, [data.nodes, data.links, savePositions]);

  const handleEngineStop = useCallback(() => {
    setSettling(false);

    if (layoutPolishedRef.current) return;
    layoutPolishedRef.current = true;

    const nodes = data.nodes;
    const links = data.links;

    window.setTimeout(() => {
      polishLayout(nodes, links);
      savePositions();
      const fg = fgRef.current;
      if (!fg) return;

      fg.resumeAnimation();

      if (!initialZoomDone.current) {
        initialZoomDone.current = true;
        requestAnimationFrame(() => {
          fg.zoomToFit(600, 110);
        });
      }
    }, 0);
  }, [data.nodes, data.links, savePositions]);

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (node.x == null || node.y == null) return;

      const isAccessed = accessed.has(node.id);
      const isSelected = selectedId === node.id;
      const isHovered = hoveredId === node.id;
      const hits = sessionHits[node.id] ?? node.hit_count ?? 0;
      const r = nodeRadius(node);
      const fill = nodeTypeColor(node, colors);

      ctx.save();

      if (isAccessed) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(167, 139, 250, 0.22)";
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = fill;
      ctx.fill();

      ctx.strokeStyle =
        isSelected || isHovered
          ? "#ffffff"
          : isAccessed
            ? "rgba(255, 255, 255, 0.75)"
            : "rgba(255, 255, 255, 0.35)";
      ctx.lineWidth = (isSelected || isHovered ? 1.6 : isAccessed ? 1.2 : 0.6) / globalScale;
      ctx.stroke();

      if (isAccessed && hits > 1) {
        ctx.fillStyle = "#fff";
        ctx.font = `${8 / globalScale}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(hits), node.x, node.y);
      }

      if (isSelected || isHovered) {
        const label = node.title.length > 36 ? `${node.title.slice(0, 34)}…` : node.title;
        ctx.font = `${10 / globalScale}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = "#e4e4e7";
        ctx.fillText(label, node.x, node.y + r + 8 / globalScale);
      }

      ctx.restore();
    },
    [accessed, colors, hoveredId, selectedId, sessionHits],
  );

  const paintLink = useCallback(
    (link: FGLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source as FGNode;
      const tgt = link.target as FGNode;
      if (src.x == null || src.y == null || tgt.x == null || tgt.y == null) return;

      const isRetrieval = link.type === "retrieval";
      const srcId = linkId(src);
      const tgtId = linkId(tgt);
      const isLit = accessed.has(srcId) || accessed.has(tgtId);
      const isSelected =
        selectedId != null && (srcId === selectedId || tgtId === selectedId);

      const alpha = linkAlpha(link, src, tgt);
      const width = Math.max(0.4, (isRetrieval ? 1.2 : isSelected ? 1 : 0.6) / globalScale);

      const { mx, my } = linkCurveControl(src, tgt, srcId, tgtId);

      ctx.save();
      ctx.lineCap = "round";
      ctx.globalAlpha = isLit ? Math.min(1, alpha * 2) : alpha;
      ctx.beginPath();
      ctx.moveTo(src.x, src.y);
      ctx.quadraticCurveTo(mx, my, tgt.x, tgt.y);
      ctx.strokeStyle = isRetrieval
        ? "rgba(196, 181, 253, 0.9)"
        : isLit
          ? "rgba(186, 176, 230, 0.65)"
          : "rgba(160, 162, 170, 0.8)";
      ctx.lineWidth = width;
      if (isRetrieval) ctx.setLineDash([4 / globalScale, 3 / globalScale]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    },
    [accessed, selectedId],
  );

  return (
    <div className={`graph-wrap ${settling ? "graph-settling" : "graph-ready"}`}>
      {settling && <div className="graph-settle-hint">Arranging knowledge graph…</div>}
      <ForceGraph2D
        ref={fgRef}
        graphData={data}
        backgroundColor="#141416"
        nodeRelSize={1}
        linkCanvasObject={paintLink}
        linkCanvasObjectMode={() => "replace"}
        linkDirectionalParticles={(link) => (link.type === "retrieval" ? 2 : 0)}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleSpeed={0.003}
        linkDirectionalParticleColor={() => "#e9d5ff"}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => "replace"}
        nodePointerAreaPaint={(node, color, ctx) => {
          const r = collisionRadius(node);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);
          ctx.fill();
        }}
        onNodeClick={(node) => {
          const id = (node as FGNode).id;
          const full = graph.nodes.find((n) => n.id === id) ?? (node as GraphNode);
          onSelect(full);
        }}
        onNodeHover={(node) => setHoveredId(node ? (node as FGNode).id : null)}
        onBackgroundClick={() => onSelect(null)}
        onNodeDragEnd={handleNodeDragEnd}
        onEngineStop={handleEngineStop}
        cooldownTicks={220}
        warmupTicks={positionsRef.current.size > 0 ? 0 : 100}
        d3AlphaDecay={0.018}
        d3AlphaMin={0.002}
        d3VelocityDecay={0.52}
        enableNodeDrag
        enableZoomInteraction
        enablePanInteraction
      />
      <div className="graph-legend">
        <div className="legend-title">Graph</div>
        <div><span className="dot accessed" /> Accessed / retrieved</div>
        <div><span className="legend-line" /> Wikilink</div>
        <div className="legend-types">
          {TYPE_LEGEND.map(({ type, label }) => (
            <div key={type} className="legend-type-row">
              <span className="dot typed" style={{ background: colors[type] }} />
              {label}
            </div>
          ))}
        </div>
        <div className="legend-hint">Hover for label · scroll zoom · drag pan</div>
      </div>
    </div>
  );
}
