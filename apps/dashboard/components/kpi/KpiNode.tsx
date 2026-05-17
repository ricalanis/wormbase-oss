"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { KpiNodeRow } from "../../lib/ledger-client.types";

export function KpiNode({
  node,
  depth = 0,
  defaultExpanded = false,
}: {
  node: KpiNodeRow;
  depth?: number;
  defaultExpanded?: boolean;
}) {
  // Tree opens to depth 2 by default so the demo shows 7+ nodes immediately
  // without an interaction. Deeper subtrees fold; user expands.
  const [expanded, setExpanded] = useState(defaultExpanded || depth < 2);
  const hasChildren = node.hasChildren && node.children.length > 0;

  const conf = node.confidence;
  const confTier = conf > 0.8 ? "high" : conf > 0.4 ? "mid" : "low";
  const edgeColor =
    confTier === "high"
      ? "var(--wb-color-botanical-green)"
      : confTier === "mid"
        ? "var(--wb-color-hash-gray)"
        : "var(--wb-color-sepia-warning)";

  return (
    <li
      data-testid={`kpi-node-${node.id}`}
      data-conf={confTier}
      style={{ listStyle: "none" }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "20px 1fr auto",
          alignItems: "center",
          gap: 12,
          padding: "8px 0",
          borderLeft: `1px solid ${edgeColor}`,
          paddingLeft: 12 + depth * 20,
        }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? `Collapse ${node.label}` : `Expand ${node.label}`}
            data-testid={`kpi-toggle-${node.id}`}
            className="wb-mono"
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
              padding: 0,
              width: 16,
            }}
          >
            {expanded ? "[−]" : "[+]"}
          </button>
        ) : (
          <span aria-hidden="true" />
        )}
        <span
          style={{
            display: "inline-flex",
            alignItems: "baseline",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 16,
              fontWeight: 500,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {node.label}
          </span>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            confidence {conf.toFixed(2)}
          </span>
        </span>
        <span style={{ minWidth: 280 }}>
          <Receipt
            hash={node.receipt.hash}
            source={node.receipt.source}
            owner={node.receipt.owner}
            classification={node.receipt.classification}
            compact
          />
        </span>
      </div>
      {expanded && hasChildren ? (
        <ul style={{ padding: 0, margin: 0 }}>
          {node.children.map((c) => (
            <KpiNode key={c.id} node={c} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
