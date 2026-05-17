/**
 * SemanticTypeRejectionModal — Reject dialog with strict reason enum
 * (L5 Sub-wave D, 2026-06-05).
 *
 * Surfaces the 5-value L5-specific enum from
 * :class:`SemanticTypeRejectedPayload`:
 *   - false_positive — the strategy mis-identified the column's semantic type
 *   - low_value      — plausible but not worth surfacing
 *   - wrong_type     — the column is semantically typed but a different one
 *                      (L5-specific 5th value; replaces L4's
 *                      ``already_handled`` and L7's ``wrong_threshold``)
 *   - out_of_scope   — correct but outside the domain we care about
 *   - other          — notes recommended
 *
 * The reason is required; notes are optional. Both are forwarded to
 * the server action which then POSTs to worm-core's reject endpoint.
 */

"use client";

import { useEffect, useState } from "react";

export type SemanticTypeRejectReason =
  | "false_positive"
  | "low_value"
  | "wrong_type"
  | "out_of_scope"
  | "other";

export const SEMANTIC_TYPE_REJECT_REASONS: ReadonlyArray<{
  value: SemanticTypeRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy mis-identified this column — it does not carry the proposed semantic type at all.",
  },
  {
    value: "low_value",
    label: "Low value",
    hint: "Plausible semantic type but not worth surfacing to admins for action.",
  },
  {
    value: "wrong_type",
    label: "Wrong type",
    hint: "The column IS semantically typed but the strategy picked the wrong type from the 19-value enum (e.g. proposed email but the column is phone_e164).",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Correct semantic type but the column / table is outside the domain we care about.",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface SemanticTypeRejectionModalProps {
  typeId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    typeId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function SemanticTypeRejectionModal({
  typeId,
  open,
  onClose,
  onSubmit,
}: SemanticTypeRejectionModalProps): JSX.Element | null {
  const [reason, setReason] =
    useState<SemanticTypeRejectReason>("false_positive");
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
      typeId,
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

  const selected = SEMANTIC_TYPE_REJECT_REASONS.find((r) => r.value === reason);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject semantic type"
      data-testid="semantic-type-reject-modal"
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
            Reject semantic type
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this candidate semantic type
          </h2>
          <code
            className="wb-mono"
            data-testid="semantic-type-reject-type-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            type_id={typeId}
          </code>
        </header>

        <label
          htmlFor="semantic-type-reject-reason"
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
            id="semantic-type-reject-reason"
            data-testid="semantic-type-reject-reason"
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as SemanticTypeRejectReason)
            }
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {SEMANTIC_TYPE_REJECT_REASONS.map((r) => (
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
          htmlFor="semantic-type-reject-notes"
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
            id="semantic-type-reject-notes"
            data-testid="semantic-type-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the semantic-type-detail row."
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
            data-testid="semantic-type-reject-error"
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
            data-testid="semantic-type-reject-cancel"
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
            data-testid="semantic-type-reject-submit"
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
            {submitting ? "Rejecting…" : "Reject type"}
          </button>
        </footer>
      </form>
    </div>
  );
}
