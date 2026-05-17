"use client";
/**
 * ReplayButton — strict-replay a data product against pinned source-hashes.
 *
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * Posts to /api/v1/data-products/{id}/replay (which proxies to worm-core).
 * worm-core re-hashes the original artifact bytes; if the hash matches
 * the recorded one, a fresh `data_product_generated` PEVR cycle is
 * written and the response carries `matches_original=true`.
 *
 * Three on-screen states after a replay attempt:
 *
 * - match: "✓ bit-identical content_hash" — the autoresearch
 *   reproducibility guarantee held.
 * - mismatch (status 409): "✗ content_hash drift" — the dashboard
 *   surfaces both expected + actual hashes for audit.
 * - transport error (status 502 or network): generic error + retry.
 *
 * The match badge is the load-bearing affordance: it's the visible
 * proof that "deterministic replay" is real, not advertised.
 */
import { useState } from "react";

interface ReplayResponse {
  data_product_id: string;
  run_id: string;
  content_hash: string;
  expected_content_hash: string;
  matches_original: boolean;
  entry_ids: string[];
}

interface MismatchResponse {
  error: "replay_mismatch";
  message: string;
}

interface Props {
  dataProductId: string;
  /** When true, the page reloads after a successful match so the new
   * run row surfaces in the run-history table. Default true; tests
   * disable this. */
  reloadOnMatch?: boolean;
}

type State =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "match"; response: ReplayResponse }
  | { kind: "mismatch"; message: string }
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

const NOTE_STYLE: React.CSSProperties = {
  margin: "8px 0 0",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
};

export function ReplayButton({ dataProductId, reloadOnMatch = true }: Props) {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function handleReplay() {
    setState({ kind: "busy" });
    try {
      const res = await fetch(
        `/api/v1/data-products/${encodeURIComponent(dataProductId)}/replay`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strict: true, generated_by: "replay" }),
        },
      );
      if (res.status === 409) {
        const body = (await res.json()) as MismatchResponse;
        setState({ kind: "mismatch", message: body.message });
        return;
      }
      if (!res.ok) {
        const text = await res.text();
        setState({ kind: "error", message: `replay failed (${res.status}): ${text}` });
        return;
      }
      const body = (await res.json()) as ReplayResponse;
      setState({ kind: "match", response: body });
      if (reloadOnMatch && body.matches_original) {
        // Surface the new run row in the parent's run-history table.
        // Defer slightly so the test harness can observe the badge first.
        setTimeout(() => window.location.reload(), 600);
      }
    } catch (err) {
      setState({
        kind: "error",
        message: `replay failed: ${(err as Error).message}`,
      });
    }
  }

  const busy = state.kind === "busy";

  return (
    <div data-testid="replay-button-container">
      <button
        onClick={handleReplay}
        disabled={busy}
        data-testid="replay-button"
        style={{
          ...BUTTON_STYLE,
          background: busy
            ? "var(--wb-color-paper-deep)"
            : BUTTON_STYLE.background,
          cursor: busy ? "wait" : "pointer",
        }}
      >
        {busy ? "Replaying…" : "Replay against pinned source-hashes"}
      </button>

      {state.kind === "match" ? (
        <p
          data-testid="replay-match-badge"
          style={{ ...NOTE_STYLE, color: "var(--wb-color-ink-green, #2a7a3c)" }}
        >
          ✓ bit-identical content_hash ·{" "}
          <span className="wb-mono">
            {state.response.content_hash.slice(0, 16)}…
          </span>
        </p>
      ) : null}

      {state.kind === "mismatch" ? (
        <p
          data-testid="replay-mismatch-badge"
          style={{
            ...NOTE_STYLE,
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          ✗ content_hash drift detected · {state.message}
        </p>
      ) : null}

      {state.kind === "error" ? (
        <p
          data-testid="replay-error"
          style={{
            ...NOTE_STYLE,
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          {state.message}
        </p>
      ) : null}
    </div>
  );
}
