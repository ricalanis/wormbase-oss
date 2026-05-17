/**
 * SchemaImpactRow — single row in the /lake/schema-impact pending table
 * (L4 Sub-wave D, 2026-06-02).
 *
 * Renders the change description (src_table.src_column → change_kind),
 * the downstream (tgt_table_id.tgt_column), three categorical badges
 * (change_kind / impact_kind / strategy), confidence, and
 * Confirm + Reject buttons. The buttons are disabled for non-admins so
 * the surface is read-only for observers/members.
 *
 * NEW for L4 — first cross-axis dashboard navigation. When the impact
 * carries ``upstream_lineage_edge_id`` (i.e. the ``lineage_edge``
 * strategy produced this impact by reading L3's projection), the row
 * renders a small "view L3 edge" link to ``/lake/lineage`` so the
 * admin can audit the source. When the field is null (e.g.
 * ``type_coercion`` strategy derives from bare type metadata, not from
 * L3), the link slot stays empty rather than rendering a dead link.
 *
 * Cross-axis link pattern (for future axes that consume other
 * projections):
 *
 *   1. The producing axis writes its projection-row id onto the
 *      consuming entry's payload (e.g. ``upstream_lineage_edge_id``).
 *   2. The consuming dashboard renders a link to the producer's surface
 *      when (and ONLY when) the id is set.
 *   3. The link target is the producer's audit page; future iterations
 *      can add ``?edge_id=<id>`` query params if the producer adds
 *      detail routing.
 */

"use client";

import type { SchemaImpactRow as SchemaImpactRowData } from "../../lib/schema-impact";

export interface SchemaImpactRowProps {
  impact: SchemaImpactRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (impact: SchemaImpactRowData) => void;
  onReject: (impact: SchemaImpactRowData) => void;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function changeArrow(kind: SchemaImpactRowData["changeKind"]): string {
  switch (kind) {
    case "column_added":
      return "+";
    case "column_dropped":
      return "−";
    case "column_type_changed":
      return "Δ";
  }
}

function changeColor(kind: SchemaImpactRowData["changeKind"]): string {
  switch (kind) {
    case "column_added":
      return "var(--wb-color-botanical-green-deep, #2d5d3a)";
    case "column_dropped":
      return "var(--wb-color-sepia-warning-deep, #b6741c)";
    case "column_type_changed":
      return "var(--wb-color-aged-ink, #2a2620)";
  }
}

export function SchemaImpactRow({
  impact,
  disabled,
  onConfirm,
  onReject,
}: SchemaImpactRowProps): JSX.Element {
  // Cross-axis link target: /lake/lineage is the L3 audit surface.
  // L3 does not (yet) implement detail routing on edge_id; when it
  // does, the link can be upgraded to /lake/lineage?edge_id=<id>
  // without changing this row's contract. Until then the link points
  // at the audit page and the admin scrolls / searches by edge_id.
  const crossAxisHref = impact.upstreamLineageEdgeId
    ? `/lake/lineage?edge_id=${encodeURIComponent(impact.upstreamLineageEdgeId)}`
    : null;

  return (
    <tr data-testid={`schema-impact-row-${impact.impactId}`}>
      {/* Change description: src_table · src_column (with change arrow) */}
      <td
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            data-testid={`schema-impact-change-arrow-${impact.impactId}`}
            className="wb-mono"
            aria-label={impact.changeKind}
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: changeColor(impact.changeKind),
              minWidth: 14,
              textAlign: "center",
            }}
          >
            {changeArrow(impact.changeKind)}
          </span>
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {impact.srcTable} · {impact.srcColumn}
          </code>
        </div>
      </td>

      {/* Downstream target: tgt_table_id · tgt_column */}
      <td
        data-testid={`schema-impact-target-${impact.impactId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <code className="wb-mono" style={{ fontSize: 11 }}>
          {impact.tgtTableId} · {impact.tgtColumn}
        </code>
      </td>

      {/* Change-kind badge (3 values) */}
      <td
        data-testid={`schema-impact-change-kind-${impact.impactId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <code
          className="wb-mono"
          style={{ color: changeColor(impact.changeKind) }}
        >
          {impact.changeKind}
        </code>
      </td>

      {/* Impact-kind badge (5 values) */}
      <td
        data-testid={`schema-impact-impact-kind-${impact.impactId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <code className="wb-mono">{impact.impactKind}</code>
      </td>

      {/* Confidence */}
      <td
        data-testid={`schema-impact-confidence-${impact.impactId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(impact.confidence)}
      </td>

      {/* Strategy badge (3 values) + cross-axis L3 link when applicable */}
      <td
        data-testid={`schema-impact-strategy-${impact.impactId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono">{impact.strategy}</code>
          {crossAxisHref ? (
            <a
              href={crossAxisHref}
              data-testid={`schema-impact-l3-link-${impact.impactId}`}
              className="wb-mono"
              style={{
                fontSize: 9,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              view L3 edge →
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
          onClick={() => onConfirm(impact)}
          disabled={disabled}
          data-testid={`schema-impact-confirm-${impact.impactId}`}
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
          onClick={() => onReject(impact)}
          disabled={disabled}
          data-testid={`schema-impact-reject-${impact.impactId}`}
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
