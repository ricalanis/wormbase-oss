"use client";
/**
 * KPI tree as an interactive React Flow graph (Step 3a of the canonical
 * 5-step product arc). Replaces the rustic indented list — the tree is
 * the demo's show-window for "the worm is building the KPI graph live."
 *
 * - Nodes: KpiNodeRow rows from getKpiTree(companyId), laid out depth-first
 *   into columns by depth and rows by the in-order traversal index. This is
 *   deterministic — same tree, same coordinates, same hash-stable visual.
 * - Edges: parent → child relationships, derived from the recursive
 *   `children` array. Confidence is encoded on the edge stroke (botanical
 *   green > 0.8, hash gray 0.4-0.8, sepia warning < 0.4) — same legend as
 *   the original list view, preserved for narrator continuity.
 * - Status palette: classification flips node fill — internal soft, pii
 *   sepia wash, public paper. Auditable governance shows up *visually*.
 * - Click a node → side panel: formula, source URIs, owner, classification,
 *   last receipt. The audience SEES the receipt without leaving the view.
 * - Live polling every 5s via usePoll → /api/kpi-tree/refresh. This is the
 *   "the worm feels alive" effect runbook authors quote.
 *
 * Field-Notebook tokens only. No new colors. No SaaS-pastel rounded chips.
 */
import { useCallback, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { KpiNodeRow } from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";
import { usePoll } from "../../lib/use-poll";

interface KpiNodeData extends Record<string, unknown> {
  row: KpiNodeRow;
  depth: number;
}

const X_STEP = 240;
const Y_STEP = 88;

/**
 * Lay out the tree deterministically. We walk depth-first, assigning each
 * leaf its own row, then back-propagating parent rows as the average of
 * their children. The shape is identical between renders — important for
 * the demo because audience eye-track stays anchored as new nodes append.
 */
function layoutTree(root: KpiNodeRow): {
  nodes: Node<KpiNodeData>[];
  edges: Edge[];
} {
  const nodes: Node<KpiNodeData>[] = [];
  const edges: Edge[] = [];
  let nextLeafRow = 0;

  function visit(n: KpiNodeRow, depth: number, parentId: string | null): number {
    let row: number;
    if (n.children.length === 0) {
      row = nextLeafRow++;
    } else {
      const childRows = n.children.map((c) => visit(c, depth + 1, n.id));
      row = childRows.reduce((a, b) => a + b, 0) / childRows.length;
    }
    nodes.push({
      id: n.id,
      type: "kpi",
      position: { x: depth * X_STEP, y: row * Y_STEP },
      data: { row: n, depth },
      // Hide handles for the root — purely visual cleanliness.
      draggable: false,
      selectable: true,
    });
    if (parentId) {
      edges.push(edgeFor(parentId, n));
    }
    return row;
  }

  visit(root, 0, null);
  return { nodes, edges };
}

function edgeFor(parentId: string, child: KpiNodeRow): Edge {
  const conf = child.confidence;
  const stroke =
    conf > 0.8
      ? "var(--wb-color-botanical-green)"
      : conf > 0.4
        ? "var(--wb-color-hash-gray)"
        : "var(--wb-color-sepia-warning)";
  return {
    id: `${parentId}-${child.id}`,
    source: parentId,
    target: child.id,
    style: { stroke, strokeWidth: 1.2 },
    animated: false,
  };
}

/**
 * Custom node renderer. Square corners, 1px aged-ink border, classification
 * wash. The receipt hash sits on the bottom of every card — receipts as a
 * first-class visual unit.
 */
function KpiFlowNode({ data }: NodeProps<Node<KpiNodeData>>) {
  const { row } = data;
  const conf = row.confidence;
  const confTier = conf > 0.8 ? "high" : conf > 0.4 ? "mid" : "low";
  const accent =
    confTier === "high"
      ? "var(--wb-color-botanical-green)"
      : confTier === "mid"
        ? "var(--wb-color-hash-gray)"
        : "var(--wb-color-sepia-warning)";
  const fill =
    row.classification === "pii" || row.classification === "restricted"
      ? "var(--wb-color-sepia-warning-soft)"
      : row.classification === "public"
        ? "var(--wb-color-paper)"
        : "var(--wb-color-paper-deep)";

  return (
    <div
      data-testid={`kpi-flow-node-${row.id}`}
      data-conf={confTier}
      data-classification={row.classification}
      style={{
        minWidth: 200,
        maxWidth: 220,
        padding: "8px 12px",
        background: fill,
        border: `1px solid var(--wb-color-aged-ink)`,
        borderLeft: `3px solid ${accent}`,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "var(--wb-color-aged-ink)", width: 6, height: 6 }}
      />
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
          fontWeight: 500,
          color: "var(--wb-color-aged-ink)",
          lineHeight: 1.2,
        }}
      >
        {row.label}
      </span>
      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.08em",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        conf {conf.toFixed(2)} · {row.classification}
      </span>
      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        #{row.receipt.hash.slice(0, 8)}
      </span>
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "var(--wb-color-aged-ink)", width: 6, height: 6 }}
      />
    </div>
  );
}

