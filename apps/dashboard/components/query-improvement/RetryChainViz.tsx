/**
 * RetryChainViz — surface ``semantic_gap_proposed`` events alongside the
 * compounding-loop panel.
 *
 * Per-outcome retry trees (``query_correction_suggested`` chains) live in
 * Task 3's recursive /trace/agent_query/[id] view — the compounding-loop
 * surface focuses on the *gap-proposal* signal: questions the agent
 * couldn't answer with the existing catalog. These are the natural-
 * language seeds for sibling Task 5's metric-proposal admin queue.
 *
 * For each gap, the link directs the operator to
 * ``/lake/metrics-proposed`` where the gap can be promoted to a real
 * metric. Empty state: when no gaps have been proposed, the page
 * renders an honest empty state at the parent (the panel exists but
 * folds away).
 */

"use client";

import Link from "next/link";

import type { SemanticGapRow } from "../../lib/query-improvement";

export interface RetryChainVizProps {
  rows: SemanticGapRow[];
}

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16);
  } catch {
    return iso;
  }
}

function reasonColor(reason: SemanticGapRow["reason"]): string {
  switch (reason) {
    case "no_match":
      return "var(--wb-color-warning, #b45309)";
    case "low_confidence":
      return "var(--wb-color-hash-gray, #6b6256)";
    case "ambiguous":
      return "var(--wb-color-botanical, #2d6a4f)";
  }
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

export function RetryChainViz({ rows }: RetryChainVizProps): JSX.Element {
  return (
    <div data-testid="query-gaps-table" style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <thead>
          <tr>
            <th scope="col" style={TH_STYLE}>
              Question
            </th>
            <th scope="col" style={TH_STYLE}>
              Reason
            </th>
            <th scope="col" style={TH_STYLE}>
              Proposed metric
            </th>
            <th scope="col" style={TH_STYLE}>
              Proposed
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-testid={`query-gaps-row-${row.id}`}>
              <td style={TD_STYLE}>
                <Link
                  href="/lake/metrics-proposed"
                  data-testid={`query-gaps-row-link-${row.id}`}
                  style={{
                    color: "var(--wb-color-botanical, #2d6a4f)",
                    textDecoration: "none",
                    fontWeight: 500,
                  }}
                >
                  {row.nlQuestion}
                </Link>
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    marginTop: 2,
                  }}
                >
                  agent: {row.agentId.slice(0, 8)}…
                </div>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`query-gaps-reason-${row.reason}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: reasonColor(row.reason),
                  }}
                >
                  {row.reason.replace("_", " ")}
                </span>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
                data-testid={`query-gaps-proposed-${row.id}`}
              >
                {row.proposedMetricName ?? "—"}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.proposedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
