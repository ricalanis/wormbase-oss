/**
 * ColumnClassificationRejectionModal — Reject dialog with strict reason
 * enum (L6 Sub-wave D, 2026-06-06).
 *
 * Surfaces the 5-value L6-specific enum from
 * :class:`ColumnClassificationRejectedPayload`:
 *   - false_positive — the strategy mis-identified the column entirely
 *   - low_value      — plausible but not worth surfacing
 *   - wrong_level    — the column IS classified but a different level
 *                      from the 5-value enum (L6-specific 5th value;
 *                      distinct from L5's ``wrong_type``, L4's
 *                      ``already_handled`` and L7's ``wrong_threshold``)
 *   - out_of_scope   — correct but outside the domain we care about
 *   - other          — notes recommended
 *
 * The reason is required; notes are optional. Both are forwarded to
 * the server action which then POSTs to worm-core's reject endpoint.
 */

"use client";

import { useEffect, useState } from "react";

export type ColumnClassificationRejectReason =
  | "false_positive"
  | "low_value"
  | "wrong_level"
  | "out_of_scope"
  | "other";

export const COLUMN_CLASSIFICATION_REJECT_REASONS: ReadonlyArray<{
  value: ColumnClassificationRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy mis-identified this column entirely — it does not carry the proposed classification level at all.",
  },
  {
    value: "low_value",
    label: "Low value",
    hint: "Plausible classification but not worth surfacing to admins for governance action.",
  },
  {
    value: "wrong_level",
    label: "Wrong level",
    hint: "The column IS classified but the strategy picked the wrong level from the 5-value enum (e.g. proposed pii but the column is regulated).",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Correct classification but the column / table is outside the domain we care about.",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface ColumnClassificationRejectionModalProps {
  classificationId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    classificationId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function ColumnClassificationRejectionModal({
  classificationId,
  open,
  onClose,
  onSubmit,
}: ColumnClassificationRejectionModalProps): JSX.Element | null {
  const [reason, setReason] =
    useState<ColumnClassificationRejectReason>("false_positive");
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
      classificationId,
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

  const selected = COLUMN_CLASSIFICATION_REJECT_REASONS.find(
    (r) => r.value === reason,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject column classification"
      data-testid="column-classification-reject-modal"
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
            Reject column classification
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this candidate classification
          </h2>
          <code
            className="wb-mono"
            data-testid="column-classification-reject-classification-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            classification_id={classificationId}
          </code>
        </header>

        <label
          htmlFor="column-classification-reject-reason"
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
            id="column-classification-reject-reason"
            data-testid="column-classification-reject-reason"
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as ColumnClassificationRejectReason)
            }
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {COLUMN_CLASSIFICATION_REJECT_REASONS.map((r) => (
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
          htmlFor="column-classification-reject-notes"
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
            id="column-classification-reject-notes"
            data-testid="column-classification-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the column-classification-detail row."
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
            data-testid="column-classification-reject-error"
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
            data-testid="column-classification-reject-cancel"
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
            data-testid="column-classification-reject-submit"
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
            {submitting ? "Rejecting…" : "Reject classification"}
          </button>
        </footer>
      </form>
    </div>
  );
}
