/**
 * EntityStitchStrategyBanner — L8 strategy status banner
 * (Sub-wave D, 2026-06-07; Catalog-mirror Wave 2 Sub-wave C banner
 * posture refresh 2026-06-10).
 *
 * Surfaces the 3 inference strategies (name_match / sample_overlap /
 * schema_shape) with honest 4-state posture for ``name_match`` (per
 * spec §7), a Wave 2-driven 3-state for ``schema_shape`` (substrate
 * empty → "productive (when columns available)" + currently-quiet
 * qualifier; substrate populated → ``productive · per-connector``),
 * and ``configured · empty-upstream`` for ``sample_overlap``
 * (NoopSampler today).
 *
 * Mirrors the L6 strategy banner shape — reuses the shared
 * :class:`CapabilityBadges` component for badge rendering.
 */

"use client";

import { CapabilityBadges } from "../onboard/CapabilityBadges";
import type { EntityStitchStrategyStatus } from "../../lib/entity-stitches";

export interface EntityStitchStrategyBannerProps {
  rows: EntityStitchStrategyStatus[];
}

export function EntityStitchStrategyBanner({
  rows,
}: EntityStitchStrategyBannerProps): JSX.Element {
  return (
    <section
      data-testid="entity-stitch-strategy-status-banner"
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
          L8 inference strategy status
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
          Which cross-source stitching strategies can produce proposals
          in this tenant today. ``productive · L5-dependent`` =
          NameMatch anchor wired against L5&apos;s confirmed types (3rd
          cross-axis chain, reuses L6&apos;s
          ``ConfirmedSemanticTypeReader`` Protocol);
          ``productive · fuzzy-only`` = NameMatch L5-anchor off but
          fuzzy-name path runs (always entity_kind=other);
          ``configured · L5-disabled`` / ``configured · awaiting-L5-types``
          = anchor wired but upstream not ready;
          ``productive · per-connector`` = SchemaShape wired AND
          catalog-mirror Wave 2 substrate
          (``projection_catalog_tables``) has ≥1 folded entry for
          this tenant (csv_local / dbt / snowflake productive today);
          ``productive (when columns available)`` = SchemaShape wired
          but no per-table catalog imports have landed yet —
          currently quiet until an extractor-registered connector
          runs against a source;
          ``configured · empty-upstream`` = SampleOverlap wired against
          a NoopSampler today;
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
          gap: 10,
        }}
      >
        {rows.map((row) => (
          <li
            key={row.strategy}
            data-testid={`entity-stitch-strategy-row-${row.strategy}`}
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
                id={`entity-stitch-${row.strategy}`}
                status={row.badge}
                statusNote={row.note}
              />
              {row.badgeLabelOverride ? (
                <span
                  className="wb-mono"
                  data-testid={`entity-stitch-strategy-override-${row.strategy}`}
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
