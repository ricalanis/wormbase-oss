/**
 * Wave 3 Task 4 — getQueryOutcomes / getQueryTemplates / getSemanticGaps
 * accessors.
 *
 * Strategy mirrors the Task 2 (agents) tests: mock the `pg` module to
 * drive controlled rows through each accessor. We verify:
 *
 *   - empty-state contract when DATABASE_URL is unset
 *   - column-to-camelCase mapping
 *   - JSON parsing for ``final_query_spec`` / ``result_summary`` /
 *     ``query_spec`` / ``promoted_from_outcome_ids``
 *   - tenant scoping in the SQL params
 *   - graceful empty on table-missing errors
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

function setupPgMock() {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();
  vi.doMock("pg", () => {
    class Pool {
      connect = connectMock;
      on = onMock;
      constructor(_opts: unknown) {}
    }
    return { default: { Pool }, Pool };
  });
  return { queryMock, releaseMock, connectMock, onMock };
}

// ─── getQueryOutcomes ─────────────────────────────────────────────────────

describe("getQueryOutcomes (Wave 3 Task 4)", () => {
  let queryMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock = setupPgMock().queryMock;
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns [] when DATABASE_URL is not set", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryOutcomes(COMPANY_ID);
    expect(out).toEqual([]);
  });

  it("returns [] when no outcomes have been recorded", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryOutcomes(COMPANY_ID);
    expect(out).toEqual([]);
  });

  it("maps projection rows to camelCase + parses JSON columns", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "outcome-1",
          agent_query_id: "audit-trail-1",
          nl_question: "what was Q3 revenue?",
          final_query_spec: {
            metric: "revenue_total",
            time_grain: "quarter",
          },
          result_summary: { row_count: 1, preview: "$1.2M" },
          used: true,
          useful: true,
          user_correction: null,
          quality_score: "1.0000",
          recorded_at: new Date("2026-05-11T10:00:00Z"),
        },
        {
          id: "outcome-2",
          agent_query_id: "audit-trail-2",
          nl_question: "what was MoM churn?",
          // JSON-as-string (round-tripping through some pg drivers)
          final_query_spec: '{"metric":"churn_rate"}',
          result_summary: '{"value":0.034}',
          used: "t",
          useful: 0,
          user_correction: "wanted gross churn",
          quality_score: "0.2000",
          recorded_at: "2026-05-11T11:00:00Z",
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryOutcomes(COMPANY_ID);
    expect(out).toHaveLength(2);
    expect(out[0].id).toBe("outcome-1");
    expect(out[0].agentQueryId).toBe("audit-trail-1");
    expect(out[0].finalQuerySpec).toEqual({
      metric: "revenue_total",
      time_grain: "quarter",
    });
    expect(out[0].used).toBe(true);
    expect(out[0].useful).toBe(true);
    expect(out[0].qualityScore).toBe("1.0000");
    expect(out[0].recordedAt).toBe("2026-05-11T10:00:00.000Z");

    // JSON-as-string fallback parses correctly.
    expect(out[1].finalQuerySpec).toEqual({ metric: "churn_rate" });
    expect(out[1].resultSummary).toEqual({ value: 0.034 });
    expect(out[1].used).toBe(true); // "t" coerces to true
    expect(out[1].useful).toBe(false); // 0 coerces to false
    expect(out[1].userCorrection).toBe("wanted gross churn");
  });

  it("scopes the SQL by company_id and respects the limit param", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/query-improvement");
    await mod.getQueryOutcomes(COMPANY_ID, { limit: 10 });
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toContain(COMPANY_ID);
    expect(params).toContain(10);
  });

  it("returns [] honestly when the projection table is missing", async () => {
    queryMock.mockRejectedValueOnce(
      new Error('relation "projection_query_outcomes" does not exist'),
    );
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryOutcomes(COMPANY_ID);
    expect(out).toEqual([]);
  });
});

// ─── getQueryTemplates ────────────────────────────────────────────────────

describe("getQueryTemplates (Wave 3 Task 4)", () => {
  let queryMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock = setupPgMock().queryMock;
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns [] when DATABASE_URL is not set", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryTemplates(COMPANY_ID);
    expect(out).toEqual([]);
  });

  it("maps rows and parses the promoted_from_outcome_ids array", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "tpl-1",
          domain_id: "domain-finance",
          nl_intent: "revenue_by_quarter",
          query_spec: { metric: "revenue_total", time_grain: "quarter" },
          promoted_from_outcome_ids: ["outcome-1", "outcome-2", "outcome-3"],
          quality_score: "0.9500",
          hit_count: 12,
          promoted_at: new Date("2026-05-11T10:00:00Z"),
        },
        {
          id: "tpl-2",
          domain_id: "domain-finance",
          nl_intent: "dau_last_30d",
          query_spec: '{"metric":"dau"}',
          promoted_from_outcome_ids: '["outcome-4","outcome-5","outcome-6"]',
          quality_score: "0.9000",
          hit_count: "3",
          promoted_at: "2026-05-11T11:00:00Z",
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getQueryTemplates(COMPANY_ID);
    expect(out).toHaveLength(2);
    expect(out[0].promotedFromOutcomeIds).toEqual([
      "outcome-1",
      "outcome-2",
      "outcome-3",
    ]);
    expect(out[0].hitCount).toBe(12);
    expect(out[0].querySpec).toEqual({
      metric: "revenue_total",
      time_grain: "quarter",
    });
    // JSON-as-string array round-trip works.
    expect(out[1].promotedFromOutcomeIds).toEqual([
      "outcome-4",
      "outcome-5",
      "outcome-6",
    ]);
    expect(out[1].hitCount).toBe(3);
    expect(out[1].querySpec).toEqual({ metric: "dau" });
  });

  it("filters by domain_id when provided", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/query-improvement");
    await mod.getQueryTemplates(COMPANY_ID, { domainId: "domain-finance" });
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toContain(COMPANY_ID);
    expect(params).toContain("domain-finance");
  });
});

// ─── getSemanticGaps ──────────────────────────────────────────────────────

describe("getSemanticGaps (Wave 3 Task 4)", () => {
  let queryMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";
    queryMock = setupPgMock().queryMock;
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns [] when DATABASE_URL is not set", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getSemanticGaps(COMPANY_ID);
    expect(out).toEqual([]);
  });

  it("returns [] when no gaps have been proposed", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getSemanticGaps(COMPANY_ID);
    expect(out).toEqual([]);
  });

  it("maps gap payloads with all three reasons", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          entry_id: "entry-1",
          ts: new Date("2026-05-11T10:00:00Z"),
          payload: {
            audit_trail_id: "audit-1",
            agent_id: "agent-claude",
            nl_question: "show me ARR by region",
            reason: "no_match",
            proposed_metric_name: "arr_by_region",
          },
        },
        {
          entry_id: "entry-2",
          ts: new Date("2026-05-11T11:00:00Z"),
          payload: {
            audit_trail_id: "audit-2",
            agent_id: "agent-kimi",
            nl_question: "uhh quarterly something",
            reason: "ambiguous",
            proposed_metric_name: null,
          },
        },
        {
          entry_id: "entry-3",
          ts: new Date("2026-05-11T12:00:00Z"),
          payload: {
            audit_trail_id: "audit-3",
            agent_id: "agent-openai",
            nl_question: "active accounts trend",
            reason: "low_confidence",
            proposed_metric_name: "active_accounts_dau",
          },
        },
      ],
      rowCount: 3,
    });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getSemanticGaps(COMPANY_ID);
    expect(out).toHaveLength(3);
    expect(out[0].reason).toBe("no_match");
    expect(out[0].proposedMetricName).toBe("arr_by_region");
    expect(out[0].agentId).toBe("agent-claude");
    expect(out[0].id).toBe("audit-1");
    expect(out[1].reason).toBe("ambiguous");
    expect(out[1].proposedMetricName).toBeNull();
    expect(out[2].reason).toBe("low_confidence");
  });

  it("drops rows missing nl_question or agent_id (defensive)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          entry_id: "entry-good",
          ts: new Date("2026-05-11T10:00:00Z"),
          payload: {
            audit_trail_id: "audit-good",
            agent_id: "agent-1",
            nl_question: "valid",
            reason: "no_match",
            proposed_metric_name: null,
          },
        },
        {
          entry_id: "entry-missing-agent",
          ts: new Date("2026-05-11T10:00:00Z"),
          payload: {
            reason: "no_match",
            nl_question: "missing agent_id",
          },
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/query-improvement");
    const out = await mod.getSemanticGaps(COMPANY_ID);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("audit-good");
  });

  it("scopes the SQL by company_id", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/query-improvement");
    await mod.getSemanticGaps(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toContain(COMPANY_ID);
  });
});
