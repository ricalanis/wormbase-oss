/**
 * /lake/lineage accessor tests — L3 Sub-wave D (2026-05-29).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset.
 *   * SQL shape — state filter + company_id scope.
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``LineageEdgeRow`` shape.
 *   * Strategy status banner reflects env-knob state honestly.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedLineageEdges (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lineage");
    const rows = await mod.getProposedLineageEdges(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedLineageEdges (Postgres path)", () => {
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
    const mod = await import("../../lib/lineage");
    await mod.getProposedLineageEdges(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_lineage_edges");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps the row payload to a LineageEdgeRow", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          edge_id: "edge-001",
          src_table_id: "snowflake.raw.users",
          src_column: "id",
          tgt_table_id: "snowflake.dbt.dim_users",
          tgt_column: "user_id",
          confidence: 0.99,
          strategy: "dbt_manifest",
          reasoning: "manifest-listed parent",
          evidence: { manifest_version: "1.7.0" },
          state: "proposed",
          state_changed_at: "2026-05-29T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lineage");
    const rows = await mod.getProposedLineageEdges(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({
      edgeId: "edge-001",
      srcTableId: "snowflake.raw.users",
      srcColumn: "id",
      tgtTableId: "snowflake.dbt.dim_users",
      tgtColumn: "user_id",
      confidence: 0.99,
      strategy: "dbt_manifest",
      reasoning: "manifest-listed parent",
      evidence: { manifest_version: "1.7.0" },
      state: "proposed",
      stateChangedAt: "2026-05-29T10:00:00.000Z",
      stateChangedBy: null,
    });
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/lineage");
    const rows = await mod.getProposedLineageEdges(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedLineageEdges scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getConfirmedLineageEdges(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedLineageEdges scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getRejectedLineageEdges(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getLineageEdgeEvidence returns null when edge_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    const got = await mod.getLineageEdgeEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });
});

describe("getLineageStrategyStatus (env-driven gauges)", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED;
  });
  afterEach(() => {
    delete process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED;
  });

  it("reports all strategies as disabled when the master switch is off", async () => {
    const mod = await import("../../lib/lineage");
    const status = await mod.getLineageStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.dbt_manifest.configured).toBe(false);
    expect(byName.naming_heuristic.configured).toBe(false);
    expect(byName.sample_overlap.configured).toBe(false);
  });

  it("reports dbt_manifest as productive and others as configured/stubbed when master switch is on", async () => {
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/lineage");
    const status = await mod.getLineageStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.dbt_manifest.productive).toBe(true);
    expect(byName.dbt_manifest.configured).toBe(true);
    expect(byName.naming_heuristic.configured).toBe(true);
    expect(byName.naming_heuristic.productive).toBe(false);
    expect(byName.sample_overlap.configured).toBe(false);
    expect(byName.sample_overlap.productive).toBe(false);
  });

  it("reports sample_overlap as configured-but-stubbed when explicit env knob is on", async () => {
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED = "true";
    const mod = await import("../../lib/lineage");
    const status = await mod.getLineageStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.sample_overlap.configured).toBe(true);
    expect(byName.sample_overlap.productive).toBe(false);
    expect(byName.sample_overlap.note).toContain("NoopSampler");
  });
});

// ─── R1 L4↦L3 reverse-arc accessor (Recipe Addendum #3) ─────────────────

describe("getSchemaImpactCountByLineageEdge (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset (honest empty)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lineage");
    const map = await mod.getSchemaImpactCountByLineageEdge(COMPANY_ID);
    expect(map).toEqual({});
  });
});

describe("getSchemaImpactCountByLineageEdge (Postgres path)", () => {
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

  it("issues state IN ('proposed','confirmed') SQL grouping by upstream_lineage_edge_id", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getSchemaImpactCountByLineageEdge(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_schema_impacts");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("company_id = $1");
    expect(sql).toContain("upstream_lineage_edge_id IS NOT NULL");
    expect(sql).toContain("GROUP BY upstream_lineage_edge_id");
  });

  it("returns a map keyed by upstream_lineage_edge_id", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        { upstream_lineage_edge_id: "edge-aaa", impact_count: 3 },
        { upstream_lineage_edge_id: "edge-bbb", impact_count: 1 },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/lineage");
    const map = await mod.getSchemaImpactCountByLineageEdge(COMPANY_ID);
    expect(map).toEqual({ "edge-aaa": 3, "edge-bbb": 1 });
  });

  it("returns {} when the query throws (honest empty fallback)", async () => {
    queryMock.mockRejectedValueOnce(new Error("relation does not exist"));
    const mod = await import("../../lib/lineage");
    const map = await mod.getSchemaImpactCountByLineageEdge(COMPANY_ID);
    expect(map).toEqual({});
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Producer-side ``?edge_id=`` deep-link filter (2026-05-16).
// ─────────────────────────────────────────────────────────────────────────

describe("_composeLineageFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/lineage");
    const { where, values } = mod.__test__._composeLineageFilter(undefined, 2);
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes edgeId as a primary-key column predicate", async () => {
    const mod = await import("../../lib/lineage");
    const { where, values } = mod.__test__._composeLineageFilter(
      { edgeId: "edge-aaa" },
      2,
    );
    expect(where).toContain("edge_id = $2");
    expect(values).toEqual(["edge-aaa"]);
  });
});

describe("getProposedLineageEdges (with edgeId filter)", () => {
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

  it("appends edge_id predicate + threads param on proposed", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getProposedLineageEdges(COMPANY_ID, {
      filter: { edgeId: "edge-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("edge_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "edge-aaa", 200]);
  });

  it("getConfirmedLineageEdges honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getConfirmedLineageEdges(COMPANY_ID, {
      filter: { edgeId: "edge-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("edge_id = $2");
  });

  it("getRejectedLineageEdges threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    await mod.getRejectedLineageEdges(COMPANY_ID, {
      days: 14,
      filter: { edgeId: "edge-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("edge_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "edge-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lineage");
    const rows = await mod.getProposedLineageEdges(COMPANY_ID, {
      filter: { edgeId: "edge-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });
});
