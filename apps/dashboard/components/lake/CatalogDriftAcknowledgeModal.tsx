/**
 * CatalogDriftAcknowledgeModal — L2 Acknowledge dialog for
 * /lake/catalog-drift (Sub-wave D, 2026-06-09).
 *
 * Lighter than the rejection modal: only an optional notes textarea.
 * The action POSTs the acknowledge to worm-core via the server
 * action.
 *
 * L2 uses ``acknowledge`` (not ``confirm`` / ``promote``) because
 * the affirmative state is read-only — the drift was already
 * observed by the catalog-mirror's W5a Reactivity; the
 * ``catalog_drift_acknowledged`` entry records the operator's
 * disposition with no downstream pipeline trigger and no cross-axis
 * effect.
 */

"use client";

import { useEffect, useState } from "react";

export interface CatalogDriftAcknowledgeModalProps {
  driftId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    driftId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function CatalogDriftAcknowledgeModal({
  driftId,
  open,
  onClose,
  onSubmit,
}: CatalogDriftAcknowledgeModalProps): JSX.Element | null {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setNotes("");
      setError(null);
      setSubmitting(false);
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
      trimmed.length > 0 ? trimmed : undefined,
    );
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error ?? "unknown error");
      return;
    }
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Acknowledge catalog drift"
      data-testid="catalog-drift-acknowledge-modal"
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
            Acknowledge catalog drift
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Sign off — drift is known/expected
          </h2>
          <code
            className="wb-mono"
            data-testid="catalog-drift-acknowledge-drift-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            drift_id={driftId}
          </code>
        </header>

        {/* No-downstream-effect notice — L2-specific. Unlike L1's
            promote dual-write, L2's acknowledge is purely a record
            of operator disposition. */}
        <section
          data-testid="catalog-drift-acknowledge-notice"
          style={{
            border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 10,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Acknowledge is record-only
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontSize: 12,
            }}
          >
            Acknowledging this drift emits a
            ``catalog_drift_acknowledged`` ledger entry recording the
            operator&apos;s disposition. No downstream pipeline is
            triggered and no cross-axis effect is fired — the
            catalog-mirror&apos;s W5a Reactivity already detected the
            structural change; this is the human-in-the-loop sign-off
            that the change is known/expected (e.g. a planned schema
            migration).
          </p>
        </section>

        <label
          htmlFor="catalog-drift-acknowledge-notes"
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
            id="catalog-drift-acknowledge-notes"
            data-testid="catalog-drift-acknowledge-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace and the catalog-drift detail row (e.g. 'planned migration; tracked in JIRA-1234')."
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
            data-testid="catalog-drift-acknowledge-error"
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
            data-testid="catalog-drift-acknowledge-cancel"
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
            data-testid="catalog-drift-acknowledge-submit"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "6px 14px",
              border: "1px solid var(--wb-color-botanical-green-deep, #2d5d3a)",
              background: "var(--wb-color-botanical-green-deep, #2d5d3a)",
              color: "var(--wb-color-paper, #f8f3e1)",
              cursor: submitting ? "wait" : "pointer",
            }}
          >
            {submitting ? "Acknowledging…" : "Acknowledge drift"}
          </button>
        </footer>
      </form>
    </div>
  );
}
