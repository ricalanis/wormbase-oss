/**
 * SourceCandidateStrategyBanner — L1 strategy status banner
 * (Sub-wave D, 2026-06-08).
 *
 * Surfaces the 3 inference strategies (kpi_gap / channel_mention /
 * complementarity) with honest per-strategy posture computed in
 * ``lib/source-candidates.ts``:
 *
 *   * ``kpi_gap`` — 4-state matrix:
 *     - disabled (master or sub-knob off)
 *     - configured · awaiting-kpi-tree-population (both on, 0 KPI nodes)
 *     - productive · KPI-dependent (both on, ≥1 KPI node)
 *
 *   * ``channel_mention`` — 3-state matrix:
 *     - disabled (master or sub-knob off)
 *     - configured · empty-upstream (both on, 0 silver-conversation rows)
 *     - productive · silver-dependent (both on, ≥1 silver-conversation row)
 *
 *   * ``complementarity`` — 3-state matrix:
 *     - disabled (master or sub-knob off)
 *     - configured · awaiting-first-source (both on, 0 connected sources)
 *     - productive · portfolio-dependent (both on, ≥1 connected source)
 *
 * Mirrors the L8 EntityStitchStrategyBanner shape — reuses the shared
 * :class:`CapabilityBadges` component for badge rendering.
 */

"use client";

import { CapabilityBadges } from "../onboard/CapabilityBadges";
import type { SourceCandidateStrategyStatus } from "../../lib/source-candidates";

export interface SourceCandidateStrategyBannerProps {
  rows: SourceCandidateStrategyStatus[];
}

export function SourceCandidateStrategyBanner({
  rows,
}: SourceCandidateStrategyBannerProps): JSX.Element {
  return (
    <section
      data-testid="source-candidate-strategy-status-banner"
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
          L1 inference strategy status
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
          Which source-discovery strategies can produce candidates in
          this tenant today. ``productive · KPI-dependent`` = kpi_gap
          reading the populated KPI tree (proposes connector kinds
          inferred from the missing KPI's name);
          ``configured · awaiting-kpi-tree-population`` = kpi_gap
          wired but KPI tree empty;
          ``productive · silver-dependent`` = channel_mention scanning
          the last 1000 silver-conversation rows (24h window) for a
          30-pattern regex bank of connector mentions;
          ``configured · empty-upstream`` = channel_mention wired but
          no silver-conversation rows landed yet;
          ``productive · portfolio-dependent`` = complementarity
          reading the connected-source portfolio and proposing gap
          fillers; ``configured · awaiting-first-source`` =
          complementarity wired but no sources connected yet;
          ``disabled`` = the master switch or sub-knob is off. L1 does
          NOT add a peer-L-axis cross-axis chain — its strategies read
          lightweight platform projections, not other axes&apos;
          confirmed outputs (cross-axis chain count stays at 3).
        </p>
      </header>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {rows.map((row) => (
          <li
            key={row.strategy}
            data-testid={`source-candidate-strategy-row-${row.strategy}`}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(160px, 200px) 1fr",
              gap: 12,
              alignItems: "flex-start",
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
                paddingTop: 2,
              }}
            >
              {row.strategy}
            </code>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <CapabilityBadges
                kind="policy"
                id={`source-candidate-${row.strategy}`}
                status={row.badge}
                statusNote={row.note}
              />
              {row.badgeLabelOverride ? (
                <span
                  className="wb-mono"
                  data-testid={`source-candidate-strategy-override-${row.strategy}`}
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: "var(--wb-color-sepia-warning-deep, #b6741c)",
                  }}
                >
                  {row.badgeLabelOverride}
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
