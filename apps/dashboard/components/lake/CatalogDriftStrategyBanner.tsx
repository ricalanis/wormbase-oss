/**
 * CatalogDriftStrategyBanner — L2 strategy status banner
 * (Sub-wave D, 2026-06-09; Catalog-mirror Wave 2 Sub-wave C banner
 * posture refresh 2026-06-10).
 *
 * Surfaces the 3 inference strategies (table_set / column_set /
 * column_type) with honest per-strategy posture computed in
 * ``lib/catalog-drift.ts``.
 *
 * Wave 2 (Sub-wave C, 2026-06-10) unified the posture matrix across
 * all 3 strategies — they now share the same 3-state logic keyed on
 * the Wave 2 substrate (``projection_catalog_tables`` from migration
 * v029, populated by the Sub-wave B ``catalog_table_imported`` fold):
 *
 *   * disabled (master or sub-knob off)
 *   * configured · awaiting-per-table-entries (both on, no
 *     ``catalog_table_imported`` entries folded for this tenant —
 *     usually means the source's connector doesn't have a registered
 *     ``catalog_column_extractor``)
 *   * productive · per-connector (both on, ≥1 entry exists —
 *     csv_local / dbt / snowflake productive today; opaque-secret
 *     connectors land entries with ``columns=()`` per the
 *     honest-empty-upstream doctrine)
 *
 * Mirrors L1's SourceCandidateStrategyBanner shape — reuses the
 * shared :class:`CapabilityBadges` component for badge rendering.
 */

"use client";

import { CapabilityBadges } from "../onboard/CapabilityBadges";
import type { CatalogDriftStrategyStatus } from "../../lib/catalog-drift";

export interface CatalogDriftStrategyBannerProps {
  rows: CatalogDriftStrategyStatus[];
}

export function CatalogDriftStrategyBanner({
  rows,
}: CatalogDriftStrategyBannerProps): JSX.Element {
  return (
    <section
      data-testid="catalog-drift-strategy-status-banner"
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
          L2 inference strategy status
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
          Which catalog-drift detection strategies can produce
          proposals in this tenant today. All three strategies share
          the same 3-state matrix keyed on the catalog-mirror Wave 2
          substrate (``projection_catalog_tables``).
          ``productive · per-connector`` = the strategy is wired AND
          at least one ``catalog_table_imported`` entry has been
          folded for this tenant — csv_local / dbt / snowflake emit
          per-table entries today via the catalog_column_extractors
          registry;
          ``configured · awaiting-per-table-entries`` = the strategy
          is wired and the Wave 2 substrate is ready, but no entries
          have been folded — usually means the source&apos;s connector
          doesn&apos;t yet have a registered extractor (see
          ``apps/worm-core/src/wormbase_core/catalog_column_extractors.py``);
          ``disabled`` = master switch or sub-knob off. L2 does NOT
          add a peer-L-axis cross-axis chain — its
          ``CatalogSnapshotReader`` reads catalog-mirror substrate,
          NOT other axes&apos; confirmed outputs (cross-axis chain
          count stays at 3).
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
            data-testid={`catalog-drift-strategy-row-${row.strategy}`}
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
                id={`catalog-drift-${row.strategy}`}
                status={row.badge}
                statusNote={row.note}
              />
              {row.badgeLabelOverride ? (
                <span
                  className="wb-mono"
                  data-testid={`catalog-drift-strategy-override-${row.strategy}`}
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
