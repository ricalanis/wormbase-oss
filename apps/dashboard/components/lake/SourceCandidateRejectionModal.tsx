/**
 * SourceCandidateRejectionModal — Reject dialog with strict reason
 * enum (L1 Sub-wave D, 2026-06-08).
 *
 * Surfaces the 5-value L1-specific enum from
 * :class:`SourceCandidateRejectedPayload`:
 *
 *   - duplicate       — L1-specific 5th value; we already have this
 *                       source or something equivalent (distinct from
 *                       L8's ``wrong_pairing``, L6's ``wrong_level``,
 *                       L5's ``wrong_type``, L4's ``already_handled``,
 *                       L7's ``wrong_threshold``)
 *   - false_positive  — the strategy mis-identified the candidate
 *                       entirely
 *   - low_value       — plausible candidate but not worth surfacing
 *   - out_of_scope    — correct candidate but outside the domain
 *                       we care about
 *   - other           — notes recommended
 *
 * The reason is required; notes are optional. Both are forwarded to
 * the server action which then POSTs to worm-core's reject endpoint.
 */

"use client";

import { useEffect, useState } from "react";

export type SourceCandidateRejectReason =
  | "duplicate"
  | "false_positive"
  | "low_value"
  | "out_of_scope"
  | "other";

export const SOURCE_CANDIDATE_REJECT_REASONS: ReadonlyArray<{
  value: SourceCandidateRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "duplicate",
    label: "Duplicate",
    hint: "We already have this source (or an equivalent one) connected. L1-specific: most common triage reject reason — the strategies overpropose familiar connectors.",
  },
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy mis-identified the candidate entirely — the proposed_kind / proposed_identifier do not point to a real source.",
  },
  {
    value: "low_value",
    label: "Low value",
    hint: "Plausible candidate but not worth surfacing for connection — the connector exists but the data doesn't support a KPI / decision.",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Correct candidate but outside the domain we care about (e.g. a marketing source proposed in a finance-only tenant).",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface SourceCandidateRejectionModalProps {
  candidateId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    candidateId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function SourceCandidateRejectionModal({
  candidateId,
  open,
  onClose,
  onSubmit,
}: SourceCandidateRejectionModalProps): JSX.Element | null {
  const [reason, setReason] =
    useState<SourceCandidateRejectReason>("duplicate");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      // Reset to the L1-most-common reason on close.
      setReason("duplicate");
      setNotes("");
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const trimmed = notes.trim();
    const result = await onSubmit(
      candidateId,
      reason,
      trimmed.length > 0 ? trimmed : undefined,
    );
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error ?? "unknown error");
      return;
    }
    onClose();
  };

  const selected = SOURCE_CANDIDATE_REJECT_REASONS.find(
    (r) => r.value === reason,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject source candidate"
      data-testid="source-candidate-reject-modal"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 18, 14, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          background: "var(--wb-color-paper, #f8f3e1)",
          border: "1px solid var(--wb-color-aged-ink, #2a2620)",
          padding: 20,
          width: "min(520px, 92vw)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Reject source candidate
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this candidate
          </h2>
          <code
            className="wb-mono"
            data-testid="source-candidate-reject-candidate-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            candidate_id={candidateId}
          </code>
        </header>

        <label
          htmlFor="source-candidate-reject-reason"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
          }}
        >
          <span>Reason (required)</span>
          <select
            id="source-candidate-reject-reason"
            data-testid="source-candidate-reject-reason"
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as SourceCandidateRejectReason)
            }
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {SOURCE_CANDIDATE_REJECT_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          {selected ? (
            <span
              style={{
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray, #7c7569)",
                fontSize: 11,
              }}
            >
              {selected.hint}
            </span>
          ) : null}
        </label>

        <label
          htmlFor="source-candidate-reject-notes"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
          }}
        >
          <span>Notes (optional)</span>
          <textarea
            id="source-candidate-reject-notes"
            data-testid="source-candidate-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the source-candidate detail row."
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 8,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
              resize: "vertical",
            }}
          />
        </label>

        {error ? (
          <div
            role="alert"
            data-testid="source-candidate-reject-error"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            {error}
          </div>
        ) : null}

        <footer style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            data-testid="source-candidate-reject-cancel"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink, #2a2620)",
              background: "var(--wb-color-paper, #f8f3e1)",
              color: "var(--wb-color-aged-ink, #2a2620)",
              cursor: submitting ? "wait" : "pointer",
            }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            data-testid="source-candidate-reject-submit"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "6px 14px",
              border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
              background: "var(--wb-color-sepia-warning-deep, #b6741c)",
              color: "var(--wb-color-paper, #f8f3e1)",
              cursor: submitting ? "wait" : "pointer",
            }}
          >
            {submitting ? "Rejecting…" : "Reject candidate"}
          </button>
        </footer>
      </form>
    </div>
  );
}
