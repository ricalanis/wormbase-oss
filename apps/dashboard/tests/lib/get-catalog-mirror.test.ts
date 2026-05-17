/**
 * catalog-mirror accessor tests — Catalog-mirror Wave 2 Sub-wave C
 * (2026-06-10).
 *
 * Mocks ``pg`` so the accessor runs without a live Postgres dep.
 * Verifies:
 *
 *   * Honest ``0`` when DATABASE_URL is unset (no DB → no count).
 *   * Honest ``0`` when the projection is empty (query returns
 *     ``[{n: 0}]``).
 *   * Honest ``0`` when the query throws (e.g. migration v029 hasn't
 *     run on this DB).
 *   * Returns the parsed count when the projection has rows.
 *   * Tenant-scoping — the SQL filters by ``company_id``.
 *
 * The accessor is consumed by both the L2 (/lake/catalog-drift) and
 * L8 (/lake/entity-stitches) strategy banners so they share one
 * upstream-substrate probe.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getCatalogTableImportCount (no DATABASE_URL)", () => {
  it("returns 0 when neither DATABASE_URL nor WORMBASE_LEDGER_DSN is set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/catalog-mirror");
    const n = await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(n).toBe(0);
  });
});

describe("getCatalogTableImportCount (Postgres path)", () => {
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

  it("issues a COUNT(*) SQL scoped by company_id against projection_catalog_tables", async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/catalog-mirror");
    await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_catalog_tables");
    expect(sql).toContain("company_id = $1");
    expect(sql).toContain("COUNT(*)");
    const params = queryMock.mock.calls[0][1];
    expect(params).toEqual([COMPANY_ID]);
  });

  it("returns 0 when the projection is empty", async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/catalog-mirror");
    const n = await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(n).toBe(0);
  });

  it("returns the parsed count when the projection has rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ n: 17 }], rowCount: 1 });
    const mod = await import("../../lib/catalog-mirror");
    const n = await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(n).toBe(17);
  });

  it("parses string-typed counts (pg can return COUNT as string on some drivers)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ n: "42" }], rowCount: 1 });
    const mod = await import("../../lib/catalog-mirror");
    const n = await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(n).toBe(42);
  });

  it("returns 0 when the query throws (e.g. migration v029 not run)", async () => {
    queryMock.mockRejectedValueOnce(
      new Error('relation "projection_catalog_tables" does not exist'),
    );
    const mod = await import("../../lib/catalog-mirror");
    const n = await mod.getCatalogTableImportCount(COMPANY_ID);
    expect(n).toBe(0);
  });
});
