/**
 * LineageGraphView — basic SVG graph for confirmed lineage edges.
 *
 * Renders nodes (catalog tables) as paper-stamp rectangles + edges
 * (confirmed lineage) as directed arrows. Layout uses a column-by-rank
 * heuristic (Sugiyama-lite): each node's column is its depth from a
 * source node (no upstream edges); ties broken by lexicographic order.
 *
 * Click an edge → expands the evidence panel with confirmation
 * metadata + a future "revoke" action (not wired in Sub-wave D —
 * revoke is forward-only via a new ledger entry and lives in a
 * subsequent wave).
 *
 * Constraints: <300 LOC per the orchestration brief. We render a
 * single-column fallback layout when the graph is too dense (>40
 * nodes), and degrade to a tabular view when SVG layout would crowd.
 */

"use client";

import { useMemo, useState } from "react";

import type { LineageEdgeRow } from "../../lib/lineage";

export interface LineageGraphViewProps {
  rows: LineageEdgeRow[];
}

interface NodeLayout {
  id: string;
  label: string;
  col: number;
  row: number;
  x: number;
  y: number;
}

interface EdgeLayout {
  edgeId: string;
  fromId: string;
  toId: string;
  edge: LineageEdgeRow;
}

const NODE_W = 168;
const NODE_H = 38;
const COL_GAP = 80;
const ROW_GAP = 18;
const PADDING = 24;

function shortLabel(id: string, column: string | null): string {
  const trimmed = id.length > 24 ? `${id.slice(0, 22)}…` : id;
  if (!column) return trimmed;
  const trimmedCol = column.length > 14 ? `${column.slice(0, 12)}…` : column;
  return `${trimmed} · ${trimmedCol}`;
}

