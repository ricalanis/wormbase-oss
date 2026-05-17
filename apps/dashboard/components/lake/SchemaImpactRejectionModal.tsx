/**
 * SchemaImpactRejectionModal — Reject dialog with strict reason enum
 * (L4 Sub-wave D, 2026-06-02).
 *
 * Surfaces the 5-value enum from :class:`SchemaImpactRejectedPayload`:
 *   - false_positive   — the strategy mis-mapped the change to this target
 *   - already_handled  — the impact is real but already addressed downstream
 *   - low_value        — plausible but not worth surfacing
 *   - out_of_scope     — correct but outside the domain we care about
 *   - other            — notes recommended
 *
 * The reason is required; notes are optional. Both are forwarded to the
 * server action which then POSTs to worm-core's reject endpoint.
 *
 * L4-specific: this enum differs from L3's and L7's by one value each.
 * L3 ships ``wrong_direction`` + ``low_confidence``; L7 ships
 * ``wrong_threshold`` + ``low_value``; L4 ships ``already_handled`` +
 * ``low_value`` (impact-evolution semantics — schema changes may have
 * already been mitigated downstream).
 */

"use client";

import { useEffect, useState } from "react";

export type SchemaImpactRejectReason =
  | "false_positive"
  | "already_handled"
  | "low_value"
  | "out_of_scope"
  | "other";

export const SCHEMA_IMPACT_REJECT_REASONS: ReadonlyArray<{
  value: SchemaImpactRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy mis-mapped the change — the downstream target is not actually affected.",
  },
  {
    value: "already_handled",
    label: "Already handled",
    hint: "Impact is real but the downstream owner has already migrated / coerced / patched it.",
  },
  {
    value: "low_value",
    label: "Low value",
    hint: "Plausible impact but not worth surfacing to admins for action.",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Correct impact but the source or target is outside the domain we care about.",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface SchemaImpactRejectionModalProps {
  impactId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    impactId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function SchemaImpactRejectionModal({
  impactId,
  open,
  onClose,
  onSubmit,
}: SchemaImpactRejectionModalProps): JSX.Element | null {
  const [reason, setReason] =
    useState<SchemaImpactRejectReason>("false_positive");
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
      impactId,
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

  const selected = SCHEMA_IMPACT_REJECT_REASONS.find((r) => r.value === reason);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject schema impact"
      data-testid="schema-impact-reject-modal"
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
            Reject schema impact
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this candidate impact
          </h2>
          <code
            className="wb-mono"
            data-testid="schema-impact-reject-impact-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            impact_id={impactId}
          </code>
        </header>

        <label
          htmlFor="schema-impact-reject-reason"
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
            id="schema-impact-reject-reason"
            data-testid="schema-impact-reject-reason"
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as SchemaImpactRejectReason)
            }
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {SCHEMA_IMPACT_REJECT_REASONS.map((r) => (
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
          htmlFor="schema-impact-reject-notes"
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
            id="schema-impact-reject-notes"
            data-testid="schema-impact-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the impact-detail row."
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
            data-testid="schema-impact-reject-error"
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
            data-testid="schema-impact-reject-cancel"
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
            data-testid="schema-impact-reject-submit"
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
            {submitting ? "Rejecting…" : "Reject impact"}
          </button>
        </footer>
      </form>
    </div>
  );
}
