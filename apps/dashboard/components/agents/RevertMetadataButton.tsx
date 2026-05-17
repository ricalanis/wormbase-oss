/**
 * RevertMetadataButton — admin-only metadata revert on /people/agents/[id]
 * (post-rest path #4, 2026-05-13).
 *
 * Renders a "Revert metadata" chip that opens an inline confirmation
 * modal. On confirm, posts to ``revertAgentMetadata`` (server action)
 * which forwards to worm-core's POST
 * /api/v1/write_actions/agents_metadata_revert/{agent_id} endpoint.
 *
 * The endpoint emits a NEW ``agent_metadata_updated`` PEVR cycle whose
 * display_name + description carry the prior state (forward-only
 * doctrine: revert = new entry, not mutation). The agent_id is
 * preserved so audit trails, grants, and subscriptions stay attached.
 *
 * Visibility: the parent page renders this button only when at least
 * one prior ``agent_metadata_updated`` exists for the agent (so a
 * revert target is well-defined). The button's own props carry that
 * derivation (``hasPriorUpdate``) so the component stays
 * presentational and the visibility logic is testable in isolation.
 *
 * Modal pattern mirrors ``RevokeAgentButton``: backdrop + panel +
 * Cancel / Confirm row. No confirm-text friction (revert is reversible
 * via another revert — much lower-stakes than revoke).
 */
"use client";

import { useState, useTransition } from "react";

import type { RevertAgentMetadataResult } from "../../app/(app)/people/agents/[id]/actions";

type RevertAction = (input: {
  agentId: string;
  reason: string | null;
}) => Promise<RevertAgentMetadataResult>;

export interface RevertMetadataButtonProps {
  agentId: string;
  /** Display name of the agent — shown in the confirm modal copy. */
  currentDisplayName: string;
  /** Whether a prior agent_metadata_updated exists. When false, the
   * button does not render (revert has no target). */
  hasPriorUpdate: boolean;
  revertAction: RevertAction;
}

const CHIP_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 12,
  letterSpacing: "0.04em",
  cursor: "pointer",
};

const MODAL_BACKDROP: React.CSSProperties = {
  position: "fixed",
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  background: "rgba(0,0,0,0.35)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
};

const MODAL_PANEL: React.CSSProperties = {
  background: "var(--wb-color-paper, #f6f1e7)",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  padding: 24,
  maxWidth: 520,
  width: "90%",
  display: "flex",
  flexDirection: "column",
  gap: 12,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
};

const INPUT_STYLE: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 13,
};

const CONFIRM_BTN: React.CSSProperties = {
  padding: "6px 14px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "var(--wb-color-aged-ink, #4b3f2f)",
  color: "var(--wb-color-paper, #f6f1e7)",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 12,
  cursor: "pointer",
};

const CANCEL_BTN: React.CSSProperties = {
  padding: "6px 14px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 12,
  cursor: "pointer",
};

export function RevertMetadataButton(
  props: RevertMetadataButtonProps,
): JSX.Element | null {
  const { agentId, currentDisplayName, hasPriorUpdate, revertAction } = props;
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  if (!hasPriorUpdate) {
    // No prior agent_metadata_updated → nothing to revert. Render
    // nothing so the page chrome stays clean.
    return null;
  }

  function handleOpen(): void {
    setError(null);
    setReason("");
    setOpen(true);
  }

  function handleClose(): void {
    if (isPending) return;
    setOpen(false);
    setError(null);
  }

  function handleConfirm(): void {
    if (isPending) return;
    startTransition(async () => {
      const result = await revertAction({
        agentId,
        reason: reason.trim() || null,
      });
      if (!result.ok) {
        setError(result.error ?? "revert failed");
        return;
      }
      setOpen(false);
      window.location.href = `/people/agents/${encodeURIComponent(agentId)}?reverted=1`;
    });
  }

  return (
    <>
      <button
        type="button"
        data-testid="agent-detail-revert-button"
        onClick={handleOpen}
        style={CHIP_STYLE}
        title="Revert metadata — emits a new ledger entry that restores the prior display_name and description."
      >
        Revert (admin)
      </button>
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="revert-metadata-modal-title"
          data-testid="agent-detail-revert-modal"
          style={MODAL_BACKDROP}
          onClick={handleClose}
        >
          <div style={MODAL_PANEL} onClick={(e) => e.stopPropagation()}>
            <h2
              id="revert-metadata-modal-title"
              style={{
                margin: 0,
                fontSize: 22,
                fontWeight: 500,
                fontFamily: "var(--wb-font-serif, Georgia, serif)",
              }}
            >
              Revert agent metadata
            </h2>
            <p
              style={{
                margin: 0,
                fontSize: 14,
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray, #6b6256)",
              }}
            >
              Revert{" "}
              <strong
                data-testid="agent-detail-revert-target-name"
                style={{
                  fontFamily:
                    "var(--wb-font-mono, ui-monospace, monospace)",
                }}
              >
                {currentDisplayName}
              </strong>{" "}
              to its previous metadata? This emits a new ledger entry —
              the prior <code
                style={{
                  fontFamily:
                    "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
              >agent_metadata_updated</code> stays in the audit trail
              unchanged (forward-only doctrine). The agent_id is preserved.
            </p>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
              }}
            >
              <span>Reason (audit note, optional)</span>
              <input
                type="text"
                data-testid="agent-detail-revert-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={INPUT_STYLE}
                autoFocus
                disabled={isPending}
                maxLength={512}
                placeholder="e.g. accidental edit; restoring prior state"
              />
            </label>
            {error ? (
              <p
                data-testid="agent-detail-revert-error"
                style={{
                  margin: 0,
                  padding: "8px 10px",
                  border: "1px solid var(--wb-color-error, #b03a2e)",
                  background: "rgba(176,58,46,0.06)",
                  color: "var(--wb-color-error, #b03a2e)",
                  fontSize: 12,
                  fontFamily:
                    "var(--wb-font-mono, ui-monospace, monospace)",
                }}
              >
                {error}
              </p>
            ) : null}
            <div
              style={{
                display: "flex",
                gap: 10,
                justifyContent: "flex-end",
                marginTop: 6,
              }}
            >
              <button
                type="button"
                data-testid="agent-detail-revert-cancel"
                onClick={handleClose}
                style={CANCEL_BTN}
                disabled={isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="agent-detail-revert-confirm"
                onClick={handleConfirm}
                style={{
                  ...CONFIRM_BTN,
                  opacity: isPending ? 0.45 : 1,
                  cursor: isPending ? "not-allowed" : "pointer",
                }}
                disabled={isPending}
              >
                {isPending ? "Reverting…" : "Revert metadata"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
