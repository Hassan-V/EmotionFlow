"use client";

import { useMemo, useState, useRef, useCallback } from "react";
import { emotionColor } from "@/lib/utils";
import type { EmotionShift, EmotionTransition } from "@/lib/types";

/* ─── Props ─────────────────────────────────────────────────────── */
interface Props {
  timeline: EmotionShift[];
  transitions?: EmotionTransition[];
  summary?: string;
}

/* ─── Internal types ────────────────────────────────────────────── */
interface GNode {
  id: string;
  count: number;
  avgIntensity: number;
  x: number;
  y: number;
  r: number;
  color: string;
}
interface GEdge {
  id: string;
  from: string;
  to: string;
  count: number;
  explanations: string[];
  color: string;
  width: number;
}

/* ─── Constants ─────────────────────────────────────────────────── */
const W = 720;
const H = 440;
const CX = W / 2;
const CY = 210;
const LAYOUT_R = 150;
const NODE_MIN = 24;
const NODE_MAX = 52;
const EDGE_MIN = 1.5;
const EDGE_MAX = 6;

/* ─── Helpers ───────────────────────────────────────────────────── */
/** Perpendicular-offset control point for a quadratic bezier */
function ctrlPt(
  x1: number, y1: number, x2: number, y2: number, off: number,
): [number, number] {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  return [mx + (-dy / len) * off, my + (dx / len) * off];
}

/** Shorten a line segment so the arrow doesn't overlap the node */
function trimEnd(
  x1: number, y1: number, x2: number, y2: number, trimBy: number,
): [number, number] {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  return [x2 - (dx / len) * trimBy, y2 - (dy / len) * trimBy];
}

