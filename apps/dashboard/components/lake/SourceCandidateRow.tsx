/**
 * SourceCandidateRow — single row in the /lake/source-candidates
 * pending table (L1 Sub-wave D, 2026-06-08).
 *
 * Renders ``proposed_kind`` chip + ``proposed_identifier`` +
 * ``domain_id_hint`` (when set) + strategy + confidence +
 * Promote/Reject buttons. Buttons are disabled for non-admins so the
 * surface is read-only for observers/members.
 *
 * Unlike L8's EntityStitchRow which carries a cross-axis L5 link, L1
 * rows do NOT render a peer-L-axis cross-axis link — its strategies
 * read lightweight platform projections, not peer-axis outputs (per
 * spec §4.6, cross-axis chain count stays at 3). The sui-generis
 * "→ source pipeline" downstream link only appears on **promoted**
 * rows in the Promoted Candidates section below, NOT on pending rows.
 *
 * Wave 1 limitations honored honestly:
 *   - ``domain_id_hint`` may be NULL even when populated upstream
 *     (handoff concerns #2 + #3 — KpiNodeRecord +
 *     SilverConversationRecord both surface NULL today). The row
 *     renders the hint when set; suppresses the cell when NULL —
 *     no synthesized values.
 */

"use client";

import type { SourceCandidateRow as SourceCandidateRowData } from "../../lib/source-candidates";
import { ProposedKindChip } from "./ProposedKindChip";

export interface SourceCandidateRowProps {
  proposal: SourceCandidateRowData;
  /** Disable action buttons when caller is not an admin. */
  disabled?: boolean;
  onPromote: (proposal: SourceCandidateRowData) => void;
  onReject: (proposal: SourceCandidateRowData) => void;
}

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

export function SourceCandidateRow({
  proposal,
  disabled,
  onPromote,
  onReject,
}: SourceCandidateRowProps): JSX.Element {
  return (
    <tr data-testid={`source-candidate-row-${proposal.candidateId}`}>
      {/* Proposed kind chip + identifier */}
      <td
        data-testid={`source-candidate-target-${proposal.candidateId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <ProposedKindChip
            kind={proposal.proposedKind}
            testIdSuffix={proposal.candidateId}
          />
          <code
            className="wb-mono"
            data-testid={`source-candidate-identifier-${proposal.candidateId}`}
            style={{ fontSize: 11 }}
          >
            {proposal.proposedIdentifier}
          </code>
        </div>
      </td>

      {/* Domain hint — honest NULL when upstream did not supply.
          Wave 1 limitation per handoff concerns #2 + #3. */}
      <td
        data-testid={`source-candidate-domain-${proposal.candidateId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 11,
          color: "var(--wb-color-hash-gray, #7c7569)",
        }}
      >
        {proposal.domainIdHint ? (
          <code className="wb-mono" style={{ fontSize: 11 }}>
            {proposal.domainIdHint}
          </code>
        ) : (
          <span
            data-testid={`source-candidate-domain-null-${proposal.candidateId}`}
            style={{ fontStyle: "italic", opacity: 0.7 }}
          >
            —
          </span>
        )}
      </td>

      {/* Confidence */}
      <td
        data-testid={`source-candidate-confidence-${proposal.candidateId}`}
        style={{
          padding: "8px 12px",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {fmtConfidence(proposal.confidence)}
      </td>

      {/* Strategy */}
      <td
        data-testid={`source-candidate-strategy-${proposal.candidateId}`}
        style={{ padding: "8px 12px", fontSize: 11 }}
      >
        <code className="wb-mono">{proposal.strategy}</code>
      </td>

      {/* Promote + Reject */}
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
          onClick={() => onPromote(proposal)}
          disabled={disabled}
          data-testid={`source-candidate-promote-${proposal.candidateId}`}
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
          Promote
        </button>
        <button
          type="button"
          onClick={() => onReject(proposal)}
          disabled={disabled}
          data-testid={`source-candidate-reject-${proposal.candidateId}`}
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
