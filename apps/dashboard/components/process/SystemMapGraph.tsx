"use client";

/**
 * System map — Step 3c, /system-map surface.
 *
 * Tiny SVG force-suggested layout: persons + channels arranged on a
 * concentric ring (persons inner, channels outer); edges drawn with
 * thickness proportional to message count. Avoids a graph library so the
 * server-render path stays deterministic and test-friendly.
 */

import { useMemo } from "react";
import type {
  SystemMapNode,
  SystemMapPayload,
} from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";
import { EmptyState } from "../chrome/EmptyState";

export interface SystemMapGraphProps {
  payload: SystemMapPayload;
  width?: number;
  height?: number;
}

interface Layout {
  nodeId: string;
  nodeKind: SystemMapNode["nodeKind"];
  x: number;
  y: number;
  label: string;
}

export function SystemMapGraph({
  payload,
  width = 720,
  height = 540,
}: SystemMapGraphProps) {
  const { nodes, layout, edges } = useMemo(() => {
    const nodes = payload.nodes;
    const persons = nodes.filter((n) => n.nodeKind === "person");
    const channels = nodes.filter((n) => n.nodeKind === "channel");
    const others = nodes.filter(
      (n) => n.nodeKind !== "person" && n.nodeKind !== "channel"
    );
    const cx = width / 2;
    const cy = height / 2;
    const personRadius = Math.min(width, height) * 0.18;
    const channelRadius = Math.min(width, height) * 0.36;
    const otherRadius = Math.min(width, height) * 0.46;

    const layout: Layout[] = [];
    persons.forEach((n, i) => {
      const angle = (i / Math.max(1, persons.length)) * Math.PI * 2;
      layout.push({
        nodeId: n.nodeId,
        nodeKind: n.nodeKind,
        x: cx + Math.cos(angle) * personRadius,
        y: cy + Math.sin(angle) * personRadius,
        label: shortenPersonId(n.nodeId),
      });
    });
    channels.forEach((n, i) => {
      const angle = (i / Math.max(1, channels.length)) * Math.PI * 2 + Math.PI / 6;
      layout.push({
        nodeId: n.nodeId,
        nodeKind: n.nodeKind,
        x: cx + Math.cos(angle) * channelRadius,
        y: cy + Math.sin(angle) * channelRadius,
        label: n.nodeId,
      });
    });
    others.forEach((n, i) => {
      const angle = (i / Math.max(1, others.length)) * Math.PI * 2;
      layout.push({
        nodeId: n.nodeId,
        nodeKind: n.nodeKind,
        x: cx + Math.cos(angle) * otherRadius,
        y: cy + Math.sin(angle) * otherRadius,
        label: n.nodeId,
      });
    });

    const layoutById = new Map<string, Layout>();
    for (const l of layout) layoutById.set(`${l.nodeKind}:${l.nodeId}`, l);

    // Build edges. Source is always layout[i]; target is resolved by trying
    // `person:<id>` then `channel:<id>` then `<kind>:<id>` fallthroughs.
    const edges: Array<{
      id: string;
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      weight: number;
      kind: string;
    }> = [];
    const maxWeight = Math.max(
      1,
      ...nodes.flatMap((n) => n.edges.map((e) => e.weight))
    );
    for (const n of nodes) {
      const src = layoutById.get(`${n.nodeKind}:${n.nodeId}`);
      if (!src) continue;
      for (const e of n.edges) {
        const candidates = [
          `person:${e.targetId}`,
          `channel:${e.targetId}`,
          `role:${e.targetId}`,
        ];
        let dst: Layout | undefined;
        for (const c of candidates) {
          const found = layoutById.get(c);
          if (found) {
            dst = found;
            break;
          }
        }
        if (!dst) continue;
        edges.push({
          id: `${n.nodeId}-${e.kind}-${e.targetId}`,
          x1: src.x,
          y1: src.y,
          x2: dst.x,
          y2: dst.y,
          weight: e.weight / maxWeight,
          kind: e.kind,
        });
      }
    }
    return { nodes, layout, edges };
  }, [payload, width, height]);

  if (nodes.length === 0) {
    return (
      <EmptyState
        testId="system-map-empty"
        eyebrow="no system map yet"
        title="The who-asks-whom-what graph builds itself as your team chats."
        description={
          "Persons + channels appear as nodes; edges grow as the worm watches " +
          "messages, mentions, and replies. Drop the worm into more channels " +
          "to grow the graph — the first edges typically appear within an " +
          "hour of the first wire event. Check back tomorrow for the full " +
          "shape of who talks to whom."
        }
        cta={{ label: "Drop the worm into more channels", href: "/channels" }}
        secondaryCta={{ label: "See raw conversations", href: "/activity" }}
      />
    );
  }

  return (
    <div data-testid="system-map">
      <svg
        role="img"
        aria-label="System map: persons and channels graph"
        data-testid="system-map-svg"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{
          background: "var(--wb-color-paper-deep)",
          border: "1px solid var(--wb-color-paper-edge)",
        }}
      >
        {edges.map((e) => (
          <line
            key={e.id}
            data-testid={`edge-${e.id}`}
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            stroke="var(--wb-color-botanical-green)"
            strokeOpacity={0.4 + e.weight * 0.6}
            strokeWidth={1 + e.weight * 3}
          />
        ))}
        {layout.map((l) => (
          <g
            key={`${l.nodeKind}:${l.nodeId}`}
            data-testid={`node-${l.nodeKind}-${l.nodeId}`}
          >
            <circle
              cx={l.x}
              cy={l.y}
              r={l.nodeKind === "channel" ? 14 : 10}
              fill={
                l.nodeKind === "channel"
                  ? "var(--wb-color-paper)"
                  : "var(--wb-color-botanical-green)"
              }
              stroke="var(--wb-color-aged-ink)"
              strokeWidth={1.5}
            />
            <text
              x={l.x + 16}
              y={l.y + 4}
              style={{
                fontFamily:
                  l.nodeKind === "channel"
                    ? "var(--wb-font-mono)"
                    : "var(--wb-font-serif)",
                fontSize: 11,
                fill: "var(--wb-color-aged-ink)",
              }}
            >
              {l.label}
            </text>
          </g>
        ))}
      </svg>
      <div
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          paddingTop: 16,
        }}
      >
        {nodes.slice(0, 8).map((n) => (
          <span
            key={`${n.nodeKind}:${n.nodeId}`}
            data-testid={`legend-${n.nodeKind}-${n.nodeId}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "4px 8px",
              border: "1px solid var(--wb-color-paper-edge)",
            }}
          >
            <span className="wb-mono" style={{ fontSize: 10 }}>
              {n.nodeKind}: {shortenPersonId(n.nodeId)}
            </span>
            <Receipt
              hash={n.receipt.hash}
              source={n.receipt.source}
              owner={n.receipt.owner}
              classification={n.receipt.classification}
              compact
            />
          </span>
        ))}
      </div>
    </div>
  );
}

function shortenPersonId(id: string): string {
  if (id.length <= 12) return id;
  return id.replace(/-/g, "").slice(0, 8);
}
