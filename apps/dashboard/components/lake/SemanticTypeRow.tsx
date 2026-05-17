/**
 * SemanticTypeRow — single row in the /lake/semantic-types pending table
 * (L5 Sub-wave D, 2026-06-05).
 *
 * Renders the table.column, the proposed semantic_type (badge — strict
 * 19-value enum), confidence, the strategy that produced the proposal,
 * and Confirm + Reject buttons. The buttons are disabled for non-
 * admins so the surface is read-only for observers/members.
 *
 * PII-band semantic types get a subtle warning chip so admins know
 * confirming will likely flow into ``regulated`` classification
 * proposals downstream (Phase 2 L5 → L6 chain, per L5 design §7).
 *
 * **Reverse-arc cluster (Recipe Addendum #3, 2026-05-16)**: L5 is the
 * most-consumed producer in the lake stack — 4 downstream axes (L6,
 * L8, L7, L4) all consume its confirmed semantic types. When any of
 * the four optional ``*Count`` props is > 0, a compact
 * ``<DownstreamCountsCluster />`` renders inline under the strategy
 * cell as a horizontal chip row. When all counts are 0 or undefined,
 * the cluster renders nothing (honest empty state).
 */

"use client";

import type {
  SemanticTypeRow as SemanticTypeRowData,
  SemanticTypeValue,
} from "../../lib/semantic-types";
import { DownstreamCountsCluster } from "./DownstreamCountsCluster";

export interface SemanticTypeRowProps {
  proposal: SemanticTypeRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (proposal: SemanticTypeRowData) => void;
  onReject: (proposal: SemanticTypeRowData) => void;
  /** R2 L6↦L5 — count of L6 column-classification rows derived from this type. */
  classificationCount?: number;
  /** R3 L8↦L5 — count of L8 entity-stitch rows derived from this type. */
  entityStitchCount?: number;
  /** R4 L7↦L5 — count of L7 quality-check rows derived from this type. */
  qualityCount?: number;
  /** R6 L4↦L5 — count of L4 schema-impact rows derived from this type. */
  impactCount?: number;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

/** PII band of the 19-value enum — surfaced with a warning chip. */
const PII_TYPES = new Set<SemanticTypeValue>([
  "pii_name",
  "pii_address",
  "pii_ssn",
  "pii_credit_card",
]);

function semanticTypeColor(t: SemanticTypeValue): string {
  if (PII_TYPES.has(t)) {
    return "var(--wb-color-sepia-warning-deep, #b6741c)";
  }
  return "var(--wb-color-aged-ink, #2a2620)";
}

export function SemanticTypeRow({
  proposal,
  disabled,
  onConfirm,
  onReject,
  classificationCount,
  entityStitchCount,
  qualityCount,
  impactCount,
}: SemanticTypeRowProps): JSX.Element {
  const isPii = PII_TYPES.has(proposal.semanticType);

  return (
    <tr data-testid={`semantic-type-row-${proposal.typeId}`}>
      {/* Table.column */}
      <td
        data-testid={`semantic-type-target-${proposal.typeId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <code className="wb-mono" style={{ fontSize: 11 }}>
          {proposal.tableId} · {proposal.column}
        </code>
      </td>

      {/* Semantic-type badge (19 values) */}
      <td
        data-testid={`semantic-type-kind-${proposal.typeId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code
            className="wb-mono"
            style={{ color: semanticTypeColor(proposal.semanticType) }}
          >
            {proposal.semanticType}
          </code>
          {isPii ? (
            <span
              data-testid={`semantic-type-pii-chip-${proposal.typeId}`}
              className="wb-mono"
              style={{
                fontSize: 9,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-sepia-warning-deep, #b6741c)",
              }}
            >
              pii · sensitive
            </span>
          ) : null}
        </div>
      </td>

      {/* Confidence */}
      <td
        data-testid={`semantic-type-confidence-${proposal.typeId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(proposal.confidence)}
      </td>

      {/* Strategy badge (3 values: column_name / value_pattern / distribution)
          + reverse-arc downstream-counts cluster (R2 + R3 + R4 + R6).
          When all 4 counts are 0/undefined, the cluster renders nothing. */}
      <td
        data-testid={`semantic-type-strategy-${proposal.typeId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono">{proposal.strategy}</code>
          <DownstreamCountsCluster
            semanticTypeId={proposal.typeId}
            classificationCount={classificationCount}
            entityStitchCount={entityStitchCount}
            qualityCount={qualityCount}
            impactCount={impactCount}
          />
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
          data-testid={`semantic-type-confirm-${proposal.typeId}`}
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
          data-testid={`semantic-type-reject-${proposal.typeId}`}
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
