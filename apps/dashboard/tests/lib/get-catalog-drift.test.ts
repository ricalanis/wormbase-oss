/**
 * /lake/catalog-drift accessor tests — L2 Sub-wave D (2026-06-09).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset (NO FIXTURE return per
 *     CLAUDE.md §9).
 *   * SQL shape — state filter + company_id scope (tenant isolation)
 *     + ``projection_catalog_drifts`` table.
 *   * Row mapping preserves nullable ``column`` (table-level drifts)
 *     and nullable before/after.
 *   * Strategy banner posture per spec §4.7 — table_set 3-state
 *     matrix honestly reflecting the substrate-richness limitation
 *     (Sub-wave C handoff concern #2); column_set + column_type
 *     stay at ``configured · empty-upstream`` regardless of upstream
 *     state (Sub-wave C handoff concern #1).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedCatalogDrifts (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set (honest empty, no FIXTURE)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getProposedCatalogDrifts(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getAcknowledgedCatalogDrifts returns [] when DATABASE_URL unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getAcknowledgedCatalogDrifts(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getRejectedCatalogDrifts returns [] when DATABASE_URL unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getRejectedCatalogDrifts(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedCatalogDrifts (Postgres path)", () => {
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

  it("issues a state='proposed' SQL with company_id scope against projection_catalog_drifts", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getProposedCatalogDrifts(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_catalog_drifts");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("quotes the reserved ``column`` SQL keyword in the SELECT projection", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getProposedCatalogDrifts(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    // ``column`` is a reserved keyword on Postgres — the accessor
    // must double-quote it. Without quoting the query would fail
    // with a syntax error.
    expect(sql).toContain('"column"');
  });

  it("maps a table_added drift row with NULL column honestly", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          drift_id: "d-001",
          source_id: "src-postgres-prod",
          table_id: "public.orders",
          column: null,
          drift_kind: "table_added",
          before: null,
          after: { table_id: "public.orders" },
          strategy: "table_set",
          reasoning: "Table appears in current but not baseline",
          confidence: 0.9,
          evidence: { before_tables: ["public.users"], after_tables: ["public.users", "public.orders"] },
          state: "proposed",
          state_changed_at: "2026-06-09T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getProposedCatalogDrifts(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      driftId: "d-001",
      sourceId: "src-postgres-prod",
      tableId: "public.orders",
      column: null,
      driftKind: "table_added",
      before: null,
      strategy: "table_set",
      confidence: 0.9,
      state: "proposed",
    });
  });

  it("maps a column_type_changed drift with both before AND after populated", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          drift_id: "d-002",
          source_id: "src-x",
          table_id: "public.users",
          column: "id",
          drift_kind: "column_type_changed",
          before: { type: "int" },
          after: { type: "bigint" },
          strategy: "column_type",
          reasoning: "Type changed from int to bigint",
          confidence: 0.9,
          evidence: { before_type: "int", after_type: "bigint" },
          state: "proposed",
          state_changed_at: "2026-06-09T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getProposedCatalogDrifts(COMPANY_ID);
    expect(rows[0].column).toBe("id");
    expect(rows[0].before).toEqual({ type: "int" });
    expect(rows[0].after).toEqual({ type: "bigint" });
  });

  it("getAcknowledgedCatalogDrifts issues state='acknowledged' SQL", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getAcknowledgedCatalogDrifts(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'acknowledged'");
  });

  it("getRejectedCatalogDrifts issues state='rejected' SQL with NOW()-interval", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getRejectedCatalogDrifts(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("NOW() - ");
    expect(sql).toContain("INTERVAL '1 day'");
  });

  it("returns [] when the query throws (honest empty fallback)", async () => {
    queryMock.mockRejectedValueOnce(new Error("relation does not exist"));
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getProposedCatalogDrifts(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getCatalogDriftStrategyStatus (no env knobs)", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED;
  });

  it("returns disabled badges for all 3 strategies when no env knobs set", async () => {
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(row.badge).toBe("disabled");
      expect(row.configured).toBe(false);
      expect(row.productive).toBe(false);
    }
  });

  it("table_set disabled when master ON but sub-knob OFF", async () => {
    process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    const ts = rows.find((r) => r.strategy === "table_set");
    expect(ts?.badge).toBe("disabled");
    expect(ts?.configured).toBe(false);
  });
});

describe("getCatalogDriftStrategyStatus (Wave 2 awaiting-per-table-entries postures)", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED = "true";
    delete process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED;
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
  });

  afterEach(() => {
    delete process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED;
  });

  it("column_set ON, no DATABASE_URL → configured · awaiting-per-table-entries (Wave 2)", async () => {
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    const cs = rows.find((r) => r.strategy === "column_set");
    expect(cs?.configured).toBe(true);
    expect(cs?.productive).toBe(false);
    expect(cs?.badge).toBe("configured-stubbed");
    expect(cs?.badgeLabelOverride).toBe(
      "configured · awaiting-per-table-entries",
    );
  });

  it("column_type ON, no DATABASE_URL → configured · awaiting-per-table-entries (Wave 2)", async () => {
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    const ct = rows.find((r) => r.strategy === "column_type");
    expect(ct?.configured).toBe(true);
    expect(ct?.productive).toBe(false);
    expect(ct?.badge).toBe("configured-stubbed");
    expect(ct?.badgeLabelOverride).toBe(
      "configured · awaiting-per-table-entries",
    );
  });
});

describe("getCatalogDriftStrategyStatus (table_set Wave 2 awaiting-per-table-entries honesty)", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED = "true";
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED;
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
  });

  afterEach(() => {
    delete process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED;
  });

  it("table_set ON, no Postgres → configured · awaiting-per-table-entries (Wave 2)", async () => {
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    const ts = rows.find((r) => r.strategy === "table_set");
    expect(ts?.configured).toBe(true);
    // No DATABASE_URL means the Wave 2 substrate probe returns 0, so
    // the banner is honest-awaiting-per-table-entries.
    expect(ts?.productive).toBe(false);
    expect(ts?.badge).toBe("configured-stubbed");
    expect(ts?.badgeLabelOverride).toBe(
      "configured · awaiting-per-table-entries",
    );
  });
});

describe("getCatalogDriftStrategyStatus (Wave 2 productive · per-connector — Postgres path)", () => {
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
    process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED = "true";
    process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED = "true";

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
    delete process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED;
    delete process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED;
    vi.doUnmock("pg");
  });

  it("flips all 3 strategies to productive · per-connector when Wave 2 substrate has ≥1 entry", async () => {
    // Wave 2 substrate probe returns 5 folded entries.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 5 }], rowCount: 1 });
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(rows.map((r) => [r.strategy, r]));
    for (const strategy of ["table_set", "column_set", "column_type"] as const) {
      expect(byName[strategy].productive).toBe(true);
      expect(byName[strategy].badge).toBe("production");
      expect(byName[strategy].badgeLabelOverride).toBe(
        "productive · per-connector",
      );
      expect(byName[strategy].note).toContain("5 folded");
    }
  });

  it("queries projection_catalog_tables exactly once even when all 3 strategies are enabled (substrate probe shared)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ n: 2 }], rowCount: 1 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getCatalogDriftStrategyStatus(COMPANY_ID);
    // Single COUNT(*) probe against projection_catalog_tables —
    // shared across all 3 strategies (per Wave 2 unified posture).
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_catalog_tables");
    expect(sql).toContain("COUNT(*)");
    expect(sql).toContain("company_id = $1");
  });
});

// ─── L4↦L2 cross-axis enrichment — Half B reverse-arc accessor ──────────

describe("getImpactCountByDriftSource (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset (honest empty)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/catalog-drift");
    const map = await mod.getImpactCountByDriftSource(COMPANY_ID);
    expect(map).toEqual({});
  });
});

describe("getImpactCountByDriftSource (Postgres path)", () => {
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

  it("issues a state IN ('proposed', 'confirmed') SQL against projection_schema_impacts grouping by source/table/column", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getImpactCountByDriftSource(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_schema_impacts");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("company_id = $1");
    expect(sql).toContain("GROUP BY source_id, src_table, src_column");
  });

  it("returns a map keyed by makeImpactCountKey(source_id, src_table, src_column)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          source_id: "warehouse",
          src_table: "public.users",
          src_column: "email",
          impact_count: 3,
        },
        {
          source_id: "warehouse",
          src_table: "public.users",
          src_column: "phone",
          impact_count: 1,
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/catalog-drift");
    const map = await mod.getImpactCountByDriftSource(COMPANY_ID);
    expect(map).toEqual({
      "warehouse|public.users|email": 3,
      "warehouse|public.users|phone": 1,
    });
    // makeImpactCountKey helper exposed for symmetric callers.
    expect(
      map[mod.makeImpactCountKey("warehouse", "public.users", "email")],
    ).toBe(3);
  });

  it("returns {} when the query throws (honest empty fallback)", async () => {
    queryMock.mockRejectedValueOnce(new Error("relation does not exist"));
    const mod = await import("../../lib/catalog-drift");
    const map = await mod.getImpactCountByDriftSource(COMPANY_ID);
    expect(map).toEqual({});
  });

  it("filters out zero counts (defensive)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          source_id: "warehouse",
          src_table: "public.users",
          src_column: "email",
          impact_count: 0,  // unusual; the SQL GROUP BY won't yield 0
        },
        {
          source_id: "warehouse",
          src_table: "public.users",
          src_column: "phone",
          impact_count: 2,
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/catalog-drift");
    const map = await mod.getImpactCountByDriftSource(COMPANY_ID);
    // The zero-count row is silently dropped; phone retained.
    expect(map).toEqual({
      "warehouse|public.users|phone": 2,
    });
  });
});

describe("makeImpactCountKey", () => {
  it("uses pipe-separated tuple format with '*' for null column", async () => {
    const mod = await import("../../lib/catalog-drift");
    expect(mod.makeImpactCountKey("src", "tbl", "col")).toBe("src|tbl|col");
    expect(mod.makeImpactCountKey("src", "tbl", null)).toBe("src|tbl|*");
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Producer-side ``?drift_id=`` deep-link filter (2026-05-16).
// ─────────────────────────────────────────────────────────────────────────

describe("_composeCatalogDriftFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/catalog-drift");
    const { where, values } =
      mod.__test__._composeCatalogDriftFilter(undefined, 2);
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes driftId as a primary-key column predicate", async () => {
    const mod = await import("../../lib/catalog-drift");
    const { where, values } = mod.__test__._composeCatalogDriftFilter(
      { driftId: "drift-aaa" },
      2,
    );
    expect(where).toContain("drift_id = $2");
    expect(values).toEqual(["drift-aaa"]);
  });
});

describe("getProposedCatalogDrifts (with driftId filter)", () => {
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

  it("appends drift_id predicate + threads param on proposed", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getProposedCatalogDrifts(COMPANY_ID, {
      filter: { driftId: "drift-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("drift_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "drift-aaa", 200]);
  });

  it("getAcknowledgedCatalogDrifts honors filter on acknowledged state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getAcknowledgedCatalogDrifts(COMPANY_ID, {
      filter: { driftId: "drift-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'acknowledged'");
    expect(sql).toContain("drift_id = $2");
  });

  it("getRejectedCatalogDrifts threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    await mod.getRejectedCatalogDrifts(COMPANY_ID, {
      days: 14,
      filter: { driftId: "drift-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("drift_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "drift-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/catalog-drift");
    const rows = await mod.getProposedCatalogDrifts(COMPANY_ID, {
      filter: { driftId: "drift-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });
});
