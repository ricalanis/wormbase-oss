/**
 * RevokeAgentButton — admin-only destructive action on /people/agents/[id]
 * (v1.4 follow-up — Path 5).
 *
 * Renders a "Revoke" chip that opens an inline confirmation modal. The
 * admin must type the agent's display_name to confirm before the revoke
 * server action is invoked. This is intentional friction — revoking an
 * agent cascades over every active grant, which is security-critical.
 *
 * On success, the parent page revalidates via the server action's
 * `revalidatePath` calls and the admin is redirected back to the
 * agents list with the revoked grant count surfaced in the URL.
 *
 * Pure-presentational client component — receives the server action
 * (`revokeAction`) and the expected confirm text (`expectedConfirm`,
 * usually `agent.displayName`) as props. Returns to the parent's
 * caller via the action's redirect; on failure, surfaces the error
 * text inline.
 */
"use client";

import { useState, useTransition } from "react";

import type { RevokeAgentResult } from "../../app/(app)/people/agents/[id]/actions";

type RevokeAction = (agentId: string) => Promise<RevokeAgentResult>;

export interface RevokeAgentButtonProps {
  agentId: string;
  expectedConfirm: string;
  revokeAction: RevokeAction;
}

const CHIP_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  border: "1px solid var(--wb-color-error, #b03a2e)",
  background: "transparent",
  color: "var(--wb-color-error, #b03a2e)",
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
  maxWidth: 480,
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
  border: "1px solid var(--wb-color-error, #b03a2e)",
  background: "var(--wb-color-error, #b03a2e)",
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

export function RevokeAgentButton(
  props: RevokeAgentButtonProps,
): JSX.Element {
  const { agentId, expectedConfirm, revokeAction } = props;
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const matches = confirmText.trim() === expectedConfirm.trim();

  function handleOpen(): void {
    setError(null);
    setConfirmText("");
    setOpen(true);
  }

  function handleClose(): void {
    if (isPending) return;
    setOpen(false);
    setConfirmText("");
    setError(null);
  }

  function handleConfirm(): void {
    if (!matches || isPending) return;
    startTransition(async () => {
      const result = await revokeAction(agentId);
      if (!result.ok) {
        setError(result.error ?? "revoke failed");
        return;
      }
      // Success — server action handles redirect / revalidate. Reload
      // to the agents list as a fallback in case the action returns
      // (it should redirect, but guard the case where it doesn't).
      setOpen(false);
      window.location.href = `/people/agents?revoked=${encodeURIComponent(agentId)}&grants=${
        result.revokedGrantCount ?? 0
      }`;
    });
  }

  return (
    <>
      <button
        type="button"
        data-testid="agent-detail-revoke-button"
        onClick={handleOpen}
        style={CHIP_STYLE}
        title="Revoke all grants — cascades over every active grant for this agent."
      >
        Revoke (admin)
      </button>
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="revoke-agent-modal-title"
          data-testid="agent-detail-revoke-modal"
          style={MODAL_BACKDROP}
          onClick={handleClose}
        >
          <div
            style={MODAL_PANEL}
            onClick={(e) => e.stopPropagation()}
          >
            <h2
              id="revoke-agent-modal-title"
              style={{
                margin: 0,
                fontSize: 22,
                fontWeight: 500,
                fontFamily: "var(--wb-font-serif, Georgia, serif)",
              }}
            >
              Revoke agent
            </h2>
            <p
              style={{
                margin: 0,
                fontSize: 14,
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray, #6b6256)",
              }}
            >
              This cascades a revoke over every active grant this agent
              currently holds. The action is recorded as one ledger PEVR
              cycle per grant and is replay-deterministic. The agent
              itself stays in the directory (preserves audit history).
            </p>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
              }}
            >
              <span>
                Type{" "}
                <strong
                  data-testid="agent-detail-revoke-expected-confirm"
                  style={{
                    fontFamily:
                      "var(--wb-font-mono, ui-monospace, monospace)",
                  }}
                >
                  {expectedConfirm}
                </strong>{" "}
                to confirm.
              </span>
              <input
                type="text"
                data-testid="agent-detail-revoke-confirm-input"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                style={INPUT_STYLE}
                autoFocus
                disabled={isPending}
              />
            </label>
            {error ? (
              <p
                data-testid="agent-detail-revoke-error"
                style={{
                  margin: 0,
                  padding: "8px 10px",
                  border:
                    "1px solid var(--wb-color-error, #b03a2e)",
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
                data-testid="agent-detail-revoke-cancel"
                onClick={handleClose}
                style={CANCEL_BTN}
                disabled={isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="agent-detail-revoke-confirm"
                onClick={handleConfirm}
                style={{
                  ...CONFIRM_BTN,
                  opacity: matches && !isPending ? 1 : 0.45,
                  cursor: matches && !isPending ? "pointer" : "not-allowed",
                }}
                disabled={!matches || isPending}
              >
                {isPending ? "Revoking…" : "Revoke all grants"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
