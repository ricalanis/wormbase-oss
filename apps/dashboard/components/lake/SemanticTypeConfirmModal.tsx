/**
 * SemanticTypeConfirmModal — light Confirm dialog for /lake/semantic-types
 * (L5 Sub-wave D, 2026-06-05).
 *
 * Lighter than the rejection modal: only an optional notes textarea.
 * The action POSTs the confirmation to worm-core via the server
 * action; the modal owns no business logic beyond capturing the
 * optional annotation.
 */

"use client";

import { useEffect, useRef, useState } from "react";

export interface SemanticTypeConfirmModalProps {
  typeId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    typeId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function SemanticTypeConfirmModal({
  typeId,
  open,
  onClose,
  onSubmit,
}: SemanticTypeConfirmModalProps): JSX.Element | null {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

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
      typeId,
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
      aria-label="Confirm semantic type"
      data-testid="semantic-type-confirm-modal"
      ref={dialogRef}
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
          width: "min(480px, 90vw)",
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
            Confirm semantic type
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Approve this candidate semantic type
          </h2>
          <code
            className="wb-mono"
            data-testid="semantic-type-confirm-type-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            type_id={typeId}
          </code>
        </header>

        <label
          htmlFor="semantic-type-confirm-notes"
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
            id="semantic-type-confirm-notes"
            data-testid="semantic-type-confirm-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace and the semantic-type-detail row."
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
            data-testid="semantic-type-confirm-error"
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
            data-testid="semantic-type-confirm-cancel"
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
            data-testid="semantic-type-confirm-submit"
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
            {submitting ? "Confirming…" : "Confirm type"}
          </button>
        </footer>
      </form>
    </div>
  );
}
