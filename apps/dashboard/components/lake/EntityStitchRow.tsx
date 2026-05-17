/**
 * EntityStitchRow — single row in the /lake/entity-stitches pending
 * table (L8 Sub-wave D, 2026-06-07).
 *
 * Renders ``src_a.col_a ↔ src_b.col_b``, the proposed entity_kind chip
 * (8 colors), confidence, the strategy that produced the proposal, and
 * Confirm + Reject buttons. The buttons are disabled for non-admins so
 * the surface is read-only for observers/members.
 *
 * Cross-axis link to L5 — third cross-axis dashboard navigation in the
 * lake stack (after L4→L3 in SchemaImpactRow and L6→L5 in
 * ColumnClassificationRow). When the stitch carries
 * ``upstreamSemanticTypeId`` (i.e. the NameMatch semantic-type-anchor
 * path produced this stitch by reading L5's projection through the
 * reused L6 ConfirmedSemanticTypeReader Protocol), the row renders a
 * small "view L5 semantic type" link to
 * ``/lake/semantic-types?type_id=<id>``. Same shape as the L6 row's
 * cross-axis link.
 */

"use client";

import type { EntityStitchRow as EntityStitchRowData } from "../../lib/entity-stitches";
import { EntityKindChip } from "./EntityKindChip";

export interface EntityStitchRowProps {
  proposal: EntityStitchRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (proposal: EntityStitchRowData) => void;
  onReject: (proposal: EntityStitchRowData) => void;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

export function EntityStitchRow({
  proposal,
  disabled,
  onConfirm,
  onReject,
}: EntityStitchRowProps): JSX.Element {
  // Cross-axis link target: /lake/semantic-types is the L5 audit
  // surface. When L5 grows ?type_id= deep-link routing, this href
  // resolves to the specific type row; until then it lands on the
  // audit page where the admin can scroll / search by type_id. Same
  // pattern as L6 ColumnClassificationRow's cross-axis link.
  const crossAxisHref = proposal.upstreamSemanticTypeId
    ? `/lake/semantic-types?type_id=${encodeURIComponent(proposal.upstreamSemanticTypeId)}`
    : null;

  return (
    <tr data-testid={`entity-stitch-row-${proposal.stitchId}`}>
      {/* Endpoint pair — src_a.col_a ↔ src_b.col_b */}
      <td
        data-testid={`entity-stitch-pair-${proposal.stitchId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {proposal.srcTableA} · {proposal.srcColumnA}
          </code>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            ↔
          </span>
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {proposal.srcTableB} · {proposal.srcColumnB}
          </code>
        </div>
      </td>

      {/* Entity kind chip (8-value) */}
      <td
        data-testid={`entity-stitch-kind-${proposal.stitchId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <EntityKindChip
          kind={proposal.entityKind}
          testIdSuffix={proposal.stitchId}
        />
      </td>

      {/* Confidence */}
      <td
        data-testid={`entity-stitch-confidence-${proposal.stitchId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(proposal.confidence)}
      </td>

      {/* Strategy badge + cross-axis L5 link when applicable */}
      <td
        data-testid={`entity-stitch-strategy-${proposal.stitchId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono">{proposal.strategy}</code>
          {crossAxisHref ? (
            <a
              href={crossAxisHref}
              data-testid={`entity-stitch-l5-link-${proposal.stitchId}`}
              className="wb-mono"
              style={{
                fontSize: 9,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              view L5 semantic type →
            </a>
          ) : null}
        </div>
      </td>

      {/* Confirm + Reject */}
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
          onClick={() => onConfirm(proposal)}
          disabled={disabled}
          data-testid={`entity-stitch-confirm-${proposal.stitchId}`}
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
          onClick={() => onReject(proposal)}
          disabled={disabled}
          data-testid={`entity-stitch-reject-${proposal.stitchId}`}
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
