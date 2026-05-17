/**
 * CatalogDriftRejectionModal — Reject dialog with strict 5-value
 * L2 reason enum (Sub-wave D, 2026-06-09).
 *
 * Surfaces the 5-value L2-specific enum from
 * :class:`CatalogDriftRejectedPayload`:
 *
 *   - false_positive    — strategy mis-identified the drift entirely
 *   - inconsequential   — drift is real but tiny / harmless
 *   - expected_change   — L2-specific 5th value; drift was real but a
 *                          known intentional change (e.g. planned
 *                          schema migration). Distinct from L1's
 *                          ``duplicate``, L8's ``wrong_pairing``,
 *                          L6's ``wrong_level``, L5's ``wrong_type``,
 *                          L4's ``already_handled``, L7's
 *                          ``wrong_threshold``.
 *   - out_of_scope      — correct drift but outside the domain
 *                          we care about
 *   - other             — notes recommended
 *
 * The reason is required; notes are optional. Both are forwarded to
 * the server action which POSTs to worm-core's reject endpoint.
 */

"use client";

import { useEffect, useState } from "react";

export type CatalogDriftRejectReason =
  | "false_positive"
  | "inconsequential"
  | "expected_change"
  | "out_of_scope"
  | "other";

export const CATALOG_DRIFT_REJECT_REASONS: ReadonlyArray<{
  value: CatalogDriftRejectReason;
  label: string;
  hint: string;
}> = [
  {
    value: "false_positive",
    label: "False positive",
    hint: "Strategy mis-identified the drift entirely — the catalog-mirror snapshot diff doesn't reflect a real structural change (e.g. transient projection lag).",
  },
  {
    value: "inconsequential",
    label: "Inconsequential",
    hint: "Drift is real but tiny / harmless — e.g. a debug-only column or an internal staging table. No downstream impact worth tracking.",
  },
  {
    value: "expected_change",
    label: "Expected change",
    hint: "L2-specific: drift was real but a known intentional change (e.g. planned schema migration, deliberate column rename). The team already knows about it — no further action required.",
  },
  {
    value: "out_of_scope",
    label: "Out of scope",
    hint: "Correct drift but outside the domain we care about (e.g. a marketing-side drift detected in a finance-only tenant).",
  },
  {
    value: "other",
    label: "Other",
    hint: "Notes recommended.",
  },
];

export interface CatalogDriftRejectionModalProps {
  driftId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    driftId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function CatalogDriftRejectionModal({
  driftId,
  open,
  onClose,
  onSubmit,
}: CatalogDriftRejectionModalProps): JSX.Element | null {
  const [reason, setReason] =
    useState<CatalogDriftRejectReason>("expected_change");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      // Reset to the L2-most-common reason on close: most drifts
      // are real but expected migrations.
      setReason("expected_change");
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
      driftId,
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

  const selected = CATALOG_DRIFT_REJECT_REASONS.find(
    (r) => r.value === reason,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reject catalog drift"
      data-testid="catalog-drift-reject-modal"
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
            Reject catalog drift
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Decline this drift proposal
          </h2>
          <code
            className="wb-mono"
            data-testid="catalog-drift-reject-drift-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            drift_id={driftId}
          </code>
        </header>

        <label
          htmlFor="catalog-drift-reject-reason"
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
            id="catalog-drift-reject-reason"
            data-testid="catalog-drift-reject-reason"
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as CatalogDriftRejectReason)
            }
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: 6,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            {CATALOG_DRIFT_REJECT_REASONS.map((r) => (
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
          htmlFor="catalog-drift-reject-notes"
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
            id="catalog-drift-reject-notes"
            data-testid="catalog-drift-reject-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace + the catalog-drift detail row."
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
            data-testid="catalog-drift-reject-error"
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
            data-testid="catalog-drift-reject-cancel"
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
            data-testid="catalog-drift-reject-submit"
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
            {submitting ? "Rejecting…" : "Reject drift"}
          </button>
        </footer>
      </form>
    </div>
  );
}
