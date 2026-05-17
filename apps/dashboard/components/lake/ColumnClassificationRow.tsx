/**
 * ColumnClassificationRow — single row in the /lake/column-classification
 * pending table (L6 Sub-wave D, 2026-06-06).
 *
 * Renders the table.column, the proposed classification_level chip (5
 * colored badges: public=gray / internal=blue / confidential=amber /
 * pii=red / regulated=red+lock), confidence, the strategy that
 * produced the proposal, and Confirm + Reject buttons. The buttons
 * are disabled for non-admins so the surface is read-only for
 * observers/members.
 *
 * Cross-axis link to L5 — second cross-axis dashboard navigation in
 * the lake stack (after L4→L3 in SchemaImpactRow). When the
 * classification carries ``upstreamSemanticTypeId`` (i.e. the
 * ``semantic_type`` strategy produced this classification by reading
 * L5's projection), the row renders a small "view L5 semantic type"
 * link to ``/lake/semantic-types?type_id=<id>``. When the field is
 * null (e.g. ``naming_pattern`` / ``domain_default`` strategies do
 * not consult L5), the link slot stays empty rather than rendering a
 * dead link.
 *
 * Cross-axis link pattern (matches L4→L3 SchemaImpactRow contract):
 *
 *   1. The producing axis writes its projection-row id onto the
 *      consuming entry's payload (here: ``upstream_semantic_type_id``).
 *   2. The consuming dashboard renders a link to the producer's surface
 *      when (and ONLY when) the id is set.
 *   3. The link target is the producer's audit page; future iterations
 *      can deepen ``?type_id=<id>`` query-param routing on the producer
 *      side without changing this row's contract.
 */

"use client";

import type {
  ClassificationLevel,
  ColumnClassificationRow as ColumnClassificationRowData,
} from "../../lib/column-classification";

export interface ColumnClassificationRowProps {
  proposal: ColumnClassificationRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (proposal: ColumnClassificationRowData) => void;
  onReject: (proposal: ColumnClassificationRowData) => void;
  /**
   * R5 L4↦L6 reverse-arc enrichment (Recipe Addendum #3, 2026-05-16).
   *
   * Count of L4 schema-evolution impacts (state ∈ {proposed,
   * confirmed}) whose evidence carries this classification's
   * ``classificationId`` as ``upstream_classification_id``. When > 0,
   * the row renders an "↪ N impact proposals via L4" badge linking
   * to /lake/schema-impact filtered by the classification id. When
   * 0 or undefined, no badge renders (honest empty state).
   */
  impactCount?: number;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

/**
 * Per-level visual signature for the 5-value enum. ``regulated``
 * carries a red border AND a lock icon glyph; ``pii`` carries red
 * without the lock; ``confidential`` is amber; ``internal`` is blue;
 * ``public`` is neutral gray. Mirrors the canonical 5-value governance
 * classification palette per CLAUDE.md §"Ledger-native governance".
 */
interface LevelChipStyle {
  bg: string;
  fg: string;
  border: string;
  prefix?: string;
}

function levelChipStyle(level: ClassificationLevel): LevelChipStyle {
  switch (level) {
    case "public":
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
    case "internal":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-archive-blue-deep, #2c5f7c)",
        border: "var(--wb-color-archive-blue-deep, #2c5f7c)",
      };
    case "confidential":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
        border: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "pii":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        border: "var(--wb-color-alarm-red-deep, #9c2a2a)",
      };
    case "regulated":
      return {
        bg: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        fg: "var(--wb-color-paper, #f8f3e1)",
        border: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        // Lock glyph (U+1F512) distinguishes regulated from pii visually.
        prefix: "\u{1F512} ",
      };
  }
}

function buildClassificationImpactsLink(classificationId: string): string {
  const params = new URLSearchParams();
  params.set("upstream_classification_id", classificationId);
  return `/lake/schema-impact?${params.toString()}`;
}

export function ColumnClassificationRow({
  proposal,
  disabled,
  onConfirm,
  onReject,
  impactCount,
}: ColumnClassificationRowProps): JSX.Element {
  const chip = levelChipStyle(proposal.classificationLevel);
  // Cross-axis link target: /lake/semantic-types is the L5 audit
  // surface. When L5 grows ?type_id= deep-link routing, this href
  // resolves to the specific type row; until then it lands on the
  // audit page where the admin can scroll / search by type_id.
  const crossAxisHref = proposal.upstreamSemanticTypeId
    ? `/lake/semantic-types?type_id=${encodeURIComponent(proposal.upstreamSemanticTypeId)}`
    : null;

  const isRegulated = proposal.classificationLevel === "regulated";
  const showImpactBadge =
    typeof impactCount === "number" && impactCount > 0;

  return (
    <tr data-testid={`column-classification-row-${proposal.classificationId}`}>
      {/* Table.column */}
      <td
        data-testid={`column-classification-target-${proposal.classificationId}`}
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

      {/* Classification level chip (5-value) */}
      <td
        data-testid={`column-classification-level-${proposal.classificationId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <span
          data-testid={`column-classification-level-chip-${proposal.classificationId}`}
          data-level={proposal.classificationLevel}
          data-regulated={isRegulated ? "true" : "false"}
          className="wb-mono"
          aria-label={
            isRegulated
              ? `regulated (locked) — ${proposal.classificationLevel}`
              : proposal.classificationLevel
          }
          style={{
            display: "inline-block",
            padding: "2px 8px",
            border: `1px solid ${chip.border}`,
            background: chip.bg,
            color: chip.fg,
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          {chip.prefix ?? ""}
          {proposal.classificationLevel}
        </span>
      </td>

      {/* Confidence */}
      <td
        data-testid={`column-classification-confidence-${proposal.classificationId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(proposal.confidence)}
      </td>

      {/* Strategy badge + cross-axis L5 link when applicable
          + L4↦L6 reverse-arc impact badge (R5, 2026-05-16). */}
      <td
        data-testid={`column-classification-strategy-${proposal.classificationId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono">{proposal.strategy}</code>
          {crossAxisHref ? (
            <a
              href={crossAxisHref}
              data-testid={`column-classification-l5-link-${proposal.classificationId}`}
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
          {showImpactBadge ? (
            <a
              href={buildClassificationImpactsLink(proposal.classificationId)}
              data-testid={`column-classification-impact-badge-${proposal.classificationId}`}
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                color: "var(--wb-color-sepia-warning-deep, #b6741c)",
                textDecoration: "none",
                cursor: "pointer",
              }}
              title="View L4 schema-evolution-impact rows elevated by this classification"
            >
              {`↪ ${impactCount} impact proposal${
                impactCount === 1 ? "" : "s"
              } via L4`}
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
          data-testid={`column-classification-confirm-${proposal.classificationId}`}
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
          data-testid={`column-classification-reject-${proposal.classificationId}`}
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