function buildLayout(rows: LineageEdgeRow[]): {
  nodes: NodeLayout[];
  edges: EdgeLayout[];
  width: number;
  height: number;
} {
  const nodeMap = new Map<string, { id: string; label: string }>();
  const upstreamCount = new Map<string, number>();
  const downstream = new Map<string, string[]>();
  const edgeList: { fromId: string; toId: string; edge: LineageEdgeRow }[] = [];

  for (const row of rows) {
    const srcKey = `${row.srcTableId}::${row.srcColumn ?? ""}`;
    const tgtKey = `${row.tgtTableId}::${row.tgtColumn ?? ""}`;
    if (!nodeMap.has(srcKey)) {
      nodeMap.set(srcKey, {
        id: srcKey,
        label: shortLabel(row.srcTableId, row.srcColumn),
      });
    }
    if (!nodeMap.has(tgtKey)) {
      nodeMap.set(tgtKey, {
        id: tgtKey,
        label: shortLabel(row.tgtTableId, row.tgtColumn),
      });
    }
    upstreamCount.set(tgtKey, (upstreamCount.get(tgtKey) ?? 0) + 1);
    upstreamCount.set(srcKey, upstreamCount.get(srcKey) ?? 0);
    const ds = downstream.get(srcKey) ?? [];
    ds.push(tgtKey);
    downstream.set(srcKey, ds);
    edgeList.push({ fromId: srcKey, toId: tgtKey, edge: row });
  }

  // Compute column = longest path from any root via BFS.
  const col = new Map<string, number>();
  const order: string[] = [];
  const queue: string[] = [];
  for (const [k, count] of upstreamCount.entries()) {
    if (count === 0) {
      col.set(k, 0);
      queue.push(k);
    }
  }
  // Stable seed-order for determinism.
  queue.sort();
  while (queue.length > 0) {
    const k = queue.shift() as string;
    if (!order.includes(k)) order.push(k);
    const c = col.get(k) ?? 0;
    const ds = (downstream.get(k) ?? []).sort();
    for (const next of ds) {
      const cand = c + 1;
      if (!col.has(next) || (col.get(next) as number) < cand) {
        col.set(next, cand);
        queue.push(next);
      }
    }
  }
  // Nodes with cycles or unreachable from roots — pin to column 0.
  for (const k of nodeMap.keys()) {
    if (!col.has(k)) col.set(k, 0);
  }

  // Group by column then assign row index.
  const byCol = new Map<number, string[]>();
  for (const [k, c] of col.entries()) {
    const arr = byCol.get(c) ?? [];
    arr.push(k);
    byCol.set(c, arr);
  }
  for (const arr of byCol.values()) arr.sort();

  const nodes: NodeLayout[] = [];
  let maxCol = 0;
  let maxRow = 0;
  for (const [c, arr] of byCol.entries()) {
    if (c > maxCol) maxCol = c;
    for (let i = 0; i < arr.length; i++) {
      if (i > maxRow) maxRow = i;
      const entry = nodeMap.get(arr[i]) as { id: string; label: string };
      nodes.push({
        id: entry.id,
        label: entry.label,
        col: c,
        row: i,
        x: PADDING + c * (NODE_W + COL_GAP),
        y: PADDING + i * (NODE_H + ROW_GAP),
      });
    }
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const edges: EdgeLayout[] = edgeList.map((e, i) => ({
    edgeId: e.edge.edgeId || `edge-${i}`,
    fromId: e.fromId,
    toId: e.toId,
    edge: e.edge,
  })).filter((e) => nodeById.has(e.fromId) && nodeById.has(e.toId));

  const width = PADDING * 2 + (maxCol + 1) * NODE_W + maxCol * COL_GAP;
  const height = PADDING * 2 + (maxRow + 1) * NODE_H + maxRow * ROW_GAP;
  return { nodes, edges, width: Math.max(width, 320), height: Math.max(height, 180) };
}

export function LineageGraphView({
  rows,
}: LineageGraphViewProps): JSX.Element {
  const layout = useMemo(() => buildLayout(rows), [rows]);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const nodeById = new Map(layout.nodes.map((n) => [n.id, n]));
  const selectedEdge =
    layout.edges.find((e) => e.edgeId === selectedEdgeId)?.edge ?? null;

  // Dense graph → tabular fallback (>40 nodes).
  if (layout.nodes.length > 40) {
    return (
      <section
        data-testid="lineage-graph-table-fallback"
        style={{ display: "flex", flexDirection: "column", gap: 6 }}
      >
        <p
          className="wb-mono"
          style={{
            margin: 0,
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          Tabular fallback · {layout.nodes.length} nodes
        </p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {layout.edges.map((e) => (
              <tr key={e.edgeId}>
                <td style={{ padding: 4 }}>
                  <code className="wb-mono" style={{ fontSize: 11 }}>
                    {nodeById.get(e.fromId)?.label}
                  </code>
                </td>
                <td style={{ padding: 4 }}>→</td>
                <td style={{ padding: 4 }}>
                  <code className="wb-mono" style={{ fontSize: 11 }}>
                    {nodeById.get(e.toId)?.label}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  return (
    <section
      data-testid="lineage-graph-view"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label="Confirmed lineage edges graph"
        style={{
          width: "100%",
          maxHeight: 480,
          border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          background: "var(--wb-color-paper, #f8f3e1)",
        }}
      >
        <defs>
          <marker
            id="arrowhead-lineage"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
            markerUnits="strokeWidth"
          >
            <path d="M0,0 L0,6 L9,3 z" fill="var(--wb-color-aged-ink, #2a2620)" />
          </marker>
        </defs>
        {layout.edges.map((e) => {
          const from = nodeById.get(e.fromId);
          const to = nodeById.get(e.toId);
          if (!from || !to) return null;
          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          const selected = selectedEdgeId === e.edgeId;
          return (
            <line
              key={e.edgeId}
              data-testid={`lineage-graph-edge-${e.edgeId}`}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={
                selected
                  ? "var(--wb-color-botanical-green-deep, #2d5d3a)"
                  : "var(--wb-color-aged-ink, #2a2620)"
              }
              strokeWidth={selected ? 2.5 : 1.5}
              markerEnd="url(#arrowhead-lineage)"
              style={{ cursor: "pointer" }}
              onClick={() =>
                setSelectedEdgeId((prev) =>
                  prev === e.edgeId ? null : e.edgeId,
                )
              }
            />
          );
        })}
        {layout.nodes.map((n) => (
          <g key={n.id} data-testid={`lineage-graph-node-${n.id}`}>
            <rect
              x={n.x}
              y={n.y}
              width={NODE_W}
              height={NODE_H}
              fill="var(--wb-color-paper-deep, #f4eedb)"
              stroke="var(--wb-color-aged-ink, #2a2620)"
              strokeWidth={1}
            />
            <text
              x={n.x + NODE_W / 2}
              y={n.y + NODE_H / 2 + 4}
              textAnchor="middle"
              fontSize={11}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill="var(--wb-color-aged-ink, #2a2620)"
            >
              {n.label}
            </text>
          </g>
        ))}
      </svg>
      {selectedEdge ? (
        <div
          data-testid="lineage-graph-evidence-panel"
          style={{
            border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 6,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Edge evidence · {selectedEdge.strategy} ·{" "}
            {(selectedEdge.confidence * 100).toFixed(0)}%
          </span>
          <div>
            <strong>edge_id:</strong>{" "}
            <code className="wb-mono" style={{ fontSize: 11 }}>
              {selectedEdge.edgeId}
            </code>
          </div>
          <div>
            <strong>reasoning:</strong> {selectedEdge.reasoning}
          </div>
          {Object.keys(selectedEdge.evidence).length > 0 ? (
            <pre
              className="wb-mono"
              style={{
                fontSize: 11,
                background: "var(--wb-color-paper, #f8f3e1)",
                border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
                padding: 8,
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              {JSON.stringify(selectedEdge.evidence, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
