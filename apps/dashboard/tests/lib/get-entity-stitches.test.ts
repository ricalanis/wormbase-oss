/**
 * /lake/entity-stitches accessor tests — L8 Sub-wave D (2026-06-07).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset (NO FIXTURE return per
 *     CLAUDE.md §9).
 *   * SQL shape — state filter + company_id scope (tenant isolation)
 *     + ``projection_entity_stitches`` table.
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``EntityStitchRow`` shape, including ``upstreamSemanticTypeId``
 *     null vs set (cross-axis-link gating), 8-value entity_kind.
 *   * Strategy status banner reflects env-knob state + L5-confirmed-
 *     type count probe honestly: ``name_match`` 4-posture matrix;
 *     ``schema_shape`` productive-when-columns-available qualifier;
 *     ``sample_overlap`` configured-empty-upstream posture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedEntityStitches (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set (honest empty, no FIXTURE)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedEntityStitches (Postgres path)", () => {
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

  it("issues a state='proposed' SQL with company_id scope against projection_entity_stitches", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getProposedEntityStitches(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_entity_stitches");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps the row payload to an EntityStitchRow with upstreamSemanticTypeId set (name_match anchor path)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          stitch_id: "stitch-001",
          src_source_id_a: "crm",
          src_table_a: "crm.contacts",
          src_column_a: "email",
          src_source_id_b: "app",
          src_table_b: "app.users",
          src_column_b: "email_address",
          upstream_semantic_type_id: "type-email-001",
          entity_kind: "person",
          confidence: 0.9,
          strategy: "name_match",
          reasoning: "L5 confirmed shared semantic type email",
          evidence: {
            path: "semantic_type_anchor",
            shared_semantic_type: "email",
          },
          state: "proposed",
          state_changed_at: "2026-06-07T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].stitchId).toBe("stitch-001");
    expect(rows[0].srcTableA).toBe("crm.contacts");
    expect(rows[0].srcColumnA).toBe("email");
    expect(rows[0].srcTableB).toBe("app.users");
    expect(rows[0].srcColumnB).toBe("email_address");
    expect(rows[0].entityKind).toBe("person");
    expect(rows[0].upstreamSemanticTypeId).toBe("type-email-001");
    expect(rows[0].strategy).toBe("name_match");
    expect(rows[0].confidence).toBe(0.9);
    expect(rows[0].evidence).toEqual({
      path: "semantic_type_anchor",
      shared_semantic_type: "email",
    });
    expect(rows[0].state).toBe("proposed");
    expect(rows[0].stateChangedBy).toBeNull();
  });

  it("maps upstreamSemanticTypeId=null + entity_kind=other when the strategy is fuzzy-name-only", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          stitch_id: "stitch-002",
          src_source_id_a: "crm",
          src_table_a: "crm.misc",
          src_column_a: "user_name",
          src_source_id_b: "app",
          src_table_b: "app.misc",
          src_column_b: "username",
          upstream_semantic_type_id: null,
          entity_kind: "other",
          confidence: 0.7,
          strategy: "name_match",
          reasoning: "fuzzy-name Levenshtein similarity 0.82",
          evidence: { path: "fuzzy_name", similarity: 0.82 },
          state: "proposed",
          state_changed_at: "2026-06-07T11:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID);
    expect(rows[0].upstreamSemanticTypeId).toBeNull();
    expect(rows[0].entityKind).toBe("other");
    expect(rows[0].strategy).toBe("name_match");
  });

  it("maps sample_overlap rows with entity_kind=other (no upstream)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          stitch_id: "stitch-003",
          src_source_id_a: "crm",
          src_table_a: "crm.orders",
          src_column_a: "txn_id",
          src_source_id_b: "stripe",
          src_table_b: "stripe.charges",
          src_column_b: "txn_id",
          upstream_semantic_type_id: null,
          entity_kind: "transaction",
          confidence: 0.75,
          strategy: "sample_overlap",
          reasoning: "Jaccard 0.85",
          evidence: { path: "sample_overlap", jaccard: 0.85 },
          state: "proposed",
          state_changed_at: "2026-06-07T12:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID);
    expect(rows[0].strategy).toBe("sample_overlap");
    expect(rows[0].entityKind).toBe("transaction");
    expect(rows[0].upstreamSemanticTypeId).toBeNull();
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedEntityStitches scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getConfirmedEntityStitches(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedEntityStitches scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getRejectedEntityStitches(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getEntityStitchEvidence returns null when stitch_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    const got = await mod.getEntityStitchEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });

  it("getL5DependencyStateForStitches counts confirmed L5 types from projection_semantic_types (cross-axis probe)", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 7 }], rowCount: 1 });
    try {
      const mod = await import("../../lib/entity-stitches");
      const state = await mod.getL5DependencyStateForStitches(COMPANY_ID);
      expect(state.l5Enabled).toBe(true);
      expect(state.confirmedSemanticTypeCount).toBe(7);
      const sql = String(queryMock.mock.calls[0][0]);
      expect(sql).toContain("projection_semantic_types");
      expect(sql).toContain("state = 'confirmed'");
    } finally {
      delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    }
  });
});

describe("getEntityStitchStrategyStatus (env- + L5-type-count-driven gauges)", () => {
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
    delete process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED;
    delete process.env.WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED;
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
    delete process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED;
    delete process.env.WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("reports all strategies as disabled when the L8 master switch is off", async () => {
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.name_match.badge).toBe("disabled");
    expect(byName.name_match.productive).toBe(false);
    expect(byName.schema_shape.badge).toBe("disabled");
    expect(byName.schema_shape.productive).toBe(false);
    expect(byName.sample_overlap.badge).toBe("disabled");
    expect(byName.sample_overlap.productive).toBe(false);
  });

  it("reports name_match productive · fuzzy-only when L8 on but anchor sub-knob off", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.name_match.configured).toBe(true);
    expect(byName.name_match.productive).toBe(true);
    expect(byName.name_match.badge).toBe("production");
    expect(byName.name_match.badgeLabelOverride).toBe(
      "productive · fuzzy-only",
    );
    expect(byName.name_match.note).toContain("fuzzy-name path");
  });

  it("reports name_match configured · L5-disabled when anchor on but L5 master switch off", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED = "true";
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.name_match.configured).toBe(true);
    expect(byName.name_match.badge).toBe("configured-stubbed");
    expect(byName.name_match.badgeLabelOverride).toBe(
      "configured · L5-disabled",
    );
  });

  it("reports name_match configured · awaiting-L5-types when anchor + L5 on but no confirmed types", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // L5 confirmed-type probe → 0.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.name_match.configured).toBe(true);
    expect(byName.name_match.badge).toBe("configured-stubbed");
    expect(byName.name_match.badgeLabelOverride).toBe(
      "configured · awaiting-L5-types",
    );
  });

  it("reports name_match productive · L5-dependent when anchor + L5 on AND ≥1 confirmed type", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 4 }], rowCount: 1 });
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.name_match.configured).toBe(true);
    expect(byName.name_match.productive).toBe(true);
    expect(byName.name_match.badge).toBe("production");
    expect(byName.name_match.badgeLabelOverride).toBe(
      "productive · L5-dependent",
    );
    expect(byName.name_match.note).toContain("4 confirmed L5 semantic types");
  });

  it("reports schema_shape productive (when columns available) qualifier when L8 on and Wave 2 substrate empty (no DATABASE_URL → count=0)", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    // Note: DATABASE_URL is unset by the surrounding describe's
    // beforeEach in get-entity-stitches.test.ts when L5 probe isn't
    // needed — the catalog-mirror substrate probe falls through to
    // honest-0 (no DB).
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.schema_shape.configured).toBe(true);
    expect(byName.schema_shape.badge).toBe("configured-stubbed");
    expect(byName.schema_shape.badgeLabelOverride).toBe(
      "productive (when columns available)",
    );
    expect(byName.schema_shape.note).toContain("currently quiet");
    expect(byName.schema_shape.note).toContain("per-table catalog imports");
  });

  it("reports sample_overlap configured · empty-upstream when sub-knob on (NoopSampler today)", async () => {
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED = "true";
    const mod = await import("../../lib/entity-stitches");
    const status = await mod.getEntityStitchStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.sample_overlap.configured).toBe(true);
    expect(byName.sample_overlap.productive).toBe(false);
    expect(byName.sample_overlap.badge).toBe("configured-stubbed");
    expect(byName.sample_overlap.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
    expect(byName.sample_overlap.note).toContain("NoopSampler");
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Per-page filter widget tests (2026-05-16) — R3 reverse-arc deeplink.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeEntityStitchFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/entity-stitches");
    const { where, values } = mod.__test__._composeEntityStitchFilter(
      undefined,
      2,
    );
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes upstream_semantic_type_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/entity-stitches");
    const { where, values } = mod.__test__._composeEntityStitchFilter(
      { upstreamSemanticTypeId: "sem-111" },
      2,
    );
    expect(where).toContain("upstream_semantic_type_id = $2");
    expect(values).toEqual(["sem-111"]);
  });

  // L8 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("composes stitch_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/entity-stitches");
    const { where, values } = mod.__test__._composeEntityStitchFilter(
      { stitchId: "stitch-zzz" },
      2,
    );
    expect(where).toContain("stitch_id = $2");
    expect(values).toEqual(["stitch-zzz"]);
  });
});

describe("getProposedEntityStitches (with filter)", () => {
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

  it("appends upstream_semantic_type_id predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getProposedEntityStitches(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("upstream_semantic_type_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "sem-aaa", 200]);
  });

  it("getConfirmedEntityStitches honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getConfirmedEntityStitches(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("upstream_semantic_type_id = $2");
  });

  it("getRejectedEntityStitches threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getRejectedEntityStitches(COMPANY_ID, {
      days: 14,
      filter: { upstreamSemanticTypeId: "sem-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("upstream_semantic_type_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "sem-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });

  // L8 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("appends stitch_id producer-side predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    await mod.getProposedEntityStitches(COMPANY_ID, {
      filter: { stitchId: "stitch-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("stitch_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "stitch-aaa", 200]);
  });

  it("returns honest empty when stitch_id filter matches no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/entity-stitches");
    const rows = await mod.getProposedEntityStitches(COMPANY_ID, {
      filter: { stitchId: "stitch-nope" },
    });
    expect(rows).toEqual([]);
  });
});
