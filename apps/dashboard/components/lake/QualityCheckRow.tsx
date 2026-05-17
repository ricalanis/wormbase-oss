/**
 * QualityCheckRow — single row in the /lake/quality pending table
 * (L7 Sub-wave D, 2026-05-30).
 *
 * Displays table · column · kind · confidence · strategy, with
 * Confirm + Reject buttons. The buttons are disabled for non-admins so
 * the surface is read-only for observers/members.
 *
 * Mirrors :class:`LineageProposalRow` structurally but renders a wider
 * row (kind cell carries the check kind — unique / not_null / freshness
 * / etc. — which has no L3 analogue).
 *
 * **L5→L7 cross-axis chain link** — when the check came from the
 * SemanticType strategy (4th cross-axis chain), the row carries
 * ``evidence.upstream_semantic_type_id`` pointing back to L5's
 * confirmed type. We surface a small "view L5 semantic type →" link
 * under the strategy cell, mirroring EntityStitchRow's L5-link pattern.
 */

"use client";

import type { QualityCheckRow as QualityCheckRowData } from "../../lib/quality";

export interface QualityCheckRowProps {
  check: QualityCheckRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onConfirm: (check: QualityCheckRowData) => void;
  onReject: (check: QualityCheckRowData) => void;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function extractUpstreamSemanticTypeId(
  evidence: Record<string, unknown>,
): string | null {
  // The cross-axis link is preserved on evidence.upstream_semantic_type_id
  // (the strategy populates it; the ledger evidence dict round-trips
  // verbatim). Keep this defensive — pre-cross-axis proposals do not
  // carry the field.
  const raw = evidence["upstream_semantic_type_id"];
  if (typeof raw !== "string" || !raw) return null;
  return raw;
}

export function QualityCheckRow({
  check,
  disabled,
  onConfirm,
  onReject,
}: QualityCheckRowProps): JSX.Element {
  const upstreamSemanticTypeId = extractUpstreamSemanticTypeId(check.evidence);
  const crossAxisHref = upstreamSemanticTypeId
    ? `/lake/semantic-types?type_id=${encodeURIComponent(upstreamSemanticTypeId)}`
    : null;
  return (
    <tr data-testid={`quality-check-row-${check.checkId}`}>
      <td
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <code className="wb-mono" style={{ fontSize: 11 }}>
          {check.tableId}
        </code>
      </td>
      <td
        data-testid={`quality-check-column-${check.checkId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        {check.column ? (
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {check.column}
          </code>
        ) : (
          <span
            style={{
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray, #7c7569)",
              fontSize: 11,
            }}
          >
            (table-level)
          </span>
        )}
      </td>
      <td
        data-testid={`quality-check-kind-${check.checkId}`}
        style={{
          padding: "8px 12px",
          fontSize: 11,
        }}
      >
        <code className="wb-mono">{check.checkKind}</code>
      </td>
      <td
        data-testid={`quality-check-confidence-${check.checkId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(check.confidence)}
      </td>
      <td
        data-testid={`quality-check-strategy-${check.checkId}`}
        style={{
          padding: "8px 12px",
          fontSize: 11,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <code className="wb-mono">{check.strategy}</code>
          {crossAxisHref ? (
            <a
              href={crossAxisHref}
              data-testid={`quality-check-l5-link-${check.checkId}`}
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
          onClick={() => onConfirm(check)}
          disabled={disabled}
          data-testid={`quality-check-confirm-${check.checkId}`}
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
          onClick={() => onReject(check)}
          disabled={disabled}
          data-testid={`quality-check-reject-${check.checkId}`}
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
