/**
 * TemplateLibrary — pure presentational list of promoted query templates.
 *
 * One row per ``query_template_promoted`` Reactivity firing. Shows the
 * canonical NL intent (cluster key), the cached QuerySpec preview, the
 * number of outcomes that drove the promotion, the cluster's mean
 * quality_score, and the cache hit count.
 *
 * Each template's ``promoted_from_outcome_ids`` is a full-provenance
 * list back to the observed outcomes — surfaced as a small footer
 * pill list. The dashboard's compounding-loop story: outcomes →
 * cluster → template → cache hits.
 *
 * Empty state is handled by the page itself.
 */

"use client";

import type { QueryTemplateRow } from "../../lib/query-improvement";

export interface TemplateLibraryProps {
  rows: QueryTemplateRow[];
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
  return `${Math.round(num * 100)}%`;
}

function fmtQuerySpec(spec: Record<string, unknown>): string {
  // Compact one-line repr: ``metric=revenue_total time_grain=quarter``.
  // The full spec is one click away via the trace chain; the list
  // surface stays scannable.
  const entries = Object.entries(spec);
  if (entries.length === 0) return "—";
  return entries
    .slice(0, 3)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
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

export function TemplateLibrary({
  rows,
}: TemplateLibraryProps): JSX.Element {
  return (
    <div data-testid="query-templates-table" style={{ overflowX: "auto" }}>
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
              Intent
            </th>
            <th scope="col" style={TH_STYLE}>
              Query spec
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              Cluster
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              Hits
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              Quality
            </th>
            <th scope="col" style={TH_STYLE}>
              Promoted
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              data-testid={`query-templates-row-${row.id}`}
            >
              <td style={TD_STYLE}>
                <div
                  style={{
                    fontFamily: "var(--wb-font-serif, Georgia, serif)",
                    fontWeight: 500,
                  }}
                >
                  {row.nlIntent}
                </div>
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    marginTop: 2,
                  }}
                >
                  domain: {row.domainId.slice(0, 8)}…
                </div>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
                data-testid={`query-templates-spec-${row.id}`}
              >
                {fmtQuerySpec(row.querySpec)}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                }}
                data-testid={`query-templates-cluster-${row.id}`}
              >
                {row.promotedFromOutcomeIds.length}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                }}
                data-testid={`query-templates-hits-${row.id}`}
              >
                {row.hitCount}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 13,
                  color: "var(--wb-color-botanical, #2d6a4f)",
                }}
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
                {fmtTimestamp(row.promotedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
