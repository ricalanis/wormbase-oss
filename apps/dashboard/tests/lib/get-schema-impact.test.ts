/**
 * /lake/schema-impact accessor tests — L4 Sub-wave D (2026-06-02).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset (handoff concern #1).
 *   * SQL shape — state filter + company_id scope (tenant isolation).
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``SchemaImpactRow`` shape, including ``upstreamLineageEdgeId``
 *     null vs set (cross-axis-link gating).
 *   * Strategy status banner reflects env-knob state honestly:
 *     ``lineage_edge`` productive · L3-dependent / configured ·
 *     awaiting-L3-edges / configured · L3-disabled / disabled —
 *     including L3-confirmed-edge count probe.
 *   * ``dbt_test`` configured · empty-upstream when its env knob is
 *     on; ``type_coercion`` productive when L4 is enabled.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedSchemaImpacts (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedSchemaImpacts (Postgres path)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("issues a state='proposed' SQL with company_id scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_schema_impacts");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps the row payload to a SchemaImpactRow with upstreamLineageEdgeId set", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          impact_id: "impact-001",
          source_id: "src-snowflake-prod",
          src_table: "raw.events",
          src_column: "user_id",
          change_kind: "column_type_changed",
          impact_kind: "tgt_column_type_mismatch",
          tgt_table_id: "dbt.dim_users",
          tgt_column: "user_id",
          upstream_lineage_edge_id: "edge-l3-aaa",
          confidence: 0.85,
          strategy: "lineage_edge",
          reasoning: "dbt-manifest edge mapped src.user_id → tgt.user_id",
          evidence: { upstream_edge_strategy: "dbt_manifest" },
          state: "proposed",
          state_changed_at: "2026-06-02T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].impactId).toBe("impact-001");
    expect(rows[0].upstreamLineageEdgeId).toBe("edge-l3-aaa");
    expect(rows[0].strategy).toBe("lineage_edge");
    expect(rows[0].changeKind).toBe("column_type_changed");
    expect(rows[0].impactKind).toBe("tgt_column_type_mismatch");
    expect(rows[0].confidence).toBe(0.85);
    expect(rows[0].evidence).toEqual({ upstream_edge_strategy: "dbt_manifest" });
  });

  it("maps upstreamLineageEdgeId=null when the strategy is non-edge-driven (type_coercion)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          impact_id: "impact-tc",
          source_id: "src-pg-prod",
          src_table: "public.orders",
          src_column: "amount",
          change_kind: "column_type_changed",
          impact_kind: "type_coercion_required",
          tgt_table_id: "public.orders",
          tgt_column: "amount",
          upstream_lineage_edge_id: null,
          confidence: 0.7,
          strategy: "type_coercion",
          reasoning: "varchar→int requires coercion downstream",
          evidence: { suggested_coercion: "CAST(amount AS INTEGER)" },
          state: "proposed",
          state_changed_at: "2026-06-02T11:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID);
    expect(rows[0].upstreamLineageEdgeId).toBeNull();
    expect(rows[0].strategy).toBe("type_coercion");
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedSchemaImpacts scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getConfirmedSchemaImpacts(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedSchemaImpacts scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getRejectedSchemaImpacts(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getSchemaImpactEvidence returns null when impact_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    const got = await mod.getSchemaImpactEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });

  it("getL3DependencyState counts confirmed L3 edges from projection_lineage_edges", async () => {
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED = "true";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 7 }], rowCount: 1 });
    try {
      const mod = await import("../../lib/schema-impact");
      const state = await mod.getL3DependencyState(COMPANY_ID);
      expect(state.l3Enabled).toBe(true);
      expect(state.confirmedEdgeCount).toBe(7);
      const sql = String(queryMock.mock.calls[0][0]);
      expect(sql).toContain("projection_lineage_edges");
      expect(sql).toContain("state = 'confirmed'");
    } finally {
      delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    }
  });
});

describe("getSchemaImpactStrategyStatus (env- + L3-edge-count-driven gauges)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    delete process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });
  afterEach(() => {
    delete process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("reports all strategies as disabled when the L4 master switch is off", async () => {
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.lineage_edge.badge).toBe("disabled");
    expect(byName.lineage_edge.productive).toBe(false);
    expect(byName.dbt_test.badge).toBe("disabled");
    expect(byName.type_coercion.badge).toBe("disabled");
  });

  it("reports lineage_edge configured · L3-disabled when L4 on but L3 off", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.lineage_edge.configured).toBe(true);
    expect(byName.lineage_edge.productive).toBe(false);
    expect(byName.lineage_edge.badge).toBe("configured-stubbed");
    expect(byName.lineage_edge.badgeLabelOverride).toBe(
      "configured · L3-disabled",
    );
  });

  it("reports lineage_edge configured · awaiting-L3-edges when L4+L3 on but no confirmed edges", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries: L3, L6, L5.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.lineage_edge.configured).toBe(true);
    expect(byName.lineage_edge.productive).toBe(false);
    expect(byName.lineage_edge.badge).toBe("configured-stubbed");
    expect(byName.lineage_edge.badgeLabelOverride).toBe(
      "configured · awaiting-L3-edges",
    );
  });

  it("reports lineage_edge productive · L3-dependent when L4+L3 on AND ≥1 confirmed edge", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries: L3, L6, L5.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 3 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.lineage_edge.configured).toBe(true);
    expect(byName.lineage_edge.productive).toBe(true);
    expect(byName.lineage_edge.badge).toBe("production");
    expect(byName.lineage_edge.badgeLabelOverride).toBe(
      "productive · L3-dependent",
    );
    expect(byName.lineage_edge.note).toContain("3 confirmed L3 lineage edges");
  });

  it("reports dbt_test configured · empty-upstream when its env knob is on", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.dbt_test.configured).toBe(true);
    expect(byName.dbt_test.productive).toBe(false);
    expect(byName.dbt_test.badge).toBe("configured-stubbed");
    expect(byName.dbt_test.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
  });

  it("reports type_coercion productive when L4 is enabled (no L3 dependency)", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.type_coercion.configured).toBe(true);
    expect(byName.type_coercion.productive).toBe(true);
    expect(byName.type_coercion.badge).toBe("production");
    expect(byName.type_coercion.note).toContain("No L3 dependency");
  });

  // ─── L6→L4 chain — governance_classification strategy row ───────────────

  it("reports governance_classification disabled when its env knob is off", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.governance_classification.configured).toBe(false);
    expect(byName.governance_classification.productive).toBe(false);
    expect(byName.governance_classification.badge).toBe("disabled");
    expect(byName.governance_classification.note).toContain(
      "WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED",
    );
  });

  it("reports governance_classification configured · awaiting-L6-classifications when sub-knob on + 0 confirmed", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries when DATABASE_URL is set:
    // L3 confirmed-edges, L6 confirmed-classifications, L5 confirmed-semantic-types
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.governance_classification.configured).toBe(true);
    expect(byName.governance_classification.productive).toBe(false);
    expect(byName.governance_classification.badge).toBe("configured-stubbed");
    expect(byName.governance_classification.badgeLabelOverride).toBe(
      "configured · awaiting-L6-classifications",
    );
  });

  it("reports governance_classification productive · L6-dependent when ≥1 L6 confirmed classification", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries: L3, L6, L5.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 4 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.governance_classification.configured).toBe(true);
    expect(byName.governance_classification.productive).toBe(true);
    expect(byName.governance_classification.badge).toBe("production");
    expect(byName.governance_classification.badgeLabelOverride).toBe(
      "productive · L6-dependent",
    );
    expect(byName.governance_classification.note).toContain(
      "4 confirmed L6 column classifications",
    );
  });

  it("governance_classification requires master switch (sub-knob alone → disabled)", async () => {
    // Master OFF but sub-knob ON — the sub-knob does NOT enable the row;
    // the master switch is the gate.
    process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.governance_classification.configured).toBe(false);
    expect(byName.governance_classification.badge).toBe("disabled");
  });
});

describe("getL6DependencyState", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });
  afterEach(() => {
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns zero count when DATABASE_URL is unset (honest empty)", async () => {
    const mod = await import("../../lib/schema-impact");
    const state = await mod.getL6DependencyState(COMPANY_ID);
    expect(state.confirmedClassificationCount).toBe(0);
    expect(state.l6Enabled).toBe(false);
  });

  it("reads WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED truthy", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 12 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const state = await mod.getL6DependencyState(COMPANY_ID);
    expect(state.l6Enabled).toBe(true);
    expect(state.confirmedClassificationCount).toBe(12);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_column_classifications");
    expect(sql).toContain("state = 'confirmed'");
  });
});

describe("getL5DependencyState (L5→L4 cross-axis chain, 6th)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });
  afterEach(() => {
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns zero count when DATABASE_URL is unset (honest empty)", async () => {
    const mod = await import("../../lib/schema-impact");
    const state = await mod.getL5DependencyState(COMPANY_ID);
    expect(state.confirmedSemanticTypeCount).toBe(0);
    expect(state.l5Enabled).toBe(false);
  });

  it("reads WORMBASE_FINGERPRINT_DISCOVERY_ENABLED truthy + counts projection_semantic_types", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 5 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const state = await mod.getL5DependencyState(COMPANY_ID);
    expect(state.l5Enabled).toBe(true);
    expect(state.confirmedSemanticTypeCount).toBe(5);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_semantic_types");
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("falls back to zero when the query throws (honest empty)", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/schema-impact");
    const state = await mod.getL5DependencyState(COMPANY_ID);
    expect(state.l5Enabled).toBe(true);
    expect(state.confirmedSemanticTypeCount).toBe(0);
  });
});

describe("getSchemaImpactStrategyStatus — semantic_type row (L5→L4 chain)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    delete process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED;
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });
  afterEach(() => {
    delete process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED;
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("reports semantic_type disabled when its env knob is off", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(false);
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.semantic_type.badge).toBe("disabled");
    expect(byName.semantic_type.note).toContain(
      "WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED",
    );
  });

  it("reports semantic_type configured · awaiting-L5-semantic-types when sub-knob on + 0 confirmed", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries: L3, L6, L5.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.semantic_type.badge).toBe("configured-stubbed");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "configured · awaiting-L5-semantic-types",
    );
  });

  it("reports semantic_type productive · L5-dependent when ≥1 L5 confirmed semantic type", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 dependency queries: L3, L6, L5 (L5 returns 7 confirmed).
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 7 }], rowCount: 1 });
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(true);
    expect(byName.semantic_type.badge).toBe("production");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "productive · L5-dependent",
    );
    expect(byName.semantic_type.note).toContain(
      "7 confirmed L5 semantic types",
    );
  });

  it("semantic_type requires master switch (sub-knob alone → disabled)", async () => {
    // Master OFF but sub-knob ON — the sub-knob does NOT enable the row.
    process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(false);
    expect(byName.semantic_type.badge).toBe("disabled");
  });

  it("includes semantic_type as the 5th row of the strategy status array", async () => {
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/schema-impact");
    const status = await mod.getSchemaImpactStrategyStatus(COMPANY_ID);
    expect(status.map((s) => s.strategy)).toEqual([
      "lineage_edge",
      "dbt_test",
      "type_coercion",
      "governance_classification",
      "semantic_type",
    ]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Per-page filter widget tests (2026-05-16) — consumer-page deeplinks
// from the reverse-arc + L4↦L2 Half B badges.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeSchemaImpactFilter (SQL composition)", () => {
  it("returns empty fragment + empty values when filter is undefined", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      undefined,
      2,
    );
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("returns empty fragment + empty values when filter is empty", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      {},
      2,
    );
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes upstream_lineage_edge_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      { upstreamLineageEdgeId: "edge-aaa" },
      2,
    );
    expect(where).toContain("upstream_lineage_edge_id = $2");
    expect(values).toEqual(["edge-aaa"]);
  });

  it("composes upstream_classification_id with both top-level and strategy-keyed paths", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      { upstreamClassificationId: "cls-111" },
      2,
    );
    expect(where).toContain("evidence->>'upstream_classification_id'");
    expect(where).toContain("evidence->'governance_classification'");
    expect(values).toEqual(["cls-111"]);
  });

  it("composes upstream_semantic_type_id with both top-level and semantic_type-keyed paths", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      { upstreamSemanticTypeId: "sem-222" },
      2,
    );
    expect(where).toContain("evidence->>'upstream_semantic_type_id'");
    expect(where).toContain("evidence->'semantic_type'");
    expect(values).toEqual(["sem-222"]);
  });

  it("composes the source/table/column triple with AND", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      {
        sourceId: "src-1",
        srcTable: "raw.events",
        srcColumn: "user_id",
      },
      2,
    );
    expect(where).toContain("source_id = $2");
    expect(where).toContain("src_table = $3");
    expect(where).toContain("src_column = $4");
    expect(values).toEqual(["src-1", "raw.events", "user_id"]);
  });

  it("omits src_column when not provided (partial composite)", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      { sourceId: "src-1", srcTable: "raw.events" },
      2,
    );
    expect(where).toContain("source_id = $2");
    expect(where).toContain("src_table = $3");
    expect(where).not.toContain("src_column");
    expect(values).toEqual(["src-1", "raw.events"]);
  });

  it("composes multiple filter keys with AND", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      {
        upstreamLineageEdgeId: "edge-aaa",
        upstreamSemanticTypeId: "sem-222",
        sourceId: "src-1",
      },
      2,
    );
    // Predicates each start with AND, so we should see at least 3 ANDs.
    const andCount = (where.match(/AND/g) ?? []).length;
    expect(andCount).toBeGreaterThanOrEqual(3);
    expect(values).toEqual(["edge-aaa", "sem-222", "src-1"]);
  });

  // L4 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("composes impact_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/schema-impact");
    const { where, values } = mod.__test__._composeSchemaImpactFilter(
      { impactId: "impact-zzz" },
      2,
    );
    expect(where).toContain("impact_id = $2");
    expect(values).toEqual(["impact-zzz"]);
  });
});

describe("getProposedSchemaImpacts (with filter)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("issues the unfiltered SQL when no filter is provided", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'proposed'");
    expect(sql).not.toContain("upstream_lineage_edge_id =");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 200]);
  });

  it("appends upstream_lineage_edge_id predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: { upstreamLineageEdgeId: "edge-xyz" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("upstream_lineage_edge_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "edge-xyz", 200]);
  });

  it("appends a composite source/table/column predicate", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: {
        sourceId: "src-1",
        srcTable: "raw.events",
        srcColumn: "user_id",
      },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("source_id = $2");
    expect(sql).toContain("src_table = $3");
    expect(sql).toContain("src_column = $4");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      "src-1",
      "raw.events",
      "user_id",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: { upstreamLineageEdgeId: "edge-nope" },
    });
    expect(rows).toEqual([]);
  });

  it("getConfirmedSchemaImpacts honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getConfirmedSchemaImpacts(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-222" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
  });

  it("getRejectedSchemaImpacts threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getRejectedSchemaImpacts(COMPANY_ID, {
      days: 14,
      filter: { upstreamLineageEdgeId: "edge-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("upstream_lineage_edge_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "edge-aaa",
      200,
    ]);
  });

  it("composes multiple filter keys + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: {
        upstreamSemanticTypeId: "sem-222",
        sourceId: "src-1",
      },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
    expect(sql).toContain("source_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      "sem-222",
      "src-1",
      200,
    ]);
  });

  it("appends impact_id producer-side predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: { impactId: "impact-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("impact_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "impact-aaa", 200]);
  });

  it("returns honest empty when impact_id filter matches no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/schema-impact");
    const rows = await mod.getProposedSchemaImpacts(COMPANY_ID, {
      filter: { impactId: "impact-nope" },
    });
    expect(rows).toEqual([]);
  });
});
