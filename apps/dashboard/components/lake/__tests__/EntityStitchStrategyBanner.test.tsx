/**
 * EntityStitchStrategyBanner component tests — L8 Sub-wave D
 * (2026-06-07; Catalog-mirror Wave 2 Sub-wave C posture refresh
 * 2026-06-10).
 *
 * Pins:
 *   * Renders all 3 strategy rows with the override label and the
 *     CapabilityBadges integration.
 *   * 4-state name_match posture honestly labeled (productive ·
 *     L5-dependent / configured · awaiting-L5-types / configured ·
 *     L5-disabled / productive · fuzzy-only).
 *   * schema_shape Wave 2 posture honestly labeled:
 *     - "productive (when columns available)" when Wave 2 substrate
 *       (``projection_catalog_tables``) is empty (currently quiet
 *       qualifier kept)
 *     - "productive · per-connector" when substrate has folded
 *       ``catalog_table_imported`` entries for this tenant
 *   * sample_overlap empty-upstream posture renders the
 *     ``configured · empty-upstream`` override.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EntityStitchStrategyBanner } from "../EntityStitchStrategyBanner";
import type { EntityStitchStrategyStatus } from "../../../lib/entity-stitches";

describe("EntityStitchStrategyBanner — 4-state name_match", () => {
  it("renders productive · L5-dependent state when anchor is wired to confirmed types", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · L5-dependent",
        note: "Productive — anchor reading 4 confirmed L5 semantic types",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "productive (when columns available)",
        note: "Configured — currently quiet — awaits per-column catalog imports",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-row-name_match"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-strategy-override-name_match"),
    ).toHaveTextContent("productive · L5-dependent");
  });

  it("renders productive · fuzzy-only when anchor sub-knob is off", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · fuzzy-only",
        note: "Productive — fuzzy-name path only",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-name_match"),
    ).toHaveTextContent("productive · fuzzy-only");
  });

  it("renders configured · awaiting-L5-types when L5 confirmed-type count is 0", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: true,
        productive: true,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-L5-types",
        note: "Configured but awaiting L5 confirmations",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        note: "Configured",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-name_match"),
    ).toHaveTextContent("configured · awaiting-L5-types");
  });

  it("renders configured · L5-disabled when anchor is wired but L5 master switch is off", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: true,
        productive: true,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · L5-disabled",
        note: "Configured but L5 is disabled",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        note: "Configured",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-name_match"),
    ).toHaveTextContent("configured · L5-disabled");
  });
});

describe("EntityStitchStrategyBanner — schema_shape Wave 2 posture", () => {
  it("renders 'productive (when columns available)' override when Wave 2 substrate is empty (currently-quiet qualifier kept)", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "productive (when columns available)",
        note: "Configured — productive on bare catalog metadata. Currently quiet — awaits per-table catalog imports.",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-schema_shape"),
    ).toHaveTextContent("productive (when columns available)");
  });

  it("renders 'productive · per-connector' override when Wave 2 substrate has folded entries", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · per-connector",
        note: "Productive — reading 7 folded catalog_table_imported entries from projection_catalog_tables.",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-schema_shape"),
    ).toHaveTextContent("productive · per-connector");
  });
});

describe("EntityStitchStrategyBanner — sample_overlap empty-upstream", () => {
  it("renders the 'configured · empty-upstream' override when NoopSampler is wired", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "sample_overlap",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · empty-upstream",
        note: "Configured but empty-upstream — NoopSampler returns empty sets",
      },
      {
        strategy: "schema_shape",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-override-sample_overlap"),
    ).toHaveTextContent("configured · empty-upstream");
  });
});

describe("EntityStitchStrategyBanner — render shape", () => {
  it("renders all three strategy rows", () => {
    const rows: EntityStitchStrategyStatus[] = [
      {
        strategy: "name_match",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "sample_overlap",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
      {
        strategy: "schema_shape",
        configured: false,
        productive: false,
        badge: "disabled",
        note: "Disabled",
      },
    ];
    render(<EntityStitchStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("entity-stitch-strategy-status-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-strategy-row-name_match"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-strategy-row-sample_overlap"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-strategy-row-schema_shape"),
    ).toBeInTheDocument();
  });
});
