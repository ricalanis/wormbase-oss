/**
 * OutcomeLedgerView — pure presentational list of query outcomes.
 *
 * One row per ``query_outcome_recorded`` ledger entry — shows the
 * natural-language question, the quality score, the used/useful pair,
 * and a click-through to the agent_query chain at
 * ``/trace/agent_query/[agentQueryId]`` (Task 3's SOC-2 chain view).
 *
 * Each row also exposes the user_correction string when the
 * outcome was marked useful=false but used=true — making the
 * compounding loop's "agent learns from corrections" mechanic
 * legible without a separate detail page.
 *
 * Empty state is handled by the page itself; this component stays
 * a pure list (consistent with AgentTable / CatalogTable).
 */

"use client";

import Link from "next/link";

import type { QueryOutcomeRow } from "../../lib/query-improvement";

export interface OutcomeLedgerViewProps {
  rows: QueryOutcomeRow[];
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

function fmtScore(s: string): string {
  const num = Number.parseFloat(s);
  if (Number.isNaN(num)) return s;
  // Outcomes carry a Decimal in [0.0, 1.0]; show 2-dp percent for
  // human readability while keeping the raw string available below.
  return `${Math.round(num * 100)}%`;
}

function scoreColor(s: string): string {
  const num = Number.parseFloat(s);
  if (Number.isNaN(num)) return "var(--wb-color-hash-gray, #6b6256)";
  if (num >= 0.9) return "var(--wb-color-botanical, #2d6a4f)";
  if (num >= 0.5) return "var(--wb-color-hash-gray, #6b6256)";
  return "var(--wb-color-warning, #b45309)";
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

export function OutcomeLedgerView({
  rows,
}: OutcomeLedgerViewProps): JSX.Element {
  return (
    <div data-testid="query-outcomes-table" style={{ overflowX: "auto" }}>
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
              Used
            </th>
            <th scope="col" style={TH_STYLE}>
              Useful
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              Quality
            </th>
            <th scope="col" style={TH_STYLE}>
              Recorded
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              data-testid={`query-outcomes-row-${row.id}`}
            >
              <td style={TD_STYLE}>
                <Link
                  href={`/trace/agent_query/${row.agentQueryId}`}
                  data-testid={`query-outcomes-row-link-${row.id}`}
                  style={{
                    color: "var(--wb-color-botanical, #2d6a4f)",
                    textDecoration: "none",
                    fontWeight: 500,
                  }}
                >
                  {row.nlQuestion}
                </Link>
                {row.userCorrection ? (
                  <div
                    style={{
                      fontFamily: "var(--wb-font-serif, Georgia, serif)",
                      fontStyle: "italic",
                      fontSize: 13,
                      color: "var(--wb-color-warning, #b45309)",
                      marginTop: 4,
                    }}
                    data-testid={`query-outcomes-correction-${row.id}`}
                  >
                    user: “{row.userCorrection}”
                  </div>
                ) : null}
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    marginTop: 2,
                  }}
                >
                  audit_trail: {row.agentQueryId.slice(0, 8)}…
                </div>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`query-outcomes-used-${row.id}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                  }}
                >
                  {row.used ? "yes" : "no"}
                </span>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`query-outcomes-useful-${row.id}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: row.useful
                      ? "var(--wb-color-botanical, #2d6a4f)"
                      : "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.useful ? "yes" : "no"}
                </span>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 13,
                  color: scoreColor(row.qualityScore),
                }}
                data-testid={`query-outcomes-quality-${row.id}`}
              >
                {fmtScore(row.qualityScore)}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.recordedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
