"use client";
/**
 * ExperimentsTable — list of experiments (proposed → run → resolved).
 *
 * Each row shows:
 *  * the headline metric + the proposed change
 *  * expected vs observed delta
 *  * outcome (or "in flight" if not yet resolved)
 *  * receipt
 *  * "approve" + "reject" buttons that fire the production write path
 *    (`/api/v1/experiments/{id}/{approve,reject}`) for in-flight
 *    experiments. The buttons are W2.A9 ApproveExperimentButton +
 *    RejectExperimentButton, which surface their own pending/error
 *    state inline.
 */

import { useCallback, useState } from "react";
import type {
  ExperimentRow,
  ExperimentOutcome,
} from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";
import { ApproveExperimentButton } from "./ApproveExperimentButton";
import { RejectExperimentButton } from "./RejectExperimentButton";

export interface ExperimentsTableProps {
  rows: ExperimentRow[];
  /**
   * Optional legacy callback. When provided the table fires it after a
   * successful approve / reject so parents can refresh polling state.
   * Newer callers can read the status directly from the per-row data
   * after the next `/api/research/refresh` tick.
   */
  onResolve?: (experimentId: string, outcome: ExperimentOutcome) => void;
  filteringByPerson?: boolean;
}

export function ExperimentsTable({
  rows,
  onResolve,
  filteringByPerson,
}: ExperimentsTableProps) {
  const [resolved, setResolved] = useState<
    Record<string, ExperimentOutcome>
  >({});

  const handleApprove = useCallback(
    (experimentId: string) => {
      setResolved((m) => ({ ...m, [experimentId]: "keep" }));
      onResolve?.(experimentId, "keep");
    },
    [onResolve],
  );
  const handleReject = useCallback(
    (experimentId: string) => {
      setResolved((m) => ({ ...m, [experimentId]: "discard" }));
      onResolve?.(experimentId, "discard");
    },
    [onResolve],
  );

  if (rows.length === 0) {
    return (
      <p
        data-testid="experiments-empty"
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No experiments {filteringByPerson ? "for this viewer" : "yet"}. Once
        the autoresearch loop ticks they land here within a cycle.
      </p>
    );
  }

  return (
    <table
      data-testid="experiments-table"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontFamily: "var(--wb-font-serif)",
      }}
    >
      <thead>
        <tr
          style={{
            textAlign: "left",
            fontSize: "var(--wb-text-xs)",
            color: "var(--wb-color-hash-gray)",
            borderBottom: "1px solid var(--wb-color-rule-line)",
          }}
        >
          <th style={{ padding: "8px 4px" }}>position</th>
          <th style={{ padding: "8px 4px" }}>metric</th>
          <th style={{ padding: "8px 4px" }}>proposed change</th>
          <th style={{ padding: "8px 4px" }}>expected</th>
          <th style={{ padding: "8px 4px" }}>observed</th>
          <th style={{ padding: "8px 4px" }}>outcome</th>
          <th style={{ padding: "8px 4px" }}>receipt</th>
          <th style={{ padding: "8px 4px" }}></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const optimistic = resolved[r.experimentId] ?? null;
          const effectiveOutcome = optimistic ?? r.outcome;
          const inFlight = effectiveOutcome === null;
          const change = r.proposedChange ?? {};
          const changeKind =
            typeof change.kind === "string" ? change.kind : "(change)";
          const changeTarget =
            typeof change.target === "string"
              ? change.target
              : "";
          return (
            <tr
              key={r.experimentId}
              data-testid={`experiment-${r.experimentId}`}
              data-outcome={effectiveOutcome ?? "pending"}
              style={{
                borderBottom: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <td style={{ padding: "8px 4px", fontWeight: 500 }}>
                {r.position}
              </td>
              <td style={{ padding: "8px 4px", fontStyle: "italic" }}>
                {r.headlineMetric}
              </td>
              <td style={{ padding: "8px 4px" }}>
                <span className="wb-mono" style={{ fontSize: 12 }}>
                  {changeKind}
                  {changeTarget ? ` · ${changeTarget}` : ""}
                </span>
              </td>
              <td
                className="wb-mono"
                style={{ padding: "8px 4px" }}
              >
                {r.expectedDelta >= 0 ? "+" : ""}
                {r.expectedDelta.toFixed(3)}
              </td>
              <td
                className="wb-mono"
                style={{
                  padding: "8px 4px",
                  color:
                    r.observedDelta === null
                      ? "var(--wb-color-hash-gray)"
                      : r.observedDelta >= 0
                        ? "var(--wb-color-botanical-green)"
                        : "var(--wb-color-aged-ink)",
                }}
              >
                {r.observedDelta === null
                  ? "—"
                  : `${r.observedDelta >= 0 ? "+" : ""}${r.observedDelta.toFixed(3)}`}
              </td>
              <td style={{ padding: "8px 4px" }}>
                <OutcomeChip outcome={effectiveOutcome} pending={false} />
              </td>
              <td style={{ padding: "8px 4px" }}>
                <Receipt
                  hash={r.receipt.hash}
                  source={r.receipt.source}
                  owner={r.receipt.owner}
                  classification={r.receipt.classification}
                  compact
                />
              </td>
              <td style={{ padding: "8px 4px" }}>
                {inFlight ? (
                  <span style={{ display: "inline-flex", gap: 6 }}>
                    <ApproveExperimentButton
                      experimentId={r.experimentId}
                      onResolved={() => handleApprove(r.experimentId)}
                      compact
                    />
                    <RejectExperimentButton
                      experimentId={r.experimentId}
                      onResolved={() => handleReject(r.experimentId)}
                      compact
                    />
                  </span>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function OutcomeChip({
  outcome,
  pending,
}: {
  outcome: ExperimentOutcome | null;
  pending: boolean;
}) {
  if (pending) {
    return (
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        resolving…
      </span>
    );
  }
  if (outcome === "keep") {
    return (
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-botanical-green)",
          letterSpacing: "0.06em",
        }}
      >
        kept
      </span>
    );
  }
  if (outcome === "discard") {
    return (
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-aged-ink)",
          letterSpacing: "0.06em",
          fontStyle: "italic",
        }}
      >
        discarded
      </span>
    );
  }
  return (
    <span
      className="wb-mono"
      style={{
        fontSize: 11,
        color: "var(--wb-color-hash-gray)",
        letterSpacing: "0.06em",
      }}
    >
      in flight
    </span>
  );
}

