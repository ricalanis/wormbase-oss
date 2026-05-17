/**
 * SourceCandidatePromoteModal — L1 Promote dialog for
 * /lake/source-candidates (Sub-wave D, 2026-06-08).
 *
 * Lighter than the rejection modal: only an optional notes textarea.
 * The action POSTs the promote to worm-core via the server action.
 *
 * L1-specific warning: a successful promote dual-writes. It emits BOTH
 * the L1 ``source_candidate_promoted`` audit entry AND triggers the
 * existing source-builder flow to emit a downstream ``source_proposed``
 * entry — the promoted candidate enters the standard source-pipeline
 * lifecycle automatically. The modal surfaces this so admins know the
 * promote is not just an audit gesture.
 */

"use client";

import { useEffect, useRef, useState } from "react";

export interface SourceCandidatePromoteModalProps {
  candidateId: string;
  open: boolean;
  onClose: () => void;
  onSubmit: (
    candidateId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

export function SourceCandidatePromoteModal({
  candidateId,
  open,
  onClose,
  onSubmit,
}: SourceCandidatePromoteModalProps): JSX.Element | null {
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
      candidateId,
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
      aria-label="Promote source candidate"
      data-testid="source-candidate-promote-modal"
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
            Promote source candidate
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
            }}
          >
            Approve this candidate for the source pipeline
          </h2>
          <code
            className="wb-mono"
            data-testid="source-candidate-promote-candidate-id"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            candidate_id={candidateId}
          </code>
        </header>

        {/* Dual-write warning — L1-specific. Promote does NOT just
            file an audit entry; it triggers the source-builder to
            emit a downstream ``source_proposed``, which enters the
            standard /sources lifecycle. */}
        <section
          data-testid="source-candidate-promote-warning"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
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
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            Promote triggers downstream pipeline
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
            Approving this candidate dual-writes: emits the L1
            ``source_candidate_promoted`` audit entry AND triggers the
            existing source-builder to emit a downstream
            ``source_proposed`` entry. The candidate enters the
            standard /sources lifecycle automatically; an admin will
            need to complete the connector configuration there.
          </p>
        </section>

        <label
          htmlFor="source-candidate-promote-notes"
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
            id="source-candidate-promote-notes"
            data-testid="source-candidate-promote-notes"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2048}
            placeholder="Optional annotation surfaced on /trace and the source-candidate detail row."
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
            data-testid="source-candidate-promote-error"
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
            data-testid="source-candidate-promote-cancel"
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
            data-testid="source-candidate-promote-submit"
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
            {submitting ? "Promoting…" : "Promote candidate"}
          </button>
        </footer>
      </form>
    </div>
  );
}
