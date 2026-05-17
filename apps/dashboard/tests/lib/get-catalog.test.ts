/**
 * /lake/catalog accessor tests (Wave 3 Task 1).
 *
 * Mocks the ``pg`` module so the accessor can be exercised without a
 * live Postgres dependency. Verifies:
 *
 *   * Honest empty when ``DATABASE_URL`` is unset (test default).
 *   * SQL shape — JOIN-driven query that pulls the most-recent
 *     snapshot per source_id and counts lineage edges.
 *   * Optional domain + search filters thread into the WHERE clause
 *     with parameterized placeholders (no string concatenation).
 *   * Row mapping converts Postgres snake_case to dashboard
 *     camelCase + coerces numeric columns to ``number``.
 *   * ``getCatalogTable`` returns ``null`` for a missing source and
 *     attaches the edge list when one exists.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getCatalogTables (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-catalog");
    const tables = await mod.getCatalogTables(COMPANY_ID);
    expect(tables).toEqual([]);
  });

  it("returns null from getCatalogTable when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-catalog");
    const detail = await mod.getCatalogTable(COMPANY_ID, "missing-source");
    expect(detail).toBeNull();
  });
});

describe("getCatalogTables (Postgres path)", () => {
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

  it("issues the catalog/lineage JOIN SQL", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-catalog");
    await mod.getCatalogTables(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_external_catalog");
    expect(sql).toContain("projection_external_lineage");
    // DISTINCT ON (source_id) → latest snapshot per source.
    expect(sql).toContain("DISTINCT ON (source_id)");
    // Joins upstream + downstream count subqueries.
    expect(sql.toLowerCase()).toContain("upstream_count");
    expect(sql.toLowerCase()).toContain("downstream_count");
    // Always includes the company_id filter as $1.
    expect(sql).toContain("c.company_id = $1");
  });

  it("returns [] when no rows match the query", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-catalog");
    const tables = await mod.getCatalogTables(COMPANY_ID);
    expect(tables).toEqual([]);
  });

  it("appends a parameterized domain_id filter when opts.domainId is set", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-catalog");
    await mod.getCatalogTables(COMPANY_ID, {
      domainId: "22222222-2222-2222-2222-222222222222",
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("c.domain_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      "22222222-2222-2222-2222-222222222222",
      expect.any(Number),
    ]);
  });

  it("appends a case-insensitive source_kind filter when opts.search is set", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-catalog");
    await mod.getCatalogTables(COMPANY_ID, { search: "dbt" });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql.toUpperCase()).toContain("ILIKE");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      "%dbt%",
      expect.any(Number),
    ]);
  });

  it("maps snake_case Postgres rows to camelCase CatalogTable rows", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          source_id: "00000000-0000-0000-0000-000000000001",
          domain_id: "11111111-1111-1111-1111-111111111111",
          source_kind: "dbt",
          snapshot_hash: "abc123",
          table_count: 12,
          edge_count: 11,
          metric_count: 3,
          import_mode: "initial",
          upstream_lineage_count: 5,
          downstream_lineage_count: 6,
          imported_at: "2026-05-11T10:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lake-catalog");
    const tables = await mod.getCatalogTables(COMPANY_ID);
    expect(tables).toHaveLength(1);
    expect(tables[0]).toEqual({
      sourceId: "00000000-0000-0000-0000-000000000001",
      domainId: "11111111-1111-1111-1111-111111111111",
      sourceKind: "dbt",
      snapshotHash: "abc123",
      tableCount: 12,
      edgeCount: 11,
      metricCount: 3,
      importMode: "initial",
      upstreamLineageCount: 5,
      downstreamLineageCount: 6,
      importedAt: "2026-05-11T10:00:00.000Z",
    });
  });

  it("coerces stringy bigint counts from Postgres into numbers", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          source_id: "00000000-0000-0000-0000-000000000001",
          domain_id: "11111111-1111-1111-1111-111111111111",
          source_kind: "snowflake_native",
          snapshot_hash: "h",
          table_count: "38",
          edge_count: "100",
          metric_count: "0",
          import_mode: "refresh",
          upstream_lineage_count: "12",
          downstream_lineage_count: "7",
          imported_at: "2026-05-11T10:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lake-catalog");
    const tables = await mod.getCatalogTables(COMPANY_ID);
    expect(tables[0].tableCount).toBe(38);
    expect(tables[0].edgeCount).toBe(100);
    expect(tables[0].metricCount).toBe(0);
    expect(tables[0].upstreamLineageCount).toBe(12);
    expect(tables[0].downstreamLineageCount).toBe(7);
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/lake-catalog");
    const tables = await mod.getCatalogTables(COMPANY_ID);
    expect(tables).toEqual([]);
  });
});

describe("getCatalogTable (single source detail)", () => {
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

  it("returns null when no snapshot exists for the source", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-catalog");
    const detail = await mod.getCatalogTable(COMPANY_ID, "missing-source");
    expect(detail).toBeNull();
  });

  it("returns the row + edge list when a snapshot exists", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            source_id: "00000000-0000-0000-0000-000000000001",
            domain_id: "11111111-1111-1111-1111-111111111111",
            source_kind: "dbt",
            snapshot_hash: "abc123",
            table_count: 4,
            edge_count: 3,
            metric_count: 1,
            import_mode: "initial",
            imported_at: "2026-05-11T10:00:00.000Z",
          },
        ],
        rowCount: 1,
      })
      .mockResolvedValueOnce({
        rows: [
          { upstream: "source.raw.x", downstream: "model.staging.x" },
          { upstream: "model.staging.x", downstream: "model.marts.x_daily" },
        ],
        rowCount: 2,
      });
    const mod = await import("../../lib/lake-catalog");
    const detail = await mod.getCatalogTable(
      COMPANY_ID,
      "00000000-0000-0000-0000-000000000001",
    );
    expect(detail).not.toBeNull();
    expect(detail!.sourceKind).toBe("dbt");
    expect(detail!.upstreamEdges).toHaveLength(2);
    expect(detail!.downstreamEdges).toHaveLength(2);
    expect(detail!.upstreamEdges[0]).toEqual({
      upstream: "source.raw.x",
      downstream: "model.staging.x",
    });
  });

  it("returns null when the header query throws", async () => {
    queryMock.mockRejectedValueOnce(new Error("table missing"));
    const mod = await import("../../lib/lake-catalog");
    const detail = await mod.getCatalogTable(COMPANY_ID, "any");
    expect(detail).toBeNull();
  });
});
