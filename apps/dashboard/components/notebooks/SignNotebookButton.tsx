"use client";
/**
 * SignNotebookButton — sign (publish) a notebook with a per-Person
 * signature receipt.
 *
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * "Sign" is the governance-framed publish: the signed-in admin Person
 * attests that this notebook run is canonical. The dashboard route
 * handler binds `signed_by` to the current admin Person id (no
 * client-supplied signer) and worm-core writes
 * `emit_notebook_published` plus returns a deterministic per-Person
 * signature receipt.
 *
 * The receipt's `signature_hash` is shown on screen as the audit-grade
 * attestation badge. It's deterministic (same inputs → same hash), so
 * a replay of the ledger reproduces the same surface.
 *
 * The button is disabled when:
 * - there is no run to sign (the user must run the notebook first),
 * - or the notebook is already signed at this version.
 */
import { useState } from "react";

interface SignatureReceipt {
  notebook_id: string;
  run_id: string;
  owner_person_id: string;
  version: string;
  signed_by: string;
  signature_hash: string;
  entry_ids: string[];
}

interface SignResponse {
  notebook_id: string;
  signature_receipt: SignatureReceipt;
  entry_ids: string[];
}

interface Props {
  notebookId: string;
  /** The run to sign. Falsy disables the button with "no run to sign". */
  runId: string | null;
  /** Defaults to "1". The dashboard surfaces the version chip alongside. */
  version?: string;
  /** Owner Person id for the signature payload — typically the
   * current user. */
  ownerPersonId: string | null;
  /** When already signed at this version, render the existing receipt
   * and disable the button. */
  alreadySigned?: boolean;
  /** Optional pre-existing signature hash to render when already signed. */
  existingSignatureHash?: string | null;
  /** Reload page after success so the version chip / status surface
   * the new state. Defaults true; tests override. */
  reloadOnSuccess?: boolean;
}

type State =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "signed"; receipt: SignatureReceipt }
  | { kind: "error"; message: string };

const BUTTON_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  padding: "8px 16px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
  cursor: "pointer",
  borderRadius: 0,
};

export function SignNotebookButton({
  notebookId,
  runId,
  version = "1",
  ownerPersonId,
  alreadySigned = false,
  existingSignatureHash = null,
  reloadOnSuccess = true,
}: Props) {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function handleSign() {
    if (!runId) {
      setState({
        kind: "error",
        message: "No run to sign — run the notebook first.",
      });
      return;
    }
    setState({ kind: "busy" });
    try {
      const res = await fetch(
        `/api/v1/notebooks/${encodeURIComponent(notebookId)}/sign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            run_id: runId,
            owner_person_id: ownerPersonId,
            version,
          }),
        },
      );
      if (!res.ok) {
        const text = await res.text();
        setState({
          kind: "error",
          message: `sign failed (${res.status}): ${text}`,
        });
        return;
      }
      const body = (await res.json()) as SignResponse;
      setState({ kind: "signed", receipt: body.signature_receipt });
      if (reloadOnSuccess) {
        setTimeout(() => window.location.reload(), 600);
      }
    } catch (err) {
      setState({
        kind: "error",
        message: `sign failed: ${(err as Error).message}`,
      });
    }
  }

  const busy = state.kind === "busy";
  const disabled = busy || !runId || alreadySigned;

  // Render path 1: already-signed; show the existing receipt as proof.
  if (alreadySigned && state.kind !== "signed") {
    return (
      <div data-testid="sign-button-container">
        <button
          disabled
          data-testid="sign-button"
          style={{
            ...BUTTON_STYLE,
            background: "var(--wb-color-paper-deep)",
            cursor: "not-allowed",
            opacity: 0.6,
          }}
        >
          Signed · v{version}
        </button>
        {existingSignatureHash ? (
          <p
            data-testid="sign-existing-receipt"
            style={{
              margin: "8px 0 0",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            receipt:{" "}
            <span className="wb-mono">
              {existingSignatureHash.slice(0, 16)}…
            </span>
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid="sign-button-container">
      <button
        onClick={handleSign}
        disabled={disabled}
        data-testid="sign-button"
        style={{
          ...BUTTON_STYLE,
          background: busy
            ? "var(--wb-color-paper-deep)"
            : BUTTON_STYLE.background,
          cursor: busy ? "wait" : disabled ? "not-allowed" : "pointer",
          opacity: disabled && !busy ? 0.6 : 1,
        }}
      >
        {busy ? "Signing…" : `Sign as canonical · v${version}`}
      </button>

      {!runId ? (
        <p
          data-testid="sign-needs-run"
          style={{
            margin: "8px 0 0",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Run the notebook before signing.
        </p>
      ) : null}

      {state.kind === "signed" ? (
        <p
          data-testid="sign-receipt"
          style={{
            margin: "8px 0 0",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            color: "var(--wb-color-ink-green, #2a7a3c)",
          }}
        >
          ✓ signed · receipt:{" "}
          <span className="wb-mono">
            {state.receipt.signature_hash.slice(0, 16)}…
          </span>
        </p>
      ) : null}

      {state.kind === "error" ? (
        <p
          data-testid="sign-error"
          style={{
            margin: "8px 0 0",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          {state.message}
        </p>
      ) : null}
    </div>
  );
}