/* ─── Component ─────────────────────────────────────────────────── */
export function CausalityGraph({ timeline, transitions, summary }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number; y: number; lines: string[];
  } | null>(null);

  /* ── Build graph data ───────────────────────────────── */
  const { nodes, edges } = useMemo(() => {
    // 1. Aggregate emotions
    const emap = new Map<string, { count: number; totalI: number }>();
    for (const e of timeline) {
      const cur = emap.get(e.emotion) || { count: 0, totalI: 0 };
      cur.count++;
      cur.totalI += e.intensity;
      emap.set(e.emotion, cur);
    }

    // 2. Build nodes — circular layout
    const entries = Array.from(emap.entries()).sort((a, b) => b[1].count - a[1].count);
    const maxC = Math.max(...entries.map(([, d]) => d.count), 1);

    const nodes: GNode[] = entries.map(([emotion, data], i) => {
      const angle = (2 * Math.PI * i) / entries.length - Math.PI / 2;
      const t = data.count / maxC;
      const r = NODE_MIN + t * (NODE_MAX - NODE_MIN);
      return {
        id: emotion,
        count: data.count,
        avgIntensity: data.totalI / data.count,
        x: CX + LAYOUT_R * Math.cos(angle),
        y: CY + LAYOUT_R * Math.sin(angle),
        r,
        color: emotionColor(emotion),
      };
    });

    // For a single node, center it
    if (nodes.length === 1) {
      nodes[0].x = CX;
      nodes[0].y = CY;
    }
    // For two nodes, side by side
    if (nodes.length === 2) {
      nodes[0].x = CX - 120;
      nodes[0].y = CY;
      nodes[1].x = CX + 120;
      nodes[1].y = CY;
    }

    // 3. Build edges
    const edgeMap = new Map<string, { from: string; to: string; count: number; explanations: string[] }>();

    if (transitions && transitions.length > 0) {
      // Use local grounded transitions + infer from timeline
      for (const t of transitions) {
        if (t.from_emotion === t.to_emotion) continue;
        const key = `${t.from_emotion}->${t.to_emotion}`;
        const cur = edgeMap.get(key) || { from: t.from_emotion, to: t.to_emotion, count: 0, explanations: [] };
        cur.count++;
        if (t.explanation) cur.explanations.push(t.explanation);
        edgeMap.set(key, cur);
      }
    } else {
      // Infer from consecutive timeline entries
      for (let i = 1; i < timeline.length; i++) {
        const from = timeline[i - 1].emotion;
        const to = timeline[i].emotion;
        if (from === to) continue;
        const key = `${from}->${to}`;
        const cur = edgeMap.get(key) || { from, to, count: 0, explanations: [] };
        cur.count++;
        edgeMap.set(key, cur);
      }
    }

    const maxE = Math.max(...Array.from(edgeMap.values()).map((e) => e.count), 1);
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    const edges: GEdge[] = Array.from(edgeMap.entries())
      .filter(([, d]) => nodeMap.has(d.from) && nodeMap.has(d.to))
      .map(([key, d]) => ({
        id: key,
        from: d.from,
        to: d.to,
        count: d.count,
        explanations: d.explanations,
        color: nodeMap.get(d.from)!.color,
        width: EDGE_MIN + (d.count / maxE) * (EDGE_MAX - EDGE_MIN),
      }));

    return { nodes, edges };
  }, [timeline, transitions]);

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  /* ── Check for bidirectional edges ─────────────────── */
  const biKeys = useMemo(() => {
    const set = new Set<string>();
    const keys = new Set(edges.map((e) => e.id));
    for (const e of edges) {
      const rev = `${e.to}->${e.from}`;
      if (keys.has(rev)) set.add(e.id);
    }
    return set;
  }, [edges]);

  /* ── Interaction helpers ────────────────────────────── */
  const showTooltip = useCallback(
    (e: React.MouseEvent<SVGElement>, lines: string[]) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      setTooltip({
        x: e.clientX - rect.left + 12,
        y: e.clientY - rect.top - 8,
        lines,
      });
    },
    [],
  );
  const hideTooltip = useCallback(() => setTooltip(null), []);

  /* ── Edge path builder ─────────────────────────────── */
  function edgePath(edge: GEdge) {
    const nFrom = nodeMap.get(edge.from)!;
    const nTo = nodeMap.get(edge.to)!;
    const isBi = biKeys.has(edge.id);
    const offset = isBi ? 40 : 25;
    const [cx, cy] = ctrlPt(nFrom.x, nFrom.y, nTo.x, nTo.y, offset);
    // Trim the end so the arrowhead sits on the node border
    const [tx, ty] = trimEnd(cx, cy, nTo.x, nTo.y, nTo.r + 6);
    return `M ${nFrom.x} ${nFrom.y} Q ${cx} ${cy} ${tx} ${ty}`;
  }

  /* ── Dim logic ─────────────────────────────────────── */
  function nodeOpacity(id: string) {
    if (!hovered) return 1;
    if (hovered === id) return 1;
    // connected?
    for (const e of edges) {
      if ((e.from === hovered && e.to === id) || (e.to === hovered && e.from === id)) return 1;
    }
    return 0.2;
  }
  function edgeOpacity(edge: GEdge) {
    if (!hovered) return 0.7;
    if (edge.from === hovered || edge.to === hovered) return 1;
    return 0.1;
  }

  /* ── Unique colors for arrow markers ───────────────── */
  const markerColors = useMemo(
    () => Array.from(new Set(edges.map((e) => e.color))),
    [edges],
  );

  if (nodes.length === 0) return null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ maxHeight: 460 }}
      >
        {/* ── Defs ────────────────────────────────── */}
        <defs>
          {/* Glow filter */}
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Per-color arrowheads */}
          {markerColors.map((c) => (
            <marker
              key={c}
              id={`ah-${c.replace("#", "")}`}
              markerWidth="10"
              markerHeight="8"
              refX="9"
              refY="4"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <polygon points="0 0,10 4,0 8" fill={c} opacity={0.9} />
            </marker>
          ))}
        </defs>

        {/* ── Edges ───────────────────────────────── */}
        {edges.map((edge) => (
          <g key={edge.id}>
            {/* Animated dash background */}
            <path
              d={edgePath(edge)}
              fill="none"
              stroke={edge.color}
              strokeWidth={edge.width}
              strokeOpacity={edgeOpacity(edge) * 0.25}
              strokeDasharray="6 4"
              strokeLinecap="round"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="0"
                to="-20"
                dur="1.5s"
                repeatCount="indefinite"
              />
            </path>
            {/* Solid edge */}
            <path
              d={edgePath(edge)}
              fill="none"
              stroke={edge.color}
              strokeWidth={edge.width}
              strokeOpacity={edgeOpacity(edge)}
              strokeLinecap="round"
              markerEnd={`url(#ah-${edge.color.replace("#", "")})`}
              className="cursor-pointer"
              onMouseEnter={(e) => {
                setHovered(edge.from);
                const lines = [
                  `${edge.from} → ${edge.to}  (×${edge.count})`,
                  ...edge.explanations.slice(0, 2),
                ];
                showTooltip(e, lines);
              }}
              onMouseLeave={() => {
                setHovered(null);
                hideTooltip();
              }}
            />
            {/* Edge count label at midpoint */}
            {edge.count > 1 && (() => {
              const nF = nodeMap.get(edge.from)!;
              const nT = nodeMap.get(edge.to)!;
              const isBi = biKeys.has(edge.id);
              const off = isBi ? 40 : 25;
              const [cx, cy] = ctrlPt(nF.x, nF.y, nT.x, nT.y, off);
              // Point on the bezier at t=0.5
              const mx = 0.25 * nF.x + 0.5 * cx + 0.25 * nT.x;
              const my = 0.25 * nF.y + 0.5 * cy + 0.25 * nT.y;
              return (
                <text
                  x={mx}
                  y={my - 6}
                  textAnchor="middle"
                  className="text-[10px] fill-zinc-400 pointer-events-none select-none"
                >
                  ×{edge.count}
                </text>
              );
            })()}
          </g>
        ))}

        {/* ── Nodes ───────────────────────────────── */}
        {nodes.map((node) => {
          const circ = 2 * Math.PI * (node.r + 4);
          const dash = node.avgIntensity * circ;
          const op = nodeOpacity(node.id);
          return (
            <g
              key={node.id}
              opacity={op}
              className="cursor-pointer transition-opacity duration-200"
              onMouseEnter={(e) => {
                setHovered(node.id);
                showTooltip(e, [
                  `${node.id} — ${node.count} segment${node.count > 1 ? "s" : ""}`,
                  `Avg intensity: ${(node.avgIntensity * 100).toFixed(0)}%`,
                ]);
              }}
              onMouseLeave={() => {
                setHovered(null);
                hideTooltip();
              }}
            >
              {/* Outer glow */}
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r + 8}
                fill={node.color}
                opacity={0.08}
              />
              {/* Background fill */}
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r}
                fill={node.color}
                opacity={0.15}
                stroke={node.color}
                strokeWidth={2}
                strokeOpacity={0.4}
              />
              {/* Intensity arc ring */}
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r + 4}
                fill="none"
                stroke={node.color}
                strokeWidth={3}
                strokeDasharray={`${dash} ${circ - dash}`}
                strokeDashoffset={circ / 4}
                strokeLinecap="round"
                opacity={0.85}
              />
              {/* Label */}
              <text
                x={node.x}
                y={node.y - 4}
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[11px] font-semibold fill-zinc-100 select-none pointer-events-none"
              >
                {node.id}
              </text>
              {/* Count below label */}
              <text
                x={node.x}
                y={node.y + 12}
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[10px] fill-zinc-400 select-none pointer-events-none"
              >
                {node.count}×
              </text>
            </g>
          );
        })}

        {/* ── Legend row ──────────────────────────── */}
        {(() => {
          const cols = Math.min(nodes.length, 6);
          const spacing = W / (cols + 1);
          const yBase = H - 30;
          return nodes.slice(0, 12).map((n, i) => {
            const row = Math.floor(i / cols);
            const col = i % cols;
            const lx = spacing * (col + 1);
            const ly = yBase + row * 20;
            return (
              <g key={`leg-${n.id}`}>
                <circle cx={lx - 10} cy={ly} r={5} fill={n.color} opacity={0.8} />
                <text
                  x={lx}
                  y={ly}
                  dominantBaseline="central"
                  className="text-[10px] fill-zinc-400 select-none"
                >
                  {n.id} ({(n.avgIntensity * 100).toFixed(0)}%)
                </text>
              </g>
            );
          });
        })()}
      </svg>

      {/* ── Tooltip overlay ──────────────────────── */}
      {tooltip && (
        <div
          className="absolute pointer-events-none z-10 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl max-w-xs"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.lines.map((line, i) => (
            <p
              key={i}
              className={i === 0 ? "text-xs font-semibold text-zinc-200" : "text-xs text-zinc-400 mt-0.5"}
            >
              {line}
            </p>
          ))}
        </div>
      )}

      {/* ── Local summary ────────────────────────── */}
      {summary && (
        <p className="text-sm text-zinc-400 mt-3 px-2 italic leading-relaxed">
          {summary}
        </p>
      )}
    </div>
  );
}
