/**
 * /lake/schema-impact searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`SchemaImpactFilter` conversion + the
 * filter → chip-map projection used by :class:`ActiveFilterChips`.
 */
import { describe, expect, it, vi } from "vitest";

// The page imports server-only modules at the top level (
// ``getCurrentCompanyId`` reads cookies, the accessors instantiate
// pg.Pool). We mock them all to a no-op so the test only exercises
// the pure helpers we export from the page.
vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/schema-impact", () => ({
  getProposedSchemaImpacts: vi.fn(async () => []),
  getConfirmedSchemaImpacts: vi.fn(async () => []),
  getRejectedSchemaImpacts: vi.fn(async () => []),
  getSchemaImpactStrategyStatus: vi.fn(async () => []),
  getL3DependencyState: vi.fn(async () => ({
    l3Enabled: false,
    confirmedEdgeCount: 0,
  })),
  getL5DependencyState: vi.fn(async () => ({
    l5Enabled: false,
    confirmedSemanticTypeCount: 0,
  })),
  getL6DependencyState: vi.fn(async () => ({
    l6Enabled: false,
    confirmedClassificationCount: 0,
  })),
}));
vi.mock("../actions", () => ({
  confirmSchemaImpact: vi.fn(),
  rejectSchemaImpact: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/schema-impact searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseSchemaImpactFilter({})).toBeUndefined();
    expect(__test__.parseSchemaImpactFilter({ unknown: "x" })).toBeUndefined();
  });

  it("parses upstream_lineage_edge_id (R1 reverse arc)", () => {
    const f = __test__.parseSchemaImpactFilter({
      upstream_lineage_edge_id: "edge-aaa",
    });
    expect(f).toEqual({ upstreamLineageEdgeId: "edge-aaa" });
  });

  it("parses upstream_classification_id (R5 reverse arc)", () => {
    const f = __test__.parseSchemaImpactFilter({
      upstream_classification_id: "cls-111",
    });
    expect(f).toEqual({ upstreamClassificationId: "cls-111" });
  });

  it("parses upstream_semantic_type_id (R6 reverse arc)", () => {
    const f = __test__.parseSchemaImpactFilter({
      upstream_semantic_type_id: "sem-222",
    });
    expect(f).toEqual({ upstreamSemanticTypeId: "sem-222" });
  });

  it("parses the L4↦L2 composite (source_id + src_table + src_column)", () => {
    const f = __test__.parseSchemaImpactFilter({
      source_id: "src-1",
      src_table: "raw.events",
      src_column: "user_id",
    });
    expect(f).toEqual({
      sourceId: "src-1",
      srcTable: "raw.events",
      srcColumn: "user_id",
    });
  });

  it("parses a partial L4↦L2 composite (table-level drift, no src_column)", () => {
    const f = __test__.parseSchemaImpactFilter({
      source_id: "src-1",
      src_table: "raw.events",
    });
    expect(f).toEqual({ sourceId: "src-1", srcTable: "raw.events" });
  });

  it("composes multiple params with all keys present", () => {
    const f = __test__.parseSchemaImpactFilter({
      upstream_semantic_type_id: "sem-222",
      source_id: "src-1",
    });
    expect(f).toEqual({
      upstreamSemanticTypeId: "sem-222",
      sourceId: "src-1",
    });
  });

  it("uses first value when a param key is repeated (array form)", () => {
    const f = __test__.parseSchemaImpactFilter({
      upstream_lineage_edge_id: ["edge-aaa", "edge-bbb"],
    });
    expect(f).toEqual({ upstreamLineageEdgeId: "edge-aaa" });
  });

  // L4 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("parses impact_id producer-side PK deep-link", () => {
    const f = __test__.parseSchemaImpactFilter({ impact_id: "impact-xyz" });
    expect(f).toEqual({ impactId: "impact-xyz" });
  });
});

describe("/lake/schema-impact filterToChipMap", () => {
  it("returns {} when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });

  it("maps SchemaImpactFilter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({
      upstreamLineageEdgeId: "edge-aaa",
      sourceId: "src-1",
    });
    expect(m).toEqual({
      upstream_lineage_edge_id: "edge-aaa",
      upstream_classification_id: undefined,
      upstream_semantic_type_id: undefined,
      source_id: "src-1",
      src_table: undefined,
      src_column: undefined,
      impact_id: undefined,
    });
  });

  it("maps impact_id back to its URL-param key", () => {
    const m = __test__.filterToChipMap({ impactId: "impact-zzz" });
    expect(m.impact_id).toBe("impact-zzz");
  });
});

// ─────────────────────────────────────────────────────────────────────────
// L4 row chain-link evidence reader (2026-05-16 — producer-side bundle).
// Closes the L4↦L2 evidence-link asymmetry by extending the existing
// evidence-keyed reader pattern with ``upstream_drift_id`` support
// (top-level OR composite-merged under ``acknowledged_drift``).
// ─────────────────────────────────────────────────────────────────────────

describe("/lake/schema-impact readUpstreamEvidenceId (L2 drift case)", () => {
  it("reads upstream_drift_id from top-level evidence (single-strategy row)", () => {
    const evidence = { upstream_drift_id: "drift-aaa" };
    expect(
      __test__.readUpstreamEvidenceId(
        evidence,
        "acknowledged_drift",
        "upstream_drift_id",
      ),
    ).toBe("drift-aaa");
  });

  it("reads upstream_drift_id from composite-merged evidence (multi-strategy)", () => {
    const evidence = {
      governance_classification: { upstream_classification_id: "cls-x" },
      acknowledged_drift: { upstream_drift_id: "drift-bbb" },
    };
    expect(
      __test__.readUpstreamEvidenceId(
        evidence,
        "acknowledged_drift",
        "upstream_drift_id",
      ),
    ).toBe("drift-bbb");
  });

  it("prefers composite-merged value over top-level when both are set", () => {
    const evidence = {
      upstream_drift_id: "drift-top",
      acknowledged_drift: { upstream_drift_id: "drift-composite" },
    };
    expect(
      __test__.readUpstreamEvidenceId(
        evidence,
        "acknowledged_drift",
        "upstream_drift_id",
      ),
    ).toBe("drift-composite");
  });

  it("returns null when neither top-level nor composite carries the key", () => {
    const evidence = {
      governance_classification: { upstream_classification_id: "cls-x" },
    };
    expect(
      __test__.readUpstreamEvidenceId(
        evidence,
        "acknowledged_drift",
        "upstream_drift_id",
      ),
    ).toBeNull();
  });

  it("returns null when evidence is undefined", () => {
    expect(
      __test__.readUpstreamEvidenceId(
        undefined,
        "acknowledged_drift",
        "upstream_drift_id",
      ),
    ).toBeNull();
  });
});