const NODE_TYPES = { kpi: KpiFlowNode };

export function KpiTreeView({ initial }: { initial: KpiNodeRow }) {
  const [selected, setSelected] = useState<KpiNodeRow | null>(null);

  // Live polling — the "the worm feels alive" effect. 5s cadence. Falls back
  // to the SSR initial snapshot when /api/kpi-tree/refresh fails.
  const { data, lastTickAt } = usePoll<{ root: KpiNodeRow } | undefined>(
    async () => {
      const res = await fetch("/api/kpi-tree/refresh", { cache: "no-store" });
      if (!res.ok) throw new Error(`refresh failed: ${res.status}`);
      const j = (await res.json()) as { root: KpiNodeRow };
      return { root: j.root };
    },
    { intervalMs: 5_000, initial: { root: initial } },
  );

  const root = data?.root ?? initial;
  const { nodes, edges } = useMemo(() => layoutTree(root), [root]);

  const onNodeClick: NodeMouseHandler = useCallback((_, n) => {
    const d = n.data as KpiNodeData;
    setSelected(d.row);
  }, []);

  const livenessLabel = lastTickAt
    ? `live · ${Math.max(1, Math.round((Date.now() - lastTickAt) / 1000))}s ago`
    : "live · connecting…";

  return (
    <div
      data-testid="kpi-tree-view"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) 320px",
        gap: 16,
        height: 560,
      }}
    >
      <div
        style={{
          position: "relative",
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper)",
        }}
      >
        <span
          className="wb-mono"
          data-testid="kpi-tree-liveness"
          style={{
            position: "absolute",
            top: 8,
            right: 12,
            zIndex: 10,
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-botanical-green-deep)",
          }}
        >
          {livenessLabel}
        </span>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          onNodeClick={onNodeClick}
          minZoom={0.4}
          maxZoom={1.6}
        >
          <Background
            color="var(--wb-color-paper-edge)"
            gap={24}
            size={1}
          />
          <Controls
            showInteractive={false}
            style={{
              background: "var(--wb-color-paper-deep)",
              border: "1px solid var(--wb-color-paper-edge)",
            }}
          />
        </ReactFlow>
      </div>
      <KpiSidePanel node={selected} />
    </div>
  );
}

function KpiSidePanel({ node }: { node: KpiNodeRow | null }) {
  if (!node) {
    return (
      <aside
        data-testid="kpi-side-panel"
        style={{
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper)",
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          KPI · detail
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
            lineHeight: 1.5,
          }}
        >
          Click any node to see its formula, sources, owner, and receipt.
        </p>
      </aside>
    );
  }
  return (
    <aside
      data-testid="kpi-side-panel"
      data-selected-id={node.id}
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        KPI · {node.id}
      </span>
      <h3
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 22,
          fontWeight: 500,
        }}
      >
        {node.label}
      </h3>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          rowGap: 6,
          columnGap: 10,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
          color: "var(--wb-color-aged-ink-soft)",
        }}
      >
        <dt
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          owner
        </dt>
        <dd style={{ margin: 0 }}>@{node.owner}</dd>
        <dt
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          confidence
        </dt>
        <dd style={{ margin: 0 }}>{node.confidence.toFixed(2)}</dd>
        <dt
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          source
        </dt>
        <dd
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            wordBreak: "break-all",
          }}
        >
          {node.receipt.source}
        </dd>
        <dt
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          status
        </dt>
        <dd style={{ margin: 0 }}>
          {node.children.length === 0 ? "leaf" : `parent of ${node.children.length}`}
        </dd>
      </dl>
      <Receipt
        hash={node.receipt.hash}
        source={node.receipt.source}
        owner={node.receipt.owner}
        classification={node.receipt.classification}
      />
    </aside>
  );
}
