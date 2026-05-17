/**
 * LineageRejectionModal — Reject dialog with strict reason enum.
 *
 * Surfaces the 5-value enum from :class:`LineageEdgeRejectedPayload`:
 *   - false_positive
 *   - wrong_direction
 *   - low_confidence
 *   - out_of_scope
 *   - other
 *
 * The reason is required; notes are optional. Both are forwarded to the
 * server action which then POSTs to worm-core's reject endpoint.
 */

"use client";

import { useEffect, useState } from "react";

export type LineageRejectReason =
  | "false_positive"
  | "wrong_direction"
  | "low_confidence"
  | "out_of_scope"
  | "other";

export const REJECT_REASONS: ReadonlyArray<{
  value: LineageRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy fired on tables that have no real lineage relationship.",
  },
  {
    value: "wrong_direction",
    label: "Wrong direction",
    hint: "Edge endpoints are correct but src/tgt are reversed.",
  },
  {
    value: "low_confidence",
    label: "Low confidence",
    hint: "Plausible but not confident enough to accept.",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Edge is technically correct but outside the domain we care about.",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface LineageRejectionModalProps {
  edgeId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    edgeId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function LineageRejectionModal({
  edgeId,
  open,
  onClose,
  onSubmit,
}: LineageRejectionModalProps): JSX.Element | null {
  const [reason, setReason] = useState<LineageRejectReason>("false_positive");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setReason("false_positive");
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
      edgeId,
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

  const selected = REJECT_REASONS.find((r) => r.value === reason);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject lineage edge"
      data-testid="lineage-reject-modal"
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
            Reject lineage edge
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this candidate edge
          </h2>
          <code
            className="wb-mono"
            data-testid="lineage-reject-edge-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            edge_id={edgeId}
          </code>
        </header>

        <label
          htmlFor="lineage-reject-reason"
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
            id="lineage-reject-reason"
            data-testid="lineage-reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value as LineageRejectReason)}
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {REJECT_REASONS.map((r) => (
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
          htmlFor="lineage-reject-notes"
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
            id="lineage-reject-notes"
            data-testid="lineage-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the edge-detail row."
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
            data-testid="lineage-reject-error"
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
            data-testid="lineage-reject-cancel"
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
            data-testid="lineage-reject-submit"
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
            {submitting ? "Rejecting…" : "Reject edge"}
          </button>
        </footer>
      </form>
    </div>
  );
}
