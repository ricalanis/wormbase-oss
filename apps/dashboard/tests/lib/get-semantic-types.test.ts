/**
 * /lake/semantic-types accessor tests — L5 Sub-wave D (2026-06-05).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset (handoff concern #4).
 *   * SQL shape — state filter + company_id scope (tenant isolation) +
 *     ``"column"`` quoted (Postgres reserved word).
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``SemanticTypeRow`` shape, including the 19-value semantic_type
 *     enum + strategy enum (column_name / value_pattern / distribution).
 *   * Strategy status banner reflects env-knob state honestly:
 *     ``column_name`` productive when L5 on; ``value_pattern`` +
 *     ``distribution`` configured · empty-upstream when env knobs on;
 *     ``disabled`` when their env knobs are off.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedSemanticTypes (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/semantic-types");
    const rows = await mod.getProposedSemanticTypes(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedSemanticTypes (Postgres path)", () => {
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

  it("issues a state='proposed' SQL with company_id scope + quoted 'column'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getProposedSemanticTypes(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_semantic_types");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
    // ``column`` is a Postgres reserved word — must be double-quoted.
    expect(sql).toContain('"column"');
  });

  it("maps the row payload to a SemanticTypeRow (column_name strategy, email type)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          type_id: "type-email-001",
          table_id: "dbt.dim_users",
          column: "email_address",
          semantic_type: "email",
          confidence: 0.95,
          strategy: "column_name",
          reasoning: "column name matches email regex /^email/i",
          evidence: { matched_regex: "^email" },
          state: "proposed",
          state_changed_at: "2026-06-05T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/semantic-types");
    const rows = await mod.getProposedSemanticTypes(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].typeId).toBe("type-email-001");
    expect(rows[0].tableId).toBe("dbt.dim_users");
    expect(rows[0].column).toBe("email_address");
    expect(rows[0].semanticType).toBe("email");
    expect(rows[0].strategy).toBe("column_name");
    expect(rows[0].confidence).toBe(0.95);
    expect(rows[0].evidence).toEqual({ matched_regex: "^email" });
    expect(rows[0].state).toBe("proposed");
    expect(rows[0].stateChangedBy).toBeNull();
  });

  it("maps PII-band semantic types correctly (pii_credit_card from value_pattern)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          type_id: "type-cc-001",
          table_id: "raw.payments",
          column: "card_number",
          semantic_type: "pii_credit_card",
          confidence: 0.88,
          strategy: "value_pattern",
          reasoning: "Luhn-valid digit sequences in sampled values",
          evidence: { match_count: 18, sample_n: 20 },
          state: "proposed",
          state_changed_at: "2026-06-05T11:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/semantic-types");
    const rows = await mod.getProposedSemanticTypes(COMPANY_ID);
    expect(rows[0].semanticType).toBe("pii_credit_card");
    expect(rows[0].strategy).toBe("value_pattern");
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/semantic-types");
    const rows = await mod.getProposedSemanticTypes(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedSemanticTypes scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getConfirmedSemanticTypes(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedSemanticTypes scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getRejectedSemanticTypes(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getSemanticTypeEvidence returns null when type_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    const got = await mod.getSemanticTypeEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });
});

describe("getSemanticTypeStrategyStatus (env-knob-driven gauges)", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED;
  });

  afterEach(() => {
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED;
  });

  it("reports all strategies as disabled when the L5 master switch is off", async () => {
    const mod = await import("../../lib/semantic-types");
    const status = await mod.getSemanticTypeStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.column_name.badge).toBe("disabled");
    expect(byName.column_name.productive).toBe(false);
    expect(byName.value_pattern.badge).toBe("disabled");
    expect(byName.distribution.badge).toBe("disabled");
  });

  it("reports column_name productive when the L5 master switch is on", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/semantic-types");
    const status = await mod.getSemanticTypeStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.column_name.configured).toBe(true);
    expect(byName.column_name.productive).toBe(true);
    expect(byName.column_name.badge).toBe("production");
    // No upstream sampler / stats dependency.
    expect(byName.column_name.note).toContain("No upstream sampler");
  });

  it("reports value_pattern configured · empty-upstream when its env knob is on", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED = "true";
    const mod = await import("../../lib/semantic-types");
    const status = await mod.getSemanticTypeStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.value_pattern.configured).toBe(true);
    expect(byName.value_pattern.productive).toBe(false);
    expect(byName.value_pattern.badge).toBe("configured-stubbed");
    expect(byName.value_pattern.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
  });

  it("reports distribution configured · empty-upstream when its env knob is on", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED = "true";
    const mod = await import("../../lib/semantic-types");
    const status = await mod.getSemanticTypeStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.distribution.configured).toBe(true);
    expect(byName.distribution.productive).toBe(false);
    expect(byName.distribution.badge).toBe("configured-stubbed");
    expect(byName.distribution.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
  });

  it("keeps value_pattern + distribution disabled when the L5 master switch is off (even with their sub-knobs on)", async () => {
    // Sub-knobs without master switch must NOT graduate to configured.
    process.env.WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED = "true";
    const mod = await import("../../lib/semantic-types");
    const status = await mod.getSemanticTypeStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.value_pattern.configured).toBe(false);
    expect(byName.value_pattern.badge).toBe("disabled");
    expect(byName.distribution.configured).toBe(false);
    expect(byName.distribution.badge).toBe("disabled");
  });
});

// ─── R2/R3/R4/R6 reverse-arc accessors (Recipe Addendum #3) ────────────
//
// The L5 page is the most-consumed producer: 4 downstream axes consult
// it. Test each accessor for:
//   * Honest empty when no Postgres.
//   * SQL shape (state filter + GROUP BY + scope).
//   * Map shape from rows.

describe("getClassificationCountBySemanticType (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getClassificationCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
  });
});

describe("getEntityStitchCountBySemanticType (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getEntityStitchCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
  });
});

describe("getQualityCheckCountBySemanticType (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getQualityCheckCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
  });
});

describe("getSchemaImpactCountBySemanticType (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getSchemaImpactCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
  });
});

describe("L5 reverse-arc accessors (Postgres path)", () => {
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

  it("R2: getClassificationCountBySemanticType SQL hits projection_column_classifications + first-class column", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getClassificationCountBySemanticType(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_column_classifications");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("upstream_semantic_type_id IS NOT NULL");
    expect(sql).toContain("GROUP BY upstream_semantic_type_id");
  });

  it("R2: returns count map keyed by upstream_semantic_type_id", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        { upstream_semantic_type_id: "type-a", n: 5 },
        { upstream_semantic_type_id: "type-b", n: 1 },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/semantic-types");
    const map = await mod.getClassificationCountBySemanticType(COMPANY_ID);
    expect(map).toEqual({ "type-a": 5, "type-b": 1 });
  });

  it("R3: getEntityStitchCountBySemanticType SQL hits projection_entity_stitches + first-class column", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getEntityStitchCountBySemanticType(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_entity_stitches");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("upstream_semantic_type_id IS NOT NULL");
    expect(sql).toContain("GROUP BY upstream_semantic_type_id");
  });

  it("R4: getQualityCheckCountBySemanticType SQL hits projection_quality_checks + evidence JSON accessor", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getQualityCheckCountBySemanticType(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_quality_checks");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("evidence ? 'upstream_semantic_type_id'");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
  });

  it("R4: returns map shape on populated evidence rows", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [{ upstream_semantic_type_id: "type-a", n: 2 }],
      rowCount: 1,
    });
    const mod = await import("../../lib/semantic-types");
    const map = await mod.getQualityCheckCountBySemanticType(COMPANY_ID);
    expect(map).toEqual({ "type-a": 2 });
  });

  it("R6: getSchemaImpactCountBySemanticType SQL hits projection_schema_impacts + evidence JSON accessor", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getSchemaImpactCountBySemanticType(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_schema_impacts");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("evidence ? 'upstream_semantic_type_id'");
    expect(sql).toContain("evidence->>'upstream_semantic_type_id'");
  });

  it("R6: returns map shape on populated evidence rows", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        { upstream_semantic_type_id: "type-a", n: 3 },
        { upstream_semantic_type_id: "type-b", n: 1 },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/semantic-types");
    const map = await mod.getSchemaImpactCountBySemanticType(COMPANY_ID);
    expect(map).toEqual({ "type-a": 3, "type-b": 1 });
  });

  it("all 4 accessors return {} when the query throws", async () => {
    queryMock.mockRejectedValue(new Error("relation does not exist"));
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getClassificationCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
    expect(await mod.getEntityStitchCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
    expect(await mod.getQualityCheckCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
    expect(await mod.getSchemaImpactCountBySemanticType(COMPANY_ID)).toEqual(
      {},
    );
  });

  it("filters out zero counts (defensive)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        { upstream_semantic_type_id: "type-zero", n: 0 },
        { upstream_semantic_type_id: "type-real", n: 7 },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/semantic-types");
    expect(await mod.getClassificationCountBySemanticType(COMPANY_ID)).toEqual(
      { "type-real": 7 },
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Producer-side ``?type_id=`` deep-link filter (2026-05-16).
// ─────────────────────────────────────────────────────────────────────────

describe("_composeSemanticTypeFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/semantic-types");
    const { where, values } =
      mod.__test__._composeSemanticTypeFilter(undefined, 2);
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes typeId as a primary-key column predicate", async () => {
    const mod = await import("../../lib/semantic-types");
    const { where, values } = mod.__test__._composeSemanticTypeFilter(
      { typeId: "type-aaa" },
      2,
    );
    expect(where).toContain("type_id = $2");
    expect(values).toEqual(["type-aaa"]);
  });
});

describe("getProposedSemanticTypes (with typeId filter)", () => {
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

  it("appends type_id predicate + threads param on proposed", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getProposedSemanticTypes(COMPANY_ID, {
      filter: { typeId: "type-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("type_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "type-aaa", 200]);
  });

  it("getConfirmedSemanticTypes honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getConfirmedSemanticTypes(COMPANY_ID, {
      filter: { typeId: "type-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("type_id = $2");
  });

  it("getRejectedSemanticTypes threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    await mod.getRejectedSemanticTypes(COMPANY_ID, {
      days: 14,
      filter: { typeId: "type-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("type_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "type-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/semantic-types");
    const rows = await mod.getProposedSemanticTypes(COMPANY_ID, {
      filter: { typeId: "type-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });
});
