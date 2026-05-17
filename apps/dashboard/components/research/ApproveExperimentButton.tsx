"use client";
/**
 * ApproveExperimentButton — W2.A9.
 *
 * The /research per-experiment "approve" button. Wraps the API call to
 * ``POST /api/v1/experiments/{id}/approve`` (which writes
 * ``emit_experiment_resolved`` with ``outcome=keep``) and surfaces a
 * disabled / pending / error state inline.
 *
 * The existing in-table buttons in `ExperimentsTable.tsx` continue to
 * call the legacy `/api/research/resolve` shim. This component is the
 * production write path: it flows through worm-core's PEVR cycle, not
 * the dashboard-side INSERT shortcut. Use it from any new approve UX
 * (drawer, bulk-approve, modal) and from per-row buttons once the
 * legacy shim is retired.
 */

import { useCallback, useState } from "react";

export interface ApproveExperimentButtonProps {
  experimentId: string;
  /**
   * Free-form prose recorded in the resolution's rationale. Surfaces in
   * the activity feed + ledger as the "why" for this approve.
   */
  rationale?: string;
  /**
   * Operator-supplied observed delta (defaults to 0 if not known). The
   * autoresearch loop normally records this; the manual approve path
   * accepts an override for the rare case where the operator has
   * corrected metric data the loop didn't see.
   */
  observedDelta?: number;
  /**
   * Optional callback fired on successful resolve. Lets parents refresh
   * a polled view or close a drawer.
   */
  onResolved?: (result: ApproveResult) => void;
  /**
   * Override the button label. Defaults to "approve".
   */
  label?: string;
  /**
   * Compact variant for inline placement in tables. Slightly smaller
   * padding + uppercase label.
   */
  compact?: boolean;
}

export interface ApproveResult {
  experimentId: string;
  outcome: "keep";
  rationale: string;
  entryIds: string[];
}

type Status = "idle" | "pending" | "ok" | "error";

export function ApproveExperimentButton({
  experimentId,
  rationale,
  observedDelta,
  onResolved,
  label = "approve",
  compact = false,
}: ApproveExperimentButtonProps) {
  const [status, setStatus] = useState<Status>("idle");
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleClick = useCallback(async () => {
    setStatus("pending");
    setErrMsg(null);
    try {
      const res = await fetch(
        `/api/v1/experiments/${encodeURIComponent(experimentId)}/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rationale,
            observedDelta,
          }),
        },
      );
      const text = await res.text();
      if (!res.ok) {
        setStatus("error");
        setErrMsg(text.slice(0, 200) || `HTTP ${res.status}`);
        return;
      }
      const json = (text ? JSON.parse(text) : {}) as {
        experiment_id?: string;
        outcome?: string;
        rationale?: string;
        entry_ids?: string[];
      };
      setStatus("ok");
      onResolved?.({
        experimentId: json.experiment_id ?? experimentId,
        outcome: "keep",
        rationale: json.rationale ?? rationale ?? "",
        entryIds: json.entry_ids ?? [],
      });
    } catch (err) {
      setStatus("error");
      setErrMsg((err as Error).message);
    }
  }, [experimentId, rationale, observedDelta, onResolved]);

  const disabled = status === "pending";
  const renderedLabel =
    status === "pending" ? "approving…" : status === "ok" ? "approved" : label;

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <button
        type="button"
        data-testid={`approve-experiment-${experimentId}`}
        data-status={status}
        onClick={handleClick}
        disabled={disabled}
        style={{
          fontFamily: "var(--wb-font-mono)",
          fontSize: compact ? 11 : 12,
          padding: compact ? "4px 8px" : "6px 12px",
          border: "1px solid var(--wb-color-rule-line)",
          background:
            status === "ok"
              ? "var(--wb-color-paper-edge)"
              : "var(--wb-color-paper)",
          color:
            status === "ok"
              ? "var(--wb-color-botanical-green)"
              : "var(--wb-color-aged-ink)",
          cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.7 : 1,
        }}
      >
        {renderedLabel}
      </button>
      {status === "error" && errMsg ? (
        <span
          data-testid={`approve-experiment-${experimentId}-error`}
          className="wb-mono"
          style={{
            fontSize: 10,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {errMsg}
        </span>
      ) : null}
    </span>
  );
}
