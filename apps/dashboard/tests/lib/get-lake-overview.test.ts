/**
 * /lake/overview accessor tests — Lake-Side Overview (2026-05-16).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty fallbacks (no DATABASE_URL → 8 axis cards with
 *     0/0/0; [] activity).
 *   * 3-pattern affirmative-state doctrine (L3/L4/L5/L6/L7/L8 →
 *     ``confirmed``, L1 → ``promoted``, L2 → ``acknowledged``).
 *   * SQL company_id scope on every per-axis query.
 *   * Recent-activity merge sorts across axes by ts DESC + honors
 *     limit + drill-in href uses producer-side deep-link param when
 *     the axis supports it.
 *   * ``getLakeChains`` returns 7 chains incl. one bidirectional
 *     (L4 ↔ L2) and correct producer/consumer hrefs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

// ─── getLakeChains — static, no DB needed ────────────────────────────────

describe("getLakeChains", () => {
  it("returns exactly 7 cross-axis chains", async () => {
    const mod = await import("../../lib/lake-overview");
    const chains = mod.getLakeChains();
    expect(chains).toHaveLength(7);
  });

  it("includes the L4 ↔ L2 bidirectional chain with the bidirectional flag", async () => {
    const mod = await import("../../lib/lake-overview");
    const chains = mod.getLakeChains();
    const l4l2 = chains.find((c) => c.forward.includes("L4") && c.forward.includes("L2"));
    expect(l4l2).toBeDefined();
    expect(l4l2!.isBidirectional).toBe(true);
    expect(l4l2!.forward).toContain("↔");
  });

  it("no chain other than L4 ↔ L2 is bidirectional", async () => {
    const mod = await import("../../lib/lake-overview");
    const chains = mod.getLakeChains();
    const bi = chains.filter((c) => c.isBidirectional);
    expect(bi).toHaveLength(1);
  });

  it("every chain row has a producer page + consumer page href", async () => {
    const mod = await import("../../lib/lake-overview");
    const chains = mod.getLakeChains();
    for (const c of chains) {
      expect(c.producerPage).toMatch(/^\/lake\//);
      expect(c.consumerPage).toMatch(/^\/lake\//);
      expect(c.description.length).toBeGreaterThan(0);
    }
  });

  it("contains all 7 named chain labels in expected forward form", async () => {
    const mod = await import("../../lib/lake-overview");
    const chains = mod.getLakeChains();
    const labels = chains.map((c) => c.forward);
    expect(labels).toContain("L4 → L3");
    expect(labels).toContain("L6 → L5");
    expect(labels).toContain("L8 → L5");
    expect(labels).toContain("L5 → L7");
    expect(labels).toContain("L6 → L4");
    expect(labels).toContain("L5 → L4");
    expect(labels).toContain("L4 ↔ L2");
  });
});

// ─── getLakeAxisStates — honest empty path ───────────────────────────────

describe("getLakeAxisStates (no DATABASE_URL)", () => {
  it("returns 8 axis rows with 0/0/0 counts when no Postgres", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getLakeAxisStates(COMPANY_ID);
    expect(rows).toHaveLength(8);
    for (const row of rows) {
      expect(row.proposedCount).toBe(0);
      expect(row.affirmedCount).toBe(0);
      expect(row.rejectedCount).toBe(0);
    }
  });

  it("affirmative state names match the 3-pattern doctrine", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getLakeAxisStates(COMPANY_ID);
    const byAxis = new Map(rows.map((r) => [r.axis, r]));
    expect(byAxis.get("L1")!.affirmativeStateLabel).toBe("promoted");
    expect(byAxis.get("L2")!.affirmativeStateLabel).toBe("acknowledged");
    expect(byAxis.get("L3")!.affirmativeStateLabel).toBe("confirmed");
    expect(byAxis.get("L4")!.affirmativeStateLabel).toBe("confirmed");
    expect(byAxis.get("L5")!.affirmativeStateLabel).toBe("confirmed");
    expect(byAxis.get("L6")!.affirmativeStateLabel).toBe("confirmed");
    expect(byAxis.get("L7")!.affirmativeStateLabel).toBe("confirmed");
    expect(byAxis.get("L8")!.affirmativeStateLabel).toBe("confirmed");
  });

  it("every axis row carries an axis href targeting /lake/*", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getLakeAxisStates(COMPANY_ID);
    for (const r of rows) {
      expect(r.axisHref).toMatch(/^\/lake\//);
    }
  });
});

// ─── getLakeAxisStates — Postgres path ───────────────────────────────────

describe("getLakeAxisStates (Postgres path)", () => {
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

  it("issues 8 parallel queries, each scoped by company_id and GROUP BY state", async () => {
    queryMock.mockResolvedValue({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-overview");
    await mod.getLakeAxisStates(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(8);
    for (let i = 0; i < 8; i++) {
      const sql = String(queryMock.mock.calls[i][0]);
      expect(sql).toContain("company_id = $1");
      expect(sql).toContain("GROUP BY state");
    }
    // every call should pass COMPANY_ID
    for (let i = 0; i < 8; i++) {
      expect(queryMock.mock.calls[i][1]).toEqual([COMPANY_ID]);
    }
  });

  it("maps proposed / per-axis affirmative / rejected counts into the row", async () => {
    // Return the same shape for every projection query — enough to
    // confirm L5 (confirmed) and L2 (acknowledged) and L1 (promoted)
    // all map the correct affirmative bucket.
    queryMock.mockImplementation(async (sql: string) => {
      if (sql.includes("projection_catalog_drifts")) {
        return {
          rows: [
            { state: "proposed", n: 2 },
            { state: "acknowledged", n: 5 },
            { state: "rejected", n: 1 },
          ],
          rowCount: 3,
        };
      }
      if (sql.includes("projection_source_candidates")) {
        return {
          rows: [
            { state: "proposed", n: 3 },
            { state: "promoted", n: 4 },
            { state: "rejected", n: 0 },
          ],
          rowCount: 3,
        };
      }
      // confirmed-flavor axes — return some confirmed counts
      return {
        rows: [
          { state: "proposed", n: 1 },
          { state: "confirmed", n: 7 },
          { state: "rejected", n: 2 },
        ],
        rowCount: 3,
      };
    });
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getLakeAxisStates(COMPANY_ID);
    const byAxis = new Map(rows.map((r) => [r.axis, r]));
    expect(byAxis.get("L1")).toEqual({
      axis: "L1",
      axisName: "Source candidates",
      axisHref: "/lake/source-candidates",
      proposedCount: 3,
      affirmedCount: 4,
      affirmativeStateLabel: "promoted",
      rejectedCount: 0,
    });
    expect(byAxis.get("L2")!.affirmedCount).toBe(5);
    expect(byAxis.get("L2")!.proposedCount).toBe(2);
    expect(byAxis.get("L5")!.affirmedCount).toBe(7);
    expect(byAxis.get("L5")!.proposedCount).toBe(1);
  });

  it("returns 0/0/0 for an axis whose query throws (does not fail the whole call)", async () => {
    queryMock.mockImplementation(async (sql: string) => {
      if (sql.includes("projection_semantic_types")) {
        throw new Error("simulated projection error");
      }
      return {
        rows: [
          { state: "proposed", n: 1 },
          { state: "confirmed", n: 1 },
        ],
        rowCount: 2,
      };
    });
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getLakeAxisStates(COMPANY_ID);
    const l5 = rows.find((r) => r.axis === "L5")!;
    expect(l5.proposedCount).toBe(0);
    expect(l5.affirmedCount).toBe(0);
    expect(l5.rejectedCount).toBe(0);
    // other axes still populated
    expect(rows.some((r) => r.affirmedCount > 0)).toBe(true);
  });
});

// ─── getRecentLakeActivity ───────────────────────────────────────────────

describe("getRecentLakeActivity (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getRecentLakeActivity(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getRecentLakeActivity (Postgres path)", () => {
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

  it("merges across axes, sorts by ts DESC, honors limit", async () => {
    queryMock.mockImplementation(async (sql: string) => {
      if (sql.includes("projection_semantic_types")) {
        return {
          rows: [
            {
              type_id: "type-001",
              table_id: "users",
              column: "email",
              semantic_type: "email",
              state: "confirmed",
              state_changed_at: "2026-05-16T12:00:00.000Z",
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_catalog_drifts")) {
        return {
          rows: [
            {
              drift_id: "drift-001",
              table_id: "orders",
              column: "status",
              drift_kind: "column_type_changed",
              state: "acknowledged",
              state_changed_at: "2026-05-16T14:00:00.000Z",
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_source_candidates")) {
        return {
          rows: [
            {
              candidate_id: "cand-001",
              proposed_kind: "postgres",
              proposed_identifier: "prod-db",
              state: "proposed",
              state_changed_at: "2026-05-16T10:00:00.000Z",
            },
          ],
          rowCount: 1,
        };
      }
      return { rows: [], rowCount: 0 };
    });

    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getRecentLakeActivity(COMPANY_ID, 5);
    expect(rows).toHaveLength(3);
    // Sorted ts DESC: drift (14:00) > sem (12:00) > cand (10:00)
    expect(rows[0].axis).toBe("L2");
    expect(rows[0].action).toBe("acknowledged");
    expect(rows[1].axis).toBe("L5");
    expect(rows[1].action).toBe("confirmed");
    expect(rows[2].axis).toBe("L1");
    expect(rows[2].action).toBe("proposed");
  });

  it("activity href uses producer-side deep-link param for L5 (type_id) + L1 now uses candidate_id (drill-in completion bundle)", async () => {
    queryMock.mockImplementation(async (sql: string) => {
      if (sql.includes("projection_semantic_types")) {
        return {
          rows: [
            {
              type_id: "type-abc",
              table_id: "users",
              column: "email",
              semantic_type: "email",
              state: "confirmed",
              state_changed_at: "2026-05-16T12:00:00.000Z",
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_source_candidates")) {
        return {
          rows: [
            {
              candidate_id: "cand-xyz",
              proposed_kind: "postgres",
              proposed_identifier: "db1",
              state: "proposed",
              state_changed_at: "2026-05-16T11:00:00.000Z",
            },
          ],
          rowCount: 1,
        };
      }
      return { rows: [], rowCount: 0 };
    });

    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getRecentLakeActivity(COMPANY_ID, 5);
    const l5 = rows.find((r) => r.axis === "L5")!;
    expect(l5.href).toBe("/lake/semantic-types?type_id=type-abc");
    const l1 = rows.find((r) => r.axis === "L1")!;
    // After 2026-05-16 drill-in completion bundle, L1 carries
    // ``?candidate_id=`` — symmetric with the L2/L3/L5/L6 producer-side
    // deep-links shipped in bdee480.
    expect(l1.href).toBe("/lake/source-candidates?candidate_id=cand-xyz");
  });

  it("all 8 axes now have producer-side PK drill-in URLs (drill-in coverage complete)", async () => {
    queryMock.mockImplementation(async (sql: string) => {
      const baseTs = "2026-05-16T12:00:00.000Z";
      if (sql.includes("projection_source_candidates")) {
        return {
          rows: [
            {
              candidate_id: "cand-1",
              proposed_kind: "postgres",
              proposed_identifier: "db",
              state: "proposed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_catalog_drifts")) {
        return {
          rows: [
            {
              drift_id: "drift-1",
              drift_kind: "table_added",
              table_id: "x",
              column: null,
              state: "acknowledged",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_lineage_edges")) {
        return {
          rows: [
            {
              edge_id: "edge-1",
              src_table_id: "a",
              tgt_table_id: "b",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_schema_impacts")) {
        return {
          rows: [
            {
              impact_id: "impact-1",
              impact_kind: "column_dropped",
              tgt_table_id: "x",
              tgt_column: "c",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_semantic_types")) {
        return {
          rows: [
            {
              type_id: "type-1",
              semantic_type: "email",
              table_id: "x",
              column: "c",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_column_classifications")) {
        return {
          rows: [
            {
              classification_id: "cls-1",
              classification_level: "pii",
              table_id: "x",
              column: "c",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_quality_checks")) {
        return {
          rows: [
            {
              check_id: "check-1",
              check_kind: "not_null",
              table_id: "x",
              column: "c",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql.includes("projection_entity_stitches")) {
        return {
          rows: [
            {
              stitch_id: "stitch-1",
              src_table_a: "a",
              src_table_b: "b",
              entity_kind: "person",
              state: "confirmed",
              state_changed_at: baseTs,
            },
          ],
          rowCount: 1,
        };
      }
      return { rows: [], rowCount: 0 };
    });

    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getRecentLakeActivity(COMPANY_ID, 20);
    const byAxis = new Map(rows.map((r) => [r.axis, r]));
    expect(byAxis.get("L1")!.href).toBe(
      "/lake/source-candidates?candidate_id=cand-1",
    );
    expect(byAxis.get("L2")!.href).toBe(
      "/lake/catalog-drift?drift_id=drift-1",
    );
    expect(byAxis.get("L3")!.href).toBe("/lake/lineage?edge_id=edge-1");
    expect(byAxis.get("L4")!.href).toBe(
      "/lake/schema-impact?impact_id=impact-1",
    );
    expect(byAxis.get("L5")!.href).toBe(
      "/lake/semantic-types?type_id=type-1",
    );
    expect(byAxis.get("L6")!.href).toBe(
      "/lake/column-classification?classification_id=cls-1",
    );
    expect(byAxis.get("L7")!.href).toBe("/lake/quality?check_id=check-1");
    expect(byAxis.get("L8")!.href).toBe(
      "/lake/entity-stitches?stitch_id=stitch-1",
    );
  });

  it("truncates the merged list to the requested limit", async () => {
    // 8 axes × 3 rows each = 24 rows; limit=5 should return 5.
    queryMock.mockImplementation(async (sql: string) => {
      // mint 3 rows per axis with descending ts
      const id =
        sql.match(/projection_(\w+)/)?.[1] ?? "x";
      const baseTs = Date.UTC(2026, 4, 16, 0, 0, 0);
      return {
        rows: [0, 1, 2].map((i) => ({
          [`${id.slice(0, -1)}_id`]: `${id}-${i}`,
          edge_id: `${id}-edge-${i}`,
          impact_id: `${id}-impact-${i}`,
          stitch_id: `${id}-stitch-${i}`,
          candidate_id: `${id}-cand-${i}`,
          drift_id: `${id}-drift-${i}`,
          check_id: `${id}-check-${i}`,
          classification_id: `${id}-cls-${i}`,
          type_id: `${id}-type-${i}`,
          state: "proposed",
          state_changed_at: new Date(baseTs + i * 60000).toISOString(),
          src_table_id: "x",
          tgt_table_id: "y",
          table_id: "tbl",
          column: "c",
          src_table_a: "a",
          src_table_b: "b",
          semantic_type: "email",
          drift_kind: "table_added",
          check_kind: "not_null",
          classification_level: "internal",
          impact_kind: "column_renamed",
          entity_kind: "user",
          proposed_kind: "postgres",
          proposed_identifier: "db",
          tgt_column: "cc",
        })),
        rowCount: 3,
      };
    });

    const mod = await import("../../lib/lake-overview");
    const rows = await mod.getRecentLakeActivity(COMPANY_ID, 5);
    expect(rows).toHaveLength(5);
  });
});
