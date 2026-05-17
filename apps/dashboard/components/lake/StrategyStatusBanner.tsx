/**
 * StrategyStatusBanner — honest productivity gauges for the L3
 * inference strategies (L3 Sub-wave D, 2026-05-29).
 *
 * Surfaces Sub-wave C concerns #1 + #2 on the operator-facing surface:
 *
 *   * dbt_manifest is the only productive strategy today.
 *   * naming_heuristic is configured but column lists are empty in the
 *     Wave 1 catalog mirror — yields zero edges.
 *   * sample_overlap is configured-but-stubbed (NoopSampler) when
 *     enabled; telemetry increments but no edges land.
 *
 * The banner ships the truth so operators flipping env knobs see the
 * real productive surface area, not a misleading "all green" view.
 */

import type { LineageStrategyStatus } from "../../lib/lineage";

export interface StrategyStatusBannerProps {
  rows: LineageStrategyStatus[];
}

function badgeFor(row: LineageStrategyStatus): {
  label: string;
  color: string;
  testIdSuffix: string;
} {
  if (row.productive) {
    return {
      label: "productive",
      color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      testIdSuffix: "productive",
    };
  }
  if (row.configured) {
    return {
      label: "configured · stubbed",
      color: "var(--wb-color-sepia-warning-deep, #b6741c)",
      testIdSuffix: "stubbed",
    };
  }
  return {
    label: "disabled",
    color: "var(--wb-color-hash-gray, #7c7569)",
    testIdSuffix: "disabled",
  };
}

export function StrategyStatusBanner({
  rows,
}: StrategyStatusBannerProps): JSX.Element {
  return (
    <section
      data-testid="strategy-status-banner"
      style={{
        border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
        background: "var(--wb-color-paper-deep, #f4eedb)",
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          L3 inference strategy status
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink, #2a2620)",
            fontSize: 13,
            maxWidth: 720,
          }}
        >
          Which inference strategies can produce lineage edges in this
          tenant today. ``productive`` = wired against real data;
          ``configured · stubbed`` = env knob on but the underlying
          implementation is a no-op (sampler stub or empty column lists);
          ``disabled`` = env knob off.
        </p>
      </header>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {rows.map((row) => {
          const badge = badgeFor(row);
          return (
            <li
              key={row.strategy}
              data-testid={`strategy-status-row-${row.strategy}`}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(160px, 200px) 160px 1fr",
                gap: 12,
                alignItems: "baseline",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
                color: "var(--wb-color-aged-ink, #2a2620)",
              }}
            >
              <code
                className="wb-mono"
                style={{
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink, #2a2620)",
                }}
              >
                {row.strategy}
              </code>
              <span
                className="wb-mono"
                data-testid={`strategy-status-badge-${row.strategy}-${badge.testIdSuffix}`}
                style={{
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: badge.color,
                }}
              >
                {badge.label}
              </span>
              <span style={{ fontStyle: "italic" }}>{row.note}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
