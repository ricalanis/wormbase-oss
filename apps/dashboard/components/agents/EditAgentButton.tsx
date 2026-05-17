/**
 * EditAgentButton — admin-only metadata edit on /people/agents/[id]
 * (final wave item #5, 2026-05-13).
 *
 * Renders an "Edit" chip that opens an inline modal with display_name +
 * description fields pre-filled from the agent's current state. The
 * admin can change either or both fields; Submit is disabled unless at
 * least one field has been edited AND the new value differs from the
 * current one.
 *
 * Modal pattern mirrors RevokeAgentButton (Path 5): backdrop + panel +
 * autoFocus on first input + Cancel / Confirm row at the bottom. The
 * Confirm button posts to ``updateAgentMetadata`` (server action) which
 * forwards to worm-core's PATCH /api/v1/write_actions/agents_metadata/
 * {agent_id} endpoint. One ``agent_metadata_updated`` PEVR cycle is
 * written per submission; preserves agent_id continuity so audit trails
 * do not fork.
 *
 * On success, the server action handles revalidatePath + redirect back
 * to the detail page with ``?edited=1``. On failure, the modal renders
 * the error inline so the admin can adjust and re-submit.
 *
 * Pure-presentational client component — receives the server action
 * (``updateAction``) and the agent's current values as props.
 */
"use client";

import { useState, useTransition } from "react";

import type { UpdateAgentMetadataResult } from "../../app/(app)/people/agents/[id]/actions";

type UpdateAction = (input: {
  agentId: string;
  displayName: string | null;
  description: string | null;
  reason: string | null;
}) => Promise<UpdateAgentMetadataResult>;

export interface EditAgentButtonProps {
  agentId: string;
  currentDisplayName: string;
  currentDescription: string | null;
  updateAction: UpdateAction;
}

const CHIP_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "var(--wb-color-paper, #f6f1e7)",
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

const TEXTAREA_STYLE: React.CSSProperties = {
  ...INPUT_STYLE,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  minHeight: 80,
  resize: "vertical",
};

const CONFIRM_BTN: React.CSSProperties = {
  padding: "6px 14px",
  border: "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
  background: "var(--wb-color-botanical-green, #3c7a55)",
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

export function EditAgentButton(props: EditAgentButtonProps): JSX.Element {
  const { agentId, currentDisplayName, currentDescription, updateAction } =
    props;
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState(currentDisplayName);
  const [description, setDescription] = useState(currentDescription ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const trimmedDisplayName = displayName.trim();
  const displayNameChanged = trimmedDisplayName !== currentDisplayName.trim();
  const descriptionChanged = description !== (currentDescription ?? "");
  const hasNewDisplayName = displayNameChanged && trimmedDisplayName.length > 0;
  const hasNewDescription = descriptionChanged;
  const canSubmit = hasNewDisplayName || hasNewDescription;

  function handleOpen(): void {
    setError(null);
    setDisplayName(currentDisplayName);
    setDescription(currentDescription ?? "");
    setReason("");
    setOpen(true);
  }

  function handleClose(): void {
    if (isPending) return;
    setOpen(false);
    setError(null);
  }

  function handleSubmit(): void {
    if (!canSubmit || isPending) return;
    startTransition(async () => {
      const result = await updateAction({
        agentId,
        displayName: hasNewDisplayName ? trimmedDisplayName : null,
        description: hasNewDescription ? description : null,
        reason: reason.trim() || null,
      });
      if (!result.ok) {
        setError(result.error ?? "edit failed");
        return;
      }
      setOpen(false);
      // Reload onto the detail page so the new values render. The
      // server action also revalidates; this is a defensive client-side
      // hop for the case where the caller invokes updateAction directly
      // without the form-bound wrapper.
      window.location.href = `/people/agents/${encodeURIComponent(agentId)}?edited=1`;
    });
  }

  return (
    <>
      <button
        type="button"
        data-testid="agent-detail-edit-button"
        onClick={handleOpen}
        style={CHIP_STYLE}
        title="Edit display name / description — preserves agent_id."
      >
        Edit (admin)
      </button>
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-agent-modal-title"
          data-testid="agent-detail-edit-modal"
          style={MODAL_BACKDROP}
          onClick={handleClose}
        >
          <div style={MODAL_PANEL} onClick={(e) => e.stopPropagation()}>
            <h2
              id="edit-agent-modal-title"
              style={{
                margin: 0,
                fontSize: 22,
                fontWeight: 500,
                fontFamily: "var(--wb-font-serif, Georgia, serif)",
              }}
            >
              Edit agent metadata
            </h2>
            <p
              style={{
                margin: 0,
                fontSize: 14,
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray, #6b6256)",
              }}
            >
              Updates the agent&apos;s display name and / or description.
              The agent_id stays the same — grants, subscriptions, and
              audit history remain attached. Written as one
              <code
                style={{
                  fontFamily:
                    "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  margin: "0 4px",
                }}
              >
                agent_metadata_updated
              </code>
              PEVR cycle on the ledger.
            </p>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
              }}
            >
              <span>Display name</span>
              <input
                type="text"
                data-testid="agent-detail-edit-display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                style={INPUT_STYLE}
                autoFocus
                disabled={isPending}
                maxLength={80}
              />
            </label>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
              }}
            >
              <span>Description</span>
              <textarea
                data-testid="agent-detail-edit-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                style={TEXTAREA_STYLE}
                disabled={isPending}
                maxLength={2048}
                placeholder="(optional) what this agent does, who it serves, scope notes"
              />
            </label>
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
                data-testid="agent-detail-edit-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={INPUT_STYLE}
                disabled={isPending}
                maxLength={512}
                placeholder="e.g. rebrand for clarity post-onboarding"
              />
            </label>
            {error ? (
              <p
                data-testid="agent-detail-edit-error"
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
            <p
              data-testid="agent-detail-edit-validity"
              style={{
                margin: 0,
                fontSize: 12,
                fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                color: canSubmit
                  ? "var(--wb-color-botanical, #2d6a4f)"
                  : "var(--wb-color-hash-gray, #6b6256)",
              }}
            >
              {canSubmit
                ? "Ready to submit."
                : "Change at least one field (display name or description) to submit."}
            </p>
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
                data-testid="agent-detail-edit-cancel"
                onClick={handleClose}
                style={CANCEL_BTN}
                disabled={isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="agent-detail-edit-confirm"
                onClick={handleSubmit}
                style={{
                  ...CONFIRM_BTN,
                  opacity: canSubmit && !isPending ? 1 : 0.45,
                  cursor:
                    canSubmit && !isPending ? "pointer" : "not-allowed",
                }}
                disabled={!canSubmit || isPending}
              >
                {isPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
