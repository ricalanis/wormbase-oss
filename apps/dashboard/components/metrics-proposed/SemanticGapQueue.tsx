/**
 * SemanticGapQueue — admin queue for ``semantic_gap_proposed`` rows.
 *
 * Wave 3 Task 5. Renders the unresolved gap rows as a table; each row
 * has a "Promote" action that opens an inline form (metric_name +
 * expression + domain_id, pre-filled from the gap's
 * ``proposedMetricName`` when set). Submitting calls the
 * ``promoteSemanticGap`` server action.
 *
 * Production contract:
 *   * NO direct ledger write — submission routes through the server
 *     action which forwards to worm-core's HTTP write API. Failure
 *     paths render the error inline.
 *   * Honest empty state lives on the page (this component stays a
 *     pure list).
 */

"use client";

import { useState, useTransition } from "react";

import type { SemanticGapRow } from "../../lib/metrics-proposed";

type Action = (
  semanticGapEntryId: string,
  metricName: string,
  metricExpression: string,
  domainId: string,
) => Promise<{ ok: boolean; error?: string }>;

export interface SemanticGapQueueProps {
  rows: SemanticGapRow[];
  /** Server action injected by the page. Tests pass a stub. */
  promoteAction: Action;
  /** Optional callback fired after a successful promotion. The page
   *  wires this to ``router.refresh()`` so the queue re-fetches. */
  onPromoted?: (entryId: string) => void;
}

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray, #6b6256)",
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  whiteSpace: "nowrap",
};

const TD_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 14,
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.06))",
  verticalAlign: "top",
};

const BUTTON_PRIMARY: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 12,
  border: "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
  background: "var(--wb-color-botanical-green, #3c7a55)",
  color: "var(--wb-color-paper, #f6f1e7)",
  cursor: "pointer",
};

const BUTTON_GHOST: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 12,
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  cursor: "pointer",
};

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16);
  } catch {
    return iso;
  }
}

function reasonLabel(
  r: "no_match" | "low_confidence" | "ambiguous",
): string {
  if (r === "no_match") return "no match";
  if (r === "low_confidence") return "low confidence";
  return "ambiguous";
}

interface PromoteFormState {
  metricName: string;
  metricExpression: string;
  domainId: string;
}

export function SemanticGapQueue({
  rows,
  promoteAction,
  onPromoted,
}: SemanticGapQueueProps): JSX.Element {
  const [openRowId, setOpenRowId] = useState<string | null>(null);
  const [form, setForm] = useState<PromoteFormState>({
    metricName: "",
    metricExpression: "",
    domainId: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function openModal(row: SemanticGapRow): void {
    setOpenRowId(row.id);
    setForm({
      metricName: row.proposedMetricName ?? "",
      metricExpression: "",
      domainId: "",
    });
    setError(null);
  }

  function closeModal(): void {
    setOpenRowId(null);
    setError(null);
  }

  function submit(rowId: string): void {
    setError(null);
    startTransition(async () => {
      const result = await promoteAction(
        rowId,
        form.metricName.trim(),
        form.metricExpression.trim(),
        form.domainId.trim(),
      );
      if (result.ok) {
        setOpenRowId(null);
        if (onPromoted) onPromoted(rowId);
      } else {
        setError(result.error ?? "unknown error");
      }
    });
  }

  return (
    <div data-testid="semantic-gap-queue">
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          background: "var(--wb-color-paper, #f6f1e7)",
        }}
      >
        <thead>
          <tr>
            <th style={TH_STYLE}>Question</th>
            <th style={TH_STYLE}>Reason</th>
            <th style={TH_STYLE}>Proposed metric</th>
            <th style={TH_STYLE}>Agent</th>
            <th style={TH_STYLE}>Proposed at</th>
            <th style={TH_STYLE}>Status</th>
            <th style={TH_STYLE}>Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              data-testid={`gap-row-${r.id}`}
              style={{
                background:
                  openRowId === r.id
                    ? "var(--wb-color-paper-warm, rgba(60,122,85,0.05))"
                    : undefined,
              }}
            >
              <td style={TD_STYLE} data-testid={`gap-question-${r.id}`}>
                {r.nlQuestion || <em>(no question text)</em>}
              </td>
              <td style={TD_STYLE} data-testid={`gap-reason-${r.id}`}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {reasonLabel(r.reason)}
                </span>
              </td>
              <td style={TD_STYLE} data-testid={`gap-metric-${r.id}`}>
                {r.proposedMetricName ?? <em>—</em>}
              </td>
              <td style={TD_STYLE} data-testid={`gap-agent-${r.id}`}>
                <code style={{ fontSize: 12 }}>{r.agentId || "—"}</code>
              </td>
              <td style={TD_STYLE} data-testid={`gap-ts-${r.id}`}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {fmtTimestamp(r.proposedAt)}
                </span>
              </td>
              <td style={TD_STYLE} data-testid={`gap-status-${r.id}`}>
                {r.status}
              </td>
              <td style={TD_STYLE}>
                <button
                  type="button"
                  data-testid={`gap-promote-${r.id}`}
                  onClick={() => openModal(r)}
                  style={BUTTON_PRIMARY}
                  disabled={pending && openRowId === r.id}
                >
                  Promote
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {openRowId !== null ? (
        <PromoteModal
          rowId={openRowId}
          form={form}
          error={error}
          pending={pending}
          onChange={setForm}
          onSubmit={() => submit(openRowId)}
          onCancel={closeModal}
        />
      ) : null}
    </div>
  );
}

