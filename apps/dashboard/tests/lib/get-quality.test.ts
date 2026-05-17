/**
 * /lake/quality accessor tests — L7 Sub-wave D (2026-05-30).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset.
 *   * SQL shape — state filter + company_id scope.
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``QualityCheckRow`` shape.
 *   * Strategy status banner reflects env-knob state honestly:
 *     ``schema_pattern`` productive / ``dbt_tests`` configured ·
 *     empty-upstream / ``historical_stats`` configured · stubbed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedQualityChecks (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedQualityChecks (Postgres path)", () => {
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
    const mod = await import("../../lib/quality");
    await mod.getProposedQualityChecks(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_quality_checks");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps the row payload to a QualityCheckRow", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          check_id: "check-001",
          table_id: "snowflake.dbt.dim_users",
          column: "user_id",
          check_kind: "unique",
          config: { strict: true },
          confidence: 0.99,
          strategy: "dbt_tests",
          reasoning: "manifest-listed unique test",
          evidence: { manifest_version: "1.7.0" },
          state: "proposed",
          state_changed_at: "2026-05-30T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({
      checkId: "check-001",
      tableId: "snowflake.dbt.dim_users",
      column: "user_id",
      checkKind: "unique",
      config: { strict: true },
      confidence: 0.99,
      strategy: "dbt_tests",
      reasoning: "manifest-listed unique test",
      evidence: { manifest_version: "1.7.0" },
      state: "proposed",
      stateChangedAt: "2026-05-30T10:00:00.000Z",
      stateChangedBy: null,
    });
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedQualityChecks scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getConfirmedQualityChecks(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedQualityChecks scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getRejectedQualityChecks(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getQualityCheckEvidence returns null when check_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    const got = await mod.getQualityCheckEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });

  it("table-level checks (column=null) map correctly", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          check_id: "check-row-count",
          table_id: "snowflake.raw.events",
          column: null,
          check_kind: "row_count_range",
          config: { min: 1000, max: 1000000 },
          confidence: 0.7,
          strategy: "historical_stats",
          reasoning: "stub",
          evidence: {},
          state: "proposed",
          state_changed_at: new Date("2026-05-30T11:00:00Z"),
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID);
    expect(rows[0].column).toBeNull();
    expect(rows[0].checkKind).toBe("row_count_range");
  });
});

describe("getQualityStrategyStatus (env-driven gauges)", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED;
    delete process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
  });
  afterEach(() => {
    delete process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED;
    delete process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
  });

  it("reports all strategies as disabled when the master switch is off", async () => {
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.schema_pattern.configured).toBe(false);
    expect(byName.schema_pattern.badge).toBe("disabled");
    expect(byName.dbt_tests.configured).toBe(false);
    expect(byName.dbt_tests.badge).toBe("disabled");
    expect(byName.historical_stats.configured).toBe(false);
    expect(byName.historical_stats.badge).toBe("disabled");
    // 4th strategy added by L5→L7 cross-axis chain.
    expect(byName.semantic_type).toBeDefined();
    expect(byName.semantic_type.configured).toBe(false);
    expect(byName.semantic_type.badge).toBe("disabled");
  });

  it("reports schema_pattern productive + dbt_tests empty-upstream when master switch is on", async () => {
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.schema_pattern.productive).toBe(true);
    expect(byName.schema_pattern.badge).toBe("production");
    expect(byName.dbt_tests.configured).toBe(true);
    expect(byName.dbt_tests.productive).toBe(false);
    expect(byName.dbt_tests.badge).toBe("configured-stubbed");
    expect(byName.dbt_tests.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
    expect(byName.historical_stats.configured).toBe(false);
    expect(byName.historical_stats.badge).toBe("disabled");
  });

  it("reports historical_stats as configured · stubbed when its env knob is on", async () => {
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED = "true";
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.historical_stats.configured).toBe(true);
    expect(byName.historical_stats.productive).toBe(false);
    expect(byName.historical_stats.badge).toBe("configured-stubbed");
    expect(byName.historical_stats.note).toContain("stubbed");
  });
});

describe("getQualityStrategyStatus — semantic_type cross-axis (L5→L7)", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
  });
  afterEach(() => {
    delete process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
  });

  it("4th strategy disabled when sub-knob off (even if master on)", async () => {
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(false);
    expect(byName.semantic_type.badge).toBe("disabled");
    expect(byName.semantic_type.note.toLowerCase()).toContain(
      "cross-axis chain",
    );
  });

  it("4th strategy disabled when sub-knob on but master off", async () => {
    process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED = "true";
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    // Sub-knob is a no-op without master; honest disabled state.
    expect(byName.semantic_type.configured).toBe(false);
    expect(byName.semantic_type.badge).toBe("disabled");
  });

  it("4th strategy configured · awaiting-L5-types when sub-knob on but L5 off", async () => {
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED = "true";
    // L5 deliberately off.
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.semantic_type.badge).toBe("configured-stubbed");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "configured · awaiting-L5-types",
    );
    expect(byName.semantic_type.note).toContain("L5");
  });

  it("4th strategy productive · L5-dependent when both sub-knob and L5 are on", async () => {
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(true);
    expect(byName.semantic_type.badge).toBe("production");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "productive · L5-dependent",
    );
    expect(byName.semantic_type.note).toContain("4th cross-axis chain");
    expect(byName.semantic_type.note).toContain("ConfirmedSemanticTypeReader");
  });

  it("status array surfaces exactly 4 strategies (3 existing + 1 cross-axis)", async () => {
    const mod = await import("../../lib/quality");
    const status = await mod.getQualityStrategyStatus(COMPANY_ID);
    expect(status.map((s) => s.strategy).sort()).toEqual([
      "dbt_tests",
      "historical_stats",
      "schema_pattern",
      "semantic_type",
    ]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Per-page filter widget tests (2026-05-16) — R4 reverse-arc deeplink.
// Quality projection stores the upstream pointer in JSON evidence, not
// a first-class column.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeQualityCheckFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/quality");
    const { where, values } = mod.__test__._composeQualityCheckFilter(
      undefined,
      2,
    );
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes upstream_semantic_type_id as a JSON evidence predicate", async () => {
    const mod = await import("../../lib/quality");
    const { where, values } = mod.__test__._composeQualityCheckFilter(
      { upstreamSemanticTypeId: "sem-111" },
      2,
    );
    expect(where).toContain("evidence ? 'upstream_semantic_type_id'");
    expect(where).toContain("evidence->>'upstream_semantic_type_id' = $2");
    expect(values).toEqual(["sem-111"]);
  });

  // L7 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("composes check_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/quality");
    const { where, values } = mod.__test__._composeQualityCheckFilter(
      { checkId: "check-zzz" },
      2,
    );
    expect(where).toContain("check_id = $2");
    expect(values).toEqual(["check-zzz"]);
  });
});

describe("getProposedQualityChecks (with filter)", () => {
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

  it("appends evidence JSON predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getProposedQualityChecks(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "sem-aaa", 200]);
  });

  it("getConfirmedQualityChecks honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getConfirmedQualityChecks(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
  });

  it("getRejectedQualityChecks threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getRejectedQualityChecks(COMPANY_ID, {
      days: 14,
      filter: { upstreamSemanticTypeId: "sem-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id' = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "sem-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });

  // L7 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("appends check_id producer-side predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    await mod.getProposedQualityChecks(COMPANY_ID, {
      filter: { checkId: "check-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("check_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "check-aaa", 200]);
  });

  it("returns honest empty when check_id filter matches no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/quality");
    const rows = await mod.getProposedQualityChecks(COMPANY_ID, {
      filter: { checkId: "check-nope" },
    });
    expect(rows).toEqual([]);
  });
});
