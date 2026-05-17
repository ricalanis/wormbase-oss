"use client";
/**
 * RejectExperimentButton — W2.A9.
 *
 * Mirror of ApproveExperimentButton. POSTs to
 * ``/api/v1/experiments/{id}/reject`` which writes
 * ``emit_experiment_resolved`` with ``outcome=discard``.
 */

import { useCallback, useState } from "react";

export interface RejectExperimentButtonProps {
  experimentId: string;
  rationale?: string;
  observedDelta?: number;
  onResolved?: (result: RejectResult) => void;
  label?: string;
  compact?: boolean;
}

export interface RejectResult {
  experimentId: string;
  outcome: "discard";
  rationale: string;
  entryIds: string[];
}

type Status = "idle" | "pending" | "ok" | "error";

export function RejectExperimentButton({
  experimentId,
  rationale,
  observedDelta,
  onResolved,
  label = "reject",
  compact = false,
}: RejectExperimentButtonProps) {
  const [status, setStatus] = useState<Status>("idle");
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleClick = useCallback(async () => {
    setStatus("pending");
    setErrMsg(null);
    try {
      const res = await fetch(
        `/api/v1/experiments/${encodeURIComponent(experimentId)}/reject`,
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
        outcome: "discard",
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
    status === "pending" ? "rejecting…" : status === "ok" ? "rejected" : label;

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <button
        type="button"
        data-testid={`reject-experiment-${experimentId}`}
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
          color: "var(--wb-color-aged-ink)",
          cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.7 : 1,
          fontStyle: status === "ok" ? "italic" : "normal",
        }}
      >
        {renderedLabel}
      </button>
      {status === "error" && errMsg ? (
        <span
          data-testid={`reject-experiment-${experimentId}-error`}
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
