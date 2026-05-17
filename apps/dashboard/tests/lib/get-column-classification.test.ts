/**
 * /lake/column-classification accessor tests — L6 Sub-wave D (2026-06-06).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset.
 *   * SQL shape — state filter + company_id scope (tenant isolation) +
 *     ``"column"`` quoted (Postgres reserved word).
 *   * Row mapping converts the raw projection row to the dashboard
 *     ``ColumnClassificationRow`` shape, including
 *     ``upstreamSemanticTypeId`` null vs set (cross-axis-link gating).
 *   * Strategy status banner reflects env-knob state + L5-confirmed-
 *     type count probe honestly: ``semantic_type`` 4-posture matrix;
 *     ``naming_pattern`` productive when L6 on; ``domain_default``
 *     3-posture matrix.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedColumnClassifications (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedColumnClassifications (Postgres path)", () => {
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
    const mod = await import("../../lib/column-classification");
    await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_column_classifications");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
    // ``column`` is a Postgres reserved word — must be double-quoted.
    expect(sql).toContain('"column"');
  });

  it("maps the row payload to a ColumnClassificationRow with upstreamSemanticTypeId set (semantic_type strategy)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          classification_id: "cls-pii-001",
          table_id: "raw.users",
          column: "ssn",
          classification_level: "regulated",
          upstream_semantic_type_id: "type-pii-ssn-001",
          confidence: 0.95,
          strategy: "semantic_type",
          reasoning: "L5 confirmed pii_ssn → governance regulated",
          evidence: { semantic_type: "pii_ssn", regex_hit: true },
          state: "proposed",
          state_changed_at: "2026-06-06T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].classificationId).toBe("cls-pii-001");
    expect(rows[0].tableId).toBe("raw.users");
    expect(rows[0].column).toBe("ssn");
    expect(rows[0].classificationLevel).toBe("regulated");
    expect(rows[0].upstreamSemanticTypeId).toBe("type-pii-ssn-001");
    expect(rows[0].strategy).toBe("semantic_type");
    expect(rows[0].confidence).toBe(0.95);
    expect(rows[0].evidence).toEqual({
      semantic_type: "pii_ssn",
      regex_hit: true,
    });
    expect(rows[0].state).toBe("proposed");
    expect(rows[0].stateChangedBy).toBeNull();
  });

  it("maps upstreamSemanticTypeId=null when the strategy is non-L5-driven (naming_pattern)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          classification_id: "cls-np-001",
          table_id: "raw.config",
          column: "api_secret",
          classification_level: "confidential",
          upstream_semantic_type_id: null,
          confidence: 0.95,
          strategy: "naming_pattern",
          reasoning: "column name matches *_secret regex",
          evidence: { matched_regex: ".*_secret$" },
          state: "proposed",
          state_changed_at: "2026-06-06T11:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(rows[0].upstreamSemanticTypeId).toBeNull();
    expect(rows[0].strategy).toBe("naming_pattern");
    expect(rows[0].classificationLevel).toBe("confidential");
  });

  it("maps domain_default rows with domain_id in evidence (alphabetical pick)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          classification_id: "cls-dd-001",
          table_id: "raw.misc",
          column: "note",
          classification_level: "internal",
          upstream_semantic_type_id: null,
          confidence: 0.6,
          strategy: "domain_default",
          reasoning: "no explicit classification; falling back to domain pack default",
          evidence: { domain_id: "engineering", default_for_domain: "internal" },
          state: "proposed",
          state_changed_at: "2026-06-06T12:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(rows[0].strategy).toBe("domain_default");
    expect(rows[0].upstreamSemanticTypeId).toBeNull();
    expect(rows[0].confidence).toBe(0.6);
    expect(rows[0].evidence).toEqual({
      domain_id: "engineering",
      default_for_domain: "internal",
    });
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getConfirmedColumnClassifications scopes to state='confirmed'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getConfirmedColumnClassifications(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("company_id = $1");
  });

  it("getRejectedColumnClassifications scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getRejectedColumnClassifications(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });

  it("getColumnClassificationEvidence returns null when classification_id is unknown", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    const got = await mod.getColumnClassificationEvidence(COMPANY_ID, "nope");
    expect(got).toBeNull();
  });

  it("getL5DependencyState counts confirmed L5 types from projection_semantic_types (cross-axis probe)", async () => {
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 7 }], rowCount: 1 });
    try {
      const mod = await import("../../lib/column-classification");
      const state = await mod.getL5DependencyState(COMPANY_ID);
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

describe("getColumnClassificationStrategyStatus (env- + L5-type-count-driven gauges)", () => {
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
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED;
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
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED;
    delete process.env.WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED;
    delete process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("reports all strategies as disabled when the L6 master switch is off", async () => {
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.badge).toBe("disabled");
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.naming_pattern.badge).toBe("disabled");
    expect(byName.naming_pattern.productive).toBe(false);
    expect(byName.domain_default.badge).toBe("disabled");
    expect(byName.domain_default.productive).toBe(false);
  });

  it("reports naming_pattern productive when L6 master switch is on (surfaces coverage list)", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.naming_pattern.configured).toBe(true);
    expect(byName.naming_pattern.productive).toBe(true);
    expect(byName.naming_pattern.badge).toBe("production");
    // Coverage list surfaced verbatim per Sub-wave C handoff concern #1.
    expect(byName.naming_pattern.note).toContain("`*_secret`");
    expect(byName.naming_pattern.note).toContain("`*_ssn`");
    expect(byName.naming_pattern.note).toContain("regulated");
    expect(byName.naming_pattern.note).toContain("0.95");
  });

  it("reports semantic_type configured · L5-disabled when L6 sub-knob on but L5 master switch off", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED = "true";
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.semantic_type.badge).toBe("configured-stubbed");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "configured · L5-disabled",
    );
  });

  it("reports semantic_type configured · awaiting-L5-types when L6+L5 on but no confirmed types", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // L5 confirmed-type probe → 0; domain pack probe → 0.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(false);
    expect(byName.semantic_type.badge).toBe("configured-stubbed");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "configured · awaiting-L5-types",
    );
  });

  it("reports semantic_type productive · L5-dependent when L6+L5 on AND ≥1 confirmed type", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED = "true";
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // L5 confirmed-type probe → 4; domain pack probe → 0.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 4 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.semantic_type.configured).toBe(true);
    expect(byName.semantic_type.productive).toBe(true);
    expect(byName.semantic_type.badge).toBe("production");
    expect(byName.semantic_type.badgeLabelOverride).toBe(
      "productive · L5-dependent",
    );
    expect(byName.semantic_type.note).toContain("4 confirmed L5 semantic types");
  });

  it("reports domain_default configured · awaiting-domain-pack when L6 sub-knob on but no domain registered", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // L5 probe (L5 disabled → no probe done in this path but reader
    // still runs L5DependencyState; ensure mock order).
    // getL5DependencyState pgQuery (since DATABASE_URL set).
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    // _hasDomainPack → 0.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.domain_default.configured).toBe(true);
    expect(byName.domain_default.productive).toBe(false);
    expect(byName.domain_default.badge).toBe("configured-stubbed");
    expect(byName.domain_default.badgeLabelOverride).toBe(
      "configured · awaiting-domain-pack",
    );
  });

  it("reports domain_default productive · domain-pack-dependent with rationale (handoff concern #3)", async () => {
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    // _hasDomainPack → 3.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 3 }], rowCount: 1 });
    const mod = await import("../../lib/column-classification");
    const status = await mod.getColumnClassificationStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.domain_default.configured).toBe(true);
    expect(byName.domain_default.productive).toBe(true);
    expect(byName.domain_default.badge).toBe("production");
    expect(byName.domain_default.badgeLabelOverride).toBe(
      "productive · domain-pack-dependent",
    );
    expect(byName.domain_default.note).toContain("0.60 baseline confidence");
    expect(byName.domain_default.note).toContain("alphabetically-first");
    expect(byName.domain_default.note).toContain("admins should override");
  });
});

// ─── R5 L4↦L6 reverse-arc accessor (Recipe Addendum #3) ─────────────────

describe("getSchemaImpactCountByClassification (no DATABASE_URL)", () => {
  it("returns {} when DATABASE_URL is unset (honest empty)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/column-classification");
    const map = await mod.getSchemaImpactCountByClassification(COMPANY_ID);
    expect(map).toEqual({});
  });
});

describe("getSchemaImpactCountByClassification (Postgres path)", () => {
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

  it("issues state IN ('proposed','confirmed') SQL grouping by evidence->>upstream_classification_id", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getSchemaImpactCountByClassification(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_schema_impacts");
    expect(sql).toContain("state IN ('proposed', 'confirmed')");
    expect(sql).toContain("company_id = $1");
    expect(sql).toContain("upstream_classification_id");
    expect(sql).toContain("evidence ? 'upstream_classification_id'");
    expect(sql).toContain("GROUP BY");
  });

  it("returns a map keyed by upstream_classification_id", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        { upstream_classification_id: "class-aaa", n: 4 },
        { upstream_classification_id: "class-bbb", n: 2 },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/column-classification");
    const map = await mod.getSchemaImpactCountByClassification(COMPANY_ID);
    expect(map).toEqual({ "class-aaa": 4, "class-bbb": 2 });
  });

  it("returns {} when the query throws (honest empty fallback)", async () => {
    queryMock.mockRejectedValueOnce(new Error("relation does not exist"));
    const mod = await import("../../lib/column-classification");
    const map = await mod.getSchemaImpactCountByClassification(COMPANY_ID);
    expect(map).toEqual({});
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Per-page filter widget tests (2026-05-16) — R2 reverse-arc deeplink.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeColumnClassificationFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/column-classification");
    const { where, values } =
      mod.__test__._composeColumnClassificationFilter(undefined, 2);
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes upstream_semantic_type_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/column-classification");
    const { where, values } =
      mod.__test__._composeColumnClassificationFilter(
        { upstreamSemanticTypeId: "sem-111" },
        2,
      );
    expect(where).toContain("upstream_semantic_type_id = $2");
    expect(values).toEqual(["sem-111"]);
  });
});

describe("getProposedColumnClassifications (with filter)", () => {
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
    const mod = await import("../../lib/column-classification");
    await mod.getProposedColumnClassifications(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("upstream_semantic_type_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "sem-aaa", 200]);
  });

  it("getConfirmedColumnClassifications honors filter on confirmed state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getConfirmedColumnClassifications(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("upstream_semantic_type_id = $2");
  });

  it("getRejectedColumnClassifications threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getRejectedColumnClassifications(COMPANY_ID, {
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
    const mod = await import("../../lib/column-classification");
    const rows = await mod.getProposedColumnClassifications(COMPANY_ID, {
      filter: { upstreamSemanticTypeId: "sem-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Producer-side ``?classification_id=`` deep-link filter (2026-05-16).
// Added alongside the existing ``upstreamSemanticTypeId`` filter.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeColumnClassificationFilter (classificationId)", () => {
  it("composes classificationId as a primary-key column predicate", async () => {
    const mod = await import("../../lib/column-classification");
    const { where, values } =
      mod.__test__._composeColumnClassificationFilter(
        { classificationId: "cls-111" },
        2,
      );
    expect(where).toContain("classification_id = $2");
    expect(values).toEqual(["cls-111"]);
  });

  it("composes both filters in order when both are set", async () => {
    const mod = await import("../../lib/column-classification");
    const { where, values } =
      mod.__test__._composeColumnClassificationFilter(
        {
          upstreamSemanticTypeId: "sem-111",
          classificationId: "cls-222",
        },
        2,
      );
    expect(where).toContain("upstream_semantic_type_id = $2");
    expect(where).toContain("classification_id = $3");
    expect(values).toEqual(["sem-111", "cls-222"]);
  });
});

describe("getProposedColumnClassifications (with classificationId filter)", () => {
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

  it("appends classification_id predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getProposedColumnClassifications(COMPANY_ID, {
      filter: { classificationId: "cls-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("classification_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "cls-aaa", 200]);
  });

  it("getConfirmedColumnClassifications honors classificationId on confirmed", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getConfirmedColumnClassifications(COMPANY_ID, {
      filter: { classificationId: "cls-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'confirmed'");
    expect(sql).toContain("classification_id = $2");
  });

  it("getRejectedColumnClassifications threads classificationId after days", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/column-classification");
    await mod.getRejectedColumnClassifications(COMPANY_ID, {
      days: 14,
      filter: { classificationId: "cls-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("classification_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "cls-ccc",
      200,
    ]);
  });
});
