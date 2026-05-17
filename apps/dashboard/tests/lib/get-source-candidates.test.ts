/**
 * /lake/source-candidates accessor tests — L1 Sub-wave D
 * (2026-06-08).
 *
 * Mocks ``pg`` so the accessors run without a live Postgres dep.
 * Verifies:
 *
 *   * Honest empty when DATABASE_URL is unset (NO FIXTURE return per
 *     CLAUDE.md §9).
 *   * SQL shape — state filter + company_id scope (tenant isolation)
 *     + ``projection_source_candidates`` table.
 *   * Row mapping preserves ``downstreamSourceProposedId`` NULL vs
 *     set (sui-generis link gating, Sub-wave C handoff #1).
 *   * Strategy banner posture per spec §4.7 — kpi_gap 3-state +
 *     channel_mention 3-state + complementarity 3-state matrices
 *     honestly keyed off env knobs and upstream count probes.
 *   * Sub-wave C handoff concern #5: the silver-conversation count
 *     queries ``projection_conversations`` (NOT
 *     ``projection_silver_conversations``).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getProposedSourceCandidates (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set (honest empty, no FIXTURE)", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getProposedSourceCandidates(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getProposedSourceCandidates (Postgres path)", () => {
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

  it("issues a state='proposed' SQL with company_id scope against projection_source_candidates", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getProposedSourceCandidates(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_source_candidates");
    expect(sql).toContain("state = 'proposed'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps a kpi_gap-proposed row with NULL domain_id_hint honestly (Wave 1 limitation, handoff concern #2)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          candidate_id: "cand-kpi-001",
          proposed_kind: "stripe",
          proposed_identifier: "monthly_recurring_revenue",
          domain_id_hint: null,
          strategy: "kpi_gap",
          reasoning: "KPI 'mrr' has no upstream source; matches *_revenue → stripe",
          confidence: 0.7,
          evidence: { kpi_node_id: "kpi-mrr-001" },
          downstream_source_proposed_id: null,
          state: "proposed",
          state_changed_at: "2026-06-08T09:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getProposedSourceCandidates(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].candidateId).toBe("cand-kpi-001");
    expect(rows[0].proposedKind).toBe("stripe");
    expect(rows[0].proposedIdentifier).toBe("monthly_recurring_revenue");
    // Honest NULL — Wave 1 limitation per handoff concern #2.
    expect(rows[0].domainIdHint).toBeNull();
    expect(rows[0].strategy).toBe("kpi_gap");
    expect(rows[0].evidence).toEqual({ kpi_node_id: "kpi-mrr-001" });
    expect(rows[0].downstreamSourceProposedId).toBeNull();
    expect(rows[0].state).toBe("proposed");
  });

  it("maps a channel_mention row with message_refs evidence", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          candidate_id: "cand-chan-001",
          proposed_kind: "snowflake",
          proposed_identifier: "our snowflake warehouse",
          domain_id_hint: null,
          strategy: "channel_mention",
          reasoning: "Pattern match in #data-eng: 'our snowflake' (3 mentions)",
          confidence: 0.6,
          evidence: { message_refs: ["msg-001", "msg-002"] },
          downstream_source_proposed_id: null,
          state: "proposed",
          state_changed_at: "2026-06-08T10:00:00.000Z",
          state_changed_by: null,
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getProposedSourceCandidates(COMPANY_ID);
    expect(rows[0].strategy).toBe("channel_mention");
    expect(rows[0].evidence).toEqual({
      message_refs: ["msg-001", "msg-002"],
    });
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getProposedSourceCandidates(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getPromotedSourceCandidates scopes to state='promoted'", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getPromotedSourceCandidates(COMPANY_ID);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'promoted'");
    expect(sql).toContain("company_id = $1");
  });

  it("maps downstreamSourceProposedId=null for promoted rows where dual-write did not fire (handoff #1)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          candidate_id: "cand-prom-001",
          proposed_kind: "csv_local",
          proposed_identifier: "/data/inbound/quarterly.csv",
          domain_id_hint: null,
          strategy: "complementarity",
          reasoning: "Portfolio gap — no file source connected",
          confidence: 0.8,
          evidence: { portfolio_snapshot: ["postgres", "stripe"] },
          downstream_source_proposed_id: null,
          state: "promoted",
          state_changed_at: "2026-06-08T11:00:00.000Z",
          state_changed_by: "admin-001",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getPromotedSourceCandidates(COMPANY_ID);
    expect(rows[0].state).toBe("promoted");
    expect(rows[0].downstreamSourceProposedId).toBeNull();
  });

  it("maps downstreamSourceProposedId set for promoted rows when dual-write succeeded", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          candidate_id: "cand-prom-002",
          proposed_kind: "postgres",
          proposed_identifier: "warehouse_main",
          domain_id_hint: null,
          strategy: "kpi_gap",
          reasoning: "ok",
          confidence: 0.85,
          evidence: {},
          downstream_source_proposed_id: "source-uuid-abc-123",
          state: "promoted",
          state_changed_at: "2026-06-08T11:30:00.000Z",
          state_changed_by: "admin-001",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getPromotedSourceCandidates(COMPANY_ID);
    expect(rows[0].downstreamSourceProposedId).toBe("source-uuid-abc-123");
  });

  it("getRejectedSourceCandidates scopes to state='rejected' AND date window", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getRejectedSourceCandidates(COMPANY_ID, { days: 14 });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("INTERVAL '1 day'");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, 14, 200]);
  });
});

describe("getSourceCandidateStrategyStatus (env- + upstream-count-driven gauges)", () => {
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
    delete process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED;
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
    delete process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED;
    delete process.env.WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED;
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("reports all strategies as disabled when the L1 master switch is off", async () => {
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.kpi_gap.badge).toBe("disabled");
    expect(byName.kpi_gap.productive).toBe(false);
    expect(byName.channel_mention.badge).toBe("disabled");
    expect(byName.channel_mention.productive).toBe(false);
    expect(byName.complementarity.badge).toBe("disabled");
    expect(byName.complementarity.productive).toBe(false);
  });

  it("reports kpi_gap configured · awaiting-kpi-tree-population when KPI tree is empty", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    // 3 count probes — kpi=0, conversations=0, sources=0.
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.kpi_gap.configured).toBe(true);
    expect(byName.kpi_gap.productive).toBe(false);
    expect(byName.kpi_gap.badge).toBe("configured-stubbed");
    expect(byName.kpi_gap.badgeLabelOverride).toBe(
      "configured · awaiting-kpi-tree-population",
    );
  });

  it("reports kpi_gap productive · KPI-dependent when KPI tree has nodes", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 4 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.kpi_gap.productive).toBe(true);
    expect(byName.kpi_gap.badge).toBe("production");
    expect(byName.kpi_gap.badgeLabelOverride).toBe(
      "productive · KPI-dependent",
    );
    expect(byName.kpi_gap.note).toContain("4 KPI nodes");
  });

  it("reports channel_mention configured · empty-upstream when conversations empty", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.channel_mention.configured).toBe(true);
    expect(byName.channel_mention.productive).toBe(false);
    expect(byName.channel_mention.badge).toBe("configured-stubbed");
    expect(byName.channel_mention.badgeLabelOverride).toBe(
      "configured · empty-upstream",
    );
    // Sub-wave C handoff concern #5 — the table is named
    // ``projection_conversations``, NOT
    // ``projection_silver_conversations``.
    expect(byName.channel_mention.note).toContain("projection_conversations");
  });

  it("reports channel_mention productive · silver-dependent when conversations populated", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 27 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.channel_mention.productive).toBe(true);
    expect(byName.channel_mention.badgeLabelOverride).toBe(
      "productive · silver-dependent",
    );
    expect(byName.channel_mention.note).toContain("27 silver-conversation");
    // Sub-wave C handoff concern #6 — 24h × 1000-cap surfaced.
    expect(byName.channel_mention.note).toContain("1000 rows");
    expect(byName.channel_mention.note).toContain("24h window");
  });

  it("reports complementarity configured · awaiting-first-source when no sources connected", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.complementarity.configured).toBe(true);
    expect(byName.complementarity.productive).toBe(false);
    expect(byName.complementarity.badge).toBe("configured-stubbed");
    expect(byName.complementarity.badgeLabelOverride).toBe(
      "configured · awaiting-first-source",
    );
  });

  it("reports complementarity productive · portfolio-dependent when ≥1 source connected", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    queryMock.mockResolvedValueOnce({ rows: [{ n: 3 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    const status = await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const byName = Object.fromEntries(status.map((s) => [s.strategy, s]));
    expect(byName.complementarity.productive).toBe(true);
    expect(byName.complementarity.badgeLabelOverride).toBe(
      "productive · portfolio-dependent",
    );
    expect(byName.complementarity.note).toContain("3 connected sources");
  });

  it("upstream count probe targets projection_conversations (NOT projection_silver_conversations) per handoff #5", async () => {
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED = "true";
    process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED = "true";
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock.mockResolvedValue({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/source-candidates");
    await mod.getSourceCandidateStrategyStatus(COMPANY_ID);
    const sqls = queryMock.mock.calls.map((c) => String(c[0]));
    const hasProjConv = sqls.some((s) =>
      /\bprojection_conversations\b/.test(s),
    );
    const hasProjSilver = sqls.some((s) =>
      /projection_silver_conversations/.test(s),
    );
    expect(hasProjConv).toBe(true);
    expect(hasProjSilver).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Per-page filter widget tests (2026-05-16) — L1 producer-side PK deep-link
// (?candidate_id=) added by the Lake-Side Overview activity-stream drill-in
// completion bundle. Mirrors the producer-deep-links bundle (bdee480) shape.
// ─────────────────────────────────────────────────────────────────────────

describe("_composeSourceCandidateFilter (SQL composition)", () => {
  it("returns empty fragment when filter is undefined", async () => {
    const mod = await import("../../lib/source-candidates");
    const { where, values } = mod.__test__._composeSourceCandidateFilter(
      undefined,
      2,
    );
    expect(where).toBe("");
    expect(values).toEqual([]);
  });

  it("composes candidate_id as a first-class column predicate", async () => {
    const mod = await import("../../lib/source-candidates");
    const { where, values } = mod.__test__._composeSourceCandidateFilter(
      { candidateId: "cand-abc" },
      2,
    );
    expect(where).toContain("candidate_id = $2");
    expect(values).toEqual(["cand-abc"]);
  });
});

describe("getProposedSourceCandidates (with filter)", () => {
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

  it("appends candidate_id predicate + threads param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getProposedSourceCandidates(COMPANY_ID, {
      filter: { candidateId: "cand-aaa" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("candidate_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([COMPANY_ID, "cand-aaa", 200]);
  });

  it("getPromotedSourceCandidates honors filter on promoted state", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getPromotedSourceCandidates(COMPANY_ID, {
      filter: { candidateId: "cand-bbb" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'promoted'");
    expect(sql).toContain("candidate_id = $2");
  });

  it("getRejectedSourceCandidates threads filter after the days param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    await mod.getRejectedSourceCandidates(COMPANY_ID, {
      days: 14,
      filter: { candidateId: "cand-ccc" },
    });
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain("candidate_id = $3");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      14,
      "cand-ccc",
      200,
    ]);
  });

  it("returns honest empty when filter matches no rows + maintains companyId scope", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/source-candidates");
    const rows = await mod.getProposedSourceCandidates(COMPANY_ID, {
      filter: { candidateId: "cand-nope" },
    });
    expect(rows).toEqual([]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("company_id = $1");
  });
});
