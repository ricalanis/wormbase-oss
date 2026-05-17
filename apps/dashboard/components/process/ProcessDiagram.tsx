"use client";

/**
 * Process diagram — Step 3c, /processes surface.
 *
 * Renders one process map as a horizontal swimlane SVG (one row per actor,
 * boxes ordered left-to-right by step.order, arrows between consecutive
 * steps). No mermaid; no graph library — keeps the bundle thin and the
 * server-render path deterministic.
 */

import type { ProcessMapRow } from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";

export interface ProcessDiagramProps {
  process: ProcessMapRow;
}

const ROW_HEIGHT = 56;
const COL_WIDTH = 200;
const PADDING_X = 140;
const PADDING_Y = 32;
const BOX_WIDTH = 160;
const BOX_HEIGHT = 36;

export function ProcessDiagram({ process }: ProcessDiagramProps) {
  const actors = uniqueActors(process.steps);
  const stepCount = process.steps.length;
  const width =
    PADDING_X + Math.max(1, stepCount) * COL_WIDTH + 40;
  const height = PADDING_Y * 2 + Math.max(1, actors.length) * ROW_HEIGHT;

  const actorRow: Record<string, number> = {};
  actors.forEach((a, i) => {
    actorRow[a] = i;
  });

  // Compute positions for each step.
  const positioned = process.steps.map((s, i) => {
    const row = actorRow[s.actor] ?? 0;
    const x = PADDING_X + i * COL_WIDTH;
    const y = PADDING_Y + row * ROW_HEIGHT + (ROW_HEIGHT - BOX_HEIGHT) / 2;
    return { step: s, x, y };
  });

  return (
    <article
      data-testid={`process-${process.processId}`}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {process.domain} · confidence {(process.confidence * 100).toFixed(0)}%
          </span>
          <h2
            data-testid={`process-name-${process.processId}`}
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            {process.processName}
          </h2>
        </div>
        <Receipt
          hash={process.receipt.hash}
          source={process.receipt.source}
          owner={process.receipt.owner}
          classification={process.receipt.classification}
          compact
        />
      </header>
      <svg
        role="img"
        aria-label={`Process diagram for ${process.processName}`}
        data-testid={`process-svg-${process.processId}`}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{
          background: "var(--wb-color-paper-deep)",
          border: "1px solid var(--wb-color-paper-edge)",
        }}
      >
        <defs>
          <marker
            id="processArrow"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 Z" fill="var(--wb-color-botanical-green)" />
          </marker>
        </defs>

        {/* Swimlane labels + horizontal rules */}
        {actors.map((a, i) => {
          const y = PADDING_Y + i * ROW_HEIGHT + ROW_HEIGHT / 2;
          return (
            <g key={`lane-${a}`}>
              <text
                x={16}
                y={y + 4}
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  fill: "var(--wb-color-aged-ink)",
                }}
              >
                {a}
              </text>
              <line
                x1={PADDING_X - 12}
                x2={width - 16}
                y1={y}
                y2={y}
                stroke="var(--wb-color-paper-edge)"
                strokeDasharray="2 4"
              />
            </g>
          );
        })}

        {/* Edges */}
        {positioned.slice(0, -1).map((p, i) => {
          const next = positioned[i + 1];
          const startX = p.x + BOX_WIDTH;
          const startY = p.y + BOX_HEIGHT / 2;
          const endX = next.x;
          const endY = next.y + BOX_HEIGHT / 2;
          return (
            <path
              key={`edge-${i}`}
              d={`M ${startX} ${startY} C ${startX + 40} ${startY}, ${endX - 40} ${endY}, ${endX} ${endY}`}
              fill="none"
              stroke="var(--wb-color-botanical-green)"
              strokeWidth={1.5}
              markerEnd="url(#processArrow)"
            />
          );
        })}

        {/* Step boxes */}
        {positioned.map((p) => (
          <g key={`step-${p.step.order}`}>
            <rect
              x={p.x}
              y={p.y}
              width={BOX_WIDTH}
              height={BOX_HEIGHT}
              fill="var(--wb-color-paper)"
              stroke="var(--wb-color-aged-ink)"
              strokeWidth={1}
            />
            <text
              x={p.x + 12}
              y={p.y + 14}
              style={{
                fontFamily: "var(--wb-font-mono)",
                fontSize: 9,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                fill: "var(--wb-color-hash-gray)",
              }}
            >
              step {p.step.order}
            </text>
            <text
              x={p.x + 12}
              y={p.y + 28}
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 12,
                fill: "var(--wb-color-aged-ink)",
              }}
            >
              {truncate(p.step.action, 22)}
            </text>
          </g>
        ))}
      </svg>
    </article>
  );
}

function uniqueActors(steps: ProcessMapRow["steps"]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of steps) {
    if (s.actor && !seen.has(s.actor)) {
      seen.add(s.actor);
      out.push(s.actor);
    }
  }
  return out;
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}
