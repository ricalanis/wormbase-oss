/**
 * LineageProposalRow — single row in the /lake/lineage pending table.
 *
 * Displays src → tgt, confidence, strategy, and Confirm + Reject
 * buttons. The buttons are disabled for non-admins so the surface is
 * read-only for observers/members.
 *
 * **L4↦L3 reverse arc (Recipe Addendum #3, 2026-05-16)**: when
 * ``impactCount > 0``, the row renders a "↪ N impact proposals via
 * L4" badge linking to the /lake/schema-impact surface filtered by
 * the edge's ``upstream_lineage_edge_id``. The forward arc lives in
 * the worm-core agent-gateway construction wiring (L4's
 * LineageEdgeImpactStrategy reads L3's confirmed edges). The reverse
 * arc is read-only enrichment — no new ledger writes, no env knob;
 * renders nothing when ``impactCount`` is undefined or 0 (honest
 * empty state).
 */

"use client";

import type { LineageEdgeRow } from "../../lib/lineage";

export interface LineageProposalRowProps {
  edge: LineageEdgeRow;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (edge: LineageEdgeRow) => void;
  onReject: (edge: LineageEdgeRow) => void;
  /**
   * L4↦L3 reverse-arc enrichment (Recipe Addendum #3).
   *
   * Count of L4 schema-evolution impacts (state ∈ {proposed,
   * confirmed}) that carry this edge's ``edgeId`` as their
   * ``upstream_lineage_edge_id``. When > 0, the row renders an
   * "↪ N impact proposals via L4" badge. When 0 or undefined,
   * the row renders no badge (honest empty state).
   */
  impactCount?: number;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtTable(table: string, column: string | null): string {
  return column ? `${table} · ${column}` : table;
}

function buildLineageImpactsLink(edgeId: string): string {
  const params = new URLSearchParams();
  params.set("upstream_lineage_edge_id", edgeId);
  return `/lake/schema-impact?${params.toString()}`;
}

export function LineageProposalRow({
  edge,
  disabled,
  onConfirm,
  onReject,
  impactCount,
}: LineageProposalRowProps): JSX.Element {
  const showImpactBadge =
    typeof impactCount === "number" && impactCount > 0;
  return (
    <tr data-testid={`lineage-proposal-row-${edge.edgeId}`}>
      <td
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {fmtTable(edge.srcTableId, edge.srcColumn)}
          </code>
          {showImpactBadge ? (
            <a
              href={buildLineageImpactsLink(edge.edgeId)}
              data-testid={`lineage-proposal-impact-badge-${edge.edgeId}`}
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                color: "var(--wb-color-sepia-warning-deep, #b6741c)",
                textDecoration: "none",
                cursor: "pointer",
              }}
              title="View L4 schema-evolution-impact rows derived from this lineage edge"
            >
              {`↪ ${impactCount} impact proposal${
                impactCount === 1 ? "" : "s"
              } via L4`}
            </a>
          ) : null}
        </div>
      </td>
      <td
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <code className="wb-mono" style={{ fontSize: 11 }}>
          {fmtTable(edge.tgtTableId, edge.tgtColumn)}
        </code>
      </td>
      <td
        data-testid={`lineage-proposal-confidence-${edge.edgeId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(edge.confidence)}
      </td>
      <td
        data-testid={`lineage-proposal-strategy-${edge.edgeId}`}
        style={{
          padding: "8px 12px",
          fontSize: 11,
        }}
      >
        <code className="wb-mono">{edge.strategy}</code>
      </td>
      <td
        style={{
          padding: "8px 12px",
          textAlign: "right",
          display: "flex",
          gap: 6,
          justifyContent: "flex-end",
        }}
      >
        <button
          type="button"
          onClick={() => onConfirm(edge)}
          disabled={disabled}
          data-testid={`lineage-proposal-confirm-${edge.edgeId}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "5px 10px",
            border: "1px solid var(--wb-color-botanical-green-deep, #2d5d3a)",
            background: disabled
              ? "var(--wb-color-paper-deep, #f4eedb)"
              : "var(--wb-color-botanical-green-deep, #2d5d3a)",
            color: disabled
              ? "var(--wb-color-hash-gray, #7c7569)"
              : "var(--wb-color-paper, #f8f3e1)",
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => onReject(edge)}
          disabled={disabled}
          data-testid={`lineage-proposal-reject-${edge.edgeId}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "5px 10px",
            border: "1px solid var(--wb-color-aged-ink, #2a2620)",
            background: "var(--wb-color-paper, #f8f3e1)",
            color: disabled
              ? "var(--wb-color-hash-gray, #7c7569)"
              : "var(--wb-color-aged-ink, #2a2620)",
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          Reject
        </button>
      </td>
    </tr>
  );
}
