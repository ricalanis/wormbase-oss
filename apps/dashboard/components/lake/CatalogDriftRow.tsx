/**
 * CatalogDriftRow — single row in the /lake/catalog-drift pending
 * table (L2 Sub-wave D, 2026-06-09; L4↦L2 Half B 2026-06-12).
 *
 * Renders ``drift_kind`` chip + ``source_id.table_id[.column]``
 * identifier + before→after delta + strategy + confidence +
 * Acknowledge/Reject buttons. Buttons are disabled for non-admins so
 * the surface is read-only for observers/members.
 *
 * L2 uses ``acknowledge`` (not ``confirm`` / ``promote``) for the
 * affirmative state: the drift was already observed by the catalog-
 * mirror's W5a Reactivity; acknowledgment records the operator's
 * disposition with no downstream pipeline trigger.
 *
 * **L4↦L2 reverse arc (Half B, 2026-06-12)**: when ``impactCount > 0``,
 * the row renders a "↪ N downstream impacts" badge linking to the
 * /lake/schema-impact surface filtered by the drift's
 * ``(source_id, table_id, column)``. The forward arc lives in the
 * worm-core agent-gateway construction wiring (L4's
 * AcknowledgedDriftImpactStrategy elevates impact severity on
 * acknowledged drifts). The reverse arc is read-only enrichment —
 * no new ledger writes, no env knob; renders nothing when
 * ``impactCount`` is undefined or 0 (honest empty state).
 */

"use client";

import type {
  CatalogDriftRow as CatalogDriftRowData,
} from "../../lib/catalog-drift";
import { BeforeAfterDelta } from "./BeforeAfterDelta";
import { DriftKindChip } from "./DriftKindChip";

export interface CatalogDriftRowProps {
  drift: CatalogDriftRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onAcknowledge: (drift: CatalogDriftRowData) => void;
  onReject: (drift: CatalogDriftRowData) => void;
  /**
   * L4↦L2 cross-axis enrichment (Half B, reverse direction).
   *
   * Count of L4 schema-evolution impacts (state ∈ {proposed,
   * confirmed}) targeting the same
   * ``(source_id, table_id, column)`` as this drift row. When > 0,
   * the row renders an "↪ N downstream impacts" badge linking to
   * /lake/schema-impact filtered to the drift's tuple. When 0 or
   * undefined, the row renders no badge (honest empty state).
   */
  impactCount?: number;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

/** Compose the ``source_id.table_id[.column]`` identifier surfaced
 *  in the target cell. ``column`` is null for table-level drifts. */
function fmtTarget(drift: CatalogDriftRowData): string {
  const tail = drift.column ? `.${drift.column}` : "";
  return `${drift.sourceId}.${drift.tableId}${tail}`;
}

/**
 * Build the cross-axis URL pointing /lake/schema-impact at this
 * drift's tuple. The L4 surface accepts ``source_id``, ``src_table``,
 * and ``src_column`` query params for narrowing the list — same
 * grammar the L4 page uses for its own filter widgets.
 *
 * Note: column-level drifts pass ``src_column``; table-level drifts
 * (drift.column null) omit the param. The reverse-direction badge
 * is rendered only when impactCount > 0, which for table-level
 * drifts implies the L4 projection had matching impacts under that
 * table — the omitted ``src_column`` filter widens the L4 page
 * scope to the table, which is the right zoom for inspection.
 */
function buildImpactsLink(drift: CatalogDriftRowData): string {
  const params = new URLSearchParams();
  params.set("source_id", drift.sourceId);
  params.set("src_table", drift.tableId);
  if (drift.column) {
    params.set("src_column", drift.column);
  }
  return `/lake/schema-impact?${params.toString()}`;
}

export function CatalogDriftRow({
  drift,
  disabled,
  onAcknowledge,
  onReject,
  impactCount,
}: CatalogDriftRowProps): JSX.Element {
  const showImpactBadge =
    typeof impactCount === "number" && impactCount > 0;
  return (
    <tr data-testid={`catalog-drift-row-${drift.driftId}`}>
      {/* drift_kind chip + identifier */}
      <td
        data-testid={`catalog-drift-target-${drift.driftId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <DriftKindChip
            kind={drift.driftKind}
            testIdSuffix={drift.driftId}
          />
          <code
            className="wb-mono"
            data-testid={`catalog-drift-identifier-${drift.driftId}`}
            style={{ fontSize: 11 }}
          >
            {fmtTarget(drift)}
          </code>
          {showImpactBadge ? (
            <a
              href={buildImpactsLink(drift)}
              data-testid={`catalog-drift-impact-badge-${drift.driftId}`}
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                color: "var(--wb-color-sepia-warning-deep, #b6741c)",
                textDecoration: "none",
                marginTop: 2,
                cursor: "pointer",
              }}
              title="View L4 schema-evolution-impact rows for this drift's column"
            >
              {`↪ ${impactCount} downstream impact${
                impactCount === 1 ? "" : "s"
              } via L4`}
            </a>
          ) : null}
        </div>
      </td>

      {/* Before → After delta */}
      <td
        data-testid={`catalog-drift-delta-cell-${drift.driftId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <BeforeAfterDelta
          driftKind={drift.driftKind}
          before={drift.before}
          after={drift.after}
          testIdSuffix={drift.driftId}
        />
      </td>

      {/* Confidence */}
      <td
        data-testid={`catalog-drift-confidence-${drift.driftId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(drift.confidence)}
      </td>

      {/* Strategy */}
      <td
        data-testid={`catalog-drift-strategy-${drift.driftId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <code className="wb-mono">{drift.strategy}</code>
      </td>

      {/* Acknowledge + Reject */}
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
          onClick={() => onAcknowledge(drift)}
          disabled={disabled}
          data-testid={`catalog-drift-acknowledge-${drift.driftId}`}
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
          Acknowledge
        </button>
        <button
          type="button"
          onClick={() => onReject(drift)}
          disabled={disabled}
          data-testid={`catalog-drift-reject-${drift.driftId}`}
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