function PromoteModal({
  rowId,
  form,
  error,
  pending,
  onChange,
  onSubmit,
  onCancel,
}: {
  rowId: string;
  form: PromoteFormState;
  error: string | null;
  pending: boolean;
  onChange: (next: PromoteFormState) => void;
  onSubmit: () => void;
  onCancel: () => void;
}): JSX.Element {
  return (
    <div
      data-testid={`promote-modal-${rowId}`}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        style={{
          background: "var(--wb-color-paper, #f6f1e7)",
          padding: "24px 28px",
          minWidth: 460,
          maxWidth: 560,
          border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          Promote semantic gap to metric
        </h3>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Registers a new metric the agent can query in future. Routes
          through worm-core; the ledger write lands as an
          ``external_metric_imported`` PEVR cycle.
        </p>
        <label
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
          }}
        >
          Metric name
          <input
            type="text"
            data-testid="promote-metric-name"
            value={form.metricName}
            onChange={(e) =>
              onChange({ ...form, metricName: e.target.value })
            }
            style={{
              padding: "6px 8px",
              border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
              fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              fontSize: 13,
            }}
            placeholder="e.g. weekly_churn_rate"
          />
        </label>
        <label
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
          }}
        >
          Metric expression
          <textarea
            data-testid="promote-metric-expression"
            value={form.metricExpression}
            onChange={(e) =>
              onChange({ ...form, metricExpression: e.target.value })
            }
            rows={3}
            style={{
              padding: "6px 8px",
              border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
              fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              fontSize: 13,
            }}
            placeholder="e.g. SUM(churned) / COUNT(active_customers)"
          />
        </label>
        <label
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
          }}
        >
          Domain id
          <input
            type="text"
            data-testid="promote-domain-id"
            value={form.domainId}
            onChange={(e) => onChange({ ...form, domainId: e.target.value })}
            style={{
              padding: "6px 8px",
              border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
              fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              fontSize: 13,
            }}
            placeholder="UUID"
          />
        </label>
        {error ? (
          <p
            data-testid="promote-error"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-error, #b03a2e)",
              background: "var(--wb-color-error-bg, rgba(176,58,46,0.08))",
              padding: "8px 10px",
              border: "1px solid var(--wb-color-error, #b03a2e)",
            }}
          >
            {error}
          </p>
        ) : null}
        <div
          style={{ display: "flex", gap: 10, marginTop: 6, alignItems: "baseline" }}
        >
          <button
            type="submit"
            data-testid="promote-submit"
            disabled={pending}
            style={{
              ...BUTTON_PRIMARY,
              opacity: pending ? 0.6 : 1,
              cursor: pending ? "default" : "pointer",
            }}
          >
            {pending ? "Promoting…" : "Promote metric"}
          </button>
          <button
            type="button"
            data-testid="promote-cancel"
            onClick={onCancel}
            style={BUTTON_GHOST}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
