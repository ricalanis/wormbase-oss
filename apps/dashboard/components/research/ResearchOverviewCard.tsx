"use client";
/**
 * ResearchOverviewCard — tenant-wide autoresearch summary card.
 *
 * Three numerical cells (totals / kept / win rate), a table of top movers,
 * a footer note linking to /trace for receipts. Everything is read-only.
 */

import type { ResearchOverview } from "../../lib/ledger-client.types";

export function ResearchOverviewCard({
  overview,
}: {
  overview: ResearchOverview;
}) {
  return (
    <section
      data-testid="research-overview"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderTop: "1px solid var(--wb-color-rule-line)",
        paddingTop: 24,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Tenant overview
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-lg)",
            fontWeight: 500,
          }}
        >
          Experiments &amp; movers
        </h2>
      </header>

      <div
        data-testid="research-totals"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 24,
          padding: "16px 0",
          borderTop: "1px solid var(--wb-color-paper-edge)",
          borderBottom: "1px solid var(--wb-color-paper-edge)",
        }}
      >
        <Cell
          label="experiments run"
          value={overview.totalExperiments}
          testId="overview-total"
        />
        <Cell
          label="kept · discarded"
          value={`${overview.totalKept} · ${overview.totalDiscarded}`}
          testId="overview-keep-discard"
        />
        <Cell
          label="win rate"
          value={
            overview.winRate === null
              ? "—"
              : `${(overview.winRate * 100).toFixed(0)}%`
          }
          testId="overview-winrate"
        />
      </div>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          top movers
        </span>
        {overview.topMovers.length === 0 ? (
          <p
            data-testid="overview-no-movers"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            No headline-metric movement yet — once experiments resolve, they land here.
          </p>
        ) : (
          <table
            data-testid="overview-movers-table"
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
                <th style={{ padding: "8px 4px" }}>delta</th>
                <th style={{ padding: "8px 4px" }}>kept</th>
                <th style={{ padding: "8px 4px" }}>discarded</th>
              </tr>
            </thead>
            <tbody>
              {overview.topMovers.map((m) => (
                <tr
                  key={`${m.position}::${m.metricId}`}
                  data-testid={`mover-${m.position}-${m.metricId}`}
                  style={{
                    borderBottom: "1px solid var(--wb-color-paper-edge)",
                  }}
                >
                  <td
                    style={{
                      padding: "8px 4px",
                      fontWeight: 500,
                    }}
                  >
                    {m.position}
                  </td>
                  <td style={{ padding: "8px 4px", fontStyle: "italic" }}>
                    {m.metricId}
                  </td>
                  <td
                    className="wb-mono"
                    style={{
                      padding: "8px 4px",
                      color:
                        m.delta >= 0
                          ? "var(--wb-color-botanical-green)"
                          : "var(--wb-color-aged-ink)",
                    }}
                  >
                    {m.delta >= 0 ? "+" : ""}
                    {m.delta.toFixed(3)}
                  </td>
                  <td className="wb-mono" style={{ padding: "8px 4px" }}>
                    {m.experimentsKept}
                  </td>
                  <td className="wb-mono" style={{ padding: "8px 4px" }}>
                    {m.experimentsDiscarded}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  );
}

function Cell({
  label,
  value,
  testId,
}: {
  label: string;
  value: number | string;
  testId: string;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 28,
          fontWeight: 500,
          letterSpacing: "-0.01em",
        }}
      >
        {value}
      </span>
    </div>
  );
}
