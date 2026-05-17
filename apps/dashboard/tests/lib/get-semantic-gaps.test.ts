/**
 * /lake/metrics-proposed accessor tests (Wave 3 Task 5).
 *
 * Mocks ``pg`` so the accessor exercises without a live Postgres
 * dependency. Verifies:
 *
 *   * Honest empty when ``DATABASE_URL`` is unset.
 *   * SQL shape — propose-phase filter with ``nl_question + reason``
 *     payload shape; the second query pulls
 *     ``external_metric_imported`` rows for resolution detection.
 *   * Row mapping converts the raw ledger payload to the dashboard
 *     ``SemanticGapRow`` shape with the right ``status`` derivation.
 *   * ``{unresolved: true}`` excludes resolved rows.
 *   * Failure paths return ``[]`` (no fixture-fallback).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getSemanticGaps (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getSemanticGaps (Postgres path)", () => {
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

  it("issues the semantic_gap_proposed propose-phase SQL", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/metrics-proposed");
    await mod.getSemanticGaps(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(2);
    const gapsSql = String(queryMock.mock.calls[0][0]);
    // Propose-phase filter with the canonical shape.
    expect(gapsSql).toContain("kind = 'propose'");
    expect(gapsSql).toContain("'nl_question'");
    expect(gapsSql).toContain("'reason'");
    expect(gapsSql).toContain("'agent_id'");
    // Tenant scope.
    expect(gapsSql).toContain("company_id = $1");
    // Exclude denial traces (they tag their propose with mcp_tool).
    expect(gapsSql).toContain("'lake.semantic.gap'");

    // Resolution-side query targets ``external_metric_imported``.
    const resolvedSql = String(queryMock.mock.calls[1][0]);
    expect(resolvedSql).toContain("emit_external_metric_imported");
    expect(resolvedSql).toContain("company_id = $1");
  });

  it("returns [] when no rows match the query", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("maps the propose payload to a SemanticGapRow", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            entry_id: "00000000-0000-0000-0000-000000000001",
            ts: "2026-05-11T10:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "did our churn rate drop last week?",
              reason: "no_match",
              proposed_metric_name: "weekly_churn_rate",
              audit_trail_id: "00000000-0000-0000-0000-000000aud001",
            },
          },
        ],
        rowCount: 1,
      })
      .mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({
      id: "00000000-0000-0000-0000-000000000001",
      agentId: "agent:acme",
      nlQuestion: "did our churn rate drop last week?",
      reason: "no_match",
      proposedMetricName: "weekly_churn_rate",
      proposedAt: "2026-05-11T10:00:00.000Z",
      status: "unresolved",
    });
  });

  it("marks a gap as resolved when a matching external_metric_imported lands", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            entry_id: "id-1",
            ts: "2026-05-11T10:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "q?",
              reason: "no_match",
              proposed_metric_name: "weekly_churn_rate",
            },
          },
          {
            entry_id: "id-2",
            ts: "2026-05-11T11:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "q2?",
              reason: "low_confidence",
              proposed_metric_name: "active_user_count",
            },
          },
        ],
        rowCount: 2,
      })
      .mockResolvedValueOnce({
        rows: [{ metric_name: "weekly_churn_rate" }],
        rowCount: 1,
      });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows).toHaveLength(2);
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(byId["id-1"].status).toBe("resolved");
    expect(byId["id-2"].status).toBe("unresolved");
  });

  it("filters out resolved rows when opts.unresolved is true", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            entry_id: "id-1",
            ts: "2026-05-11T10:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "q?",
              reason: "no_match",
              proposed_metric_name: "weekly_churn_rate",
            },
          },
          {
            entry_id: "id-2",
            ts: "2026-05-11T11:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "q2?",
              reason: "ambiguous",
              proposed_metric_name: null,
            },
          },
        ],
        rowCount: 2,
      })
      .mockResolvedValueOnce({
        rows: [{ metric_name: "weekly_churn_rate" }],
        rowCount: 1,
      });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID, { unresolved: true });
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("id-2");
    expect(rows[0].status).toBe("unresolved");
  });

  it("treats a gap with proposed_metric_name=null as always unresolved", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            entry_id: "id-ambig",
            ts: "2026-05-11T10:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "ambig?",
              reason: "ambiguous",
              proposed_metric_name: null,
            },
          },
        ],
        rowCount: 1,
      })
      .mockResolvedValueOnce({
        rows: [{ metric_name: "anything" }],
        rowCount: 1,
      });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows[0].status).toBe("unresolved");
    expect(rows[0].proposedMetricName).toBeNull();
    expect(rows[0].reason).toBe("ambiguous");
  });

  it("does a case-insensitive match between metric names", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          {
            entry_id: "id-1",
            ts: "2026-05-11T10:00:00.000Z",
            payload: {
              agent_id: "agent:acme",
              nl_question: "q?",
              reason: "no_match",
              proposed_metric_name: "Weekly_Churn_Rate",
            },
          },
        ],
        rowCount: 1,
      })
      .mockResolvedValueOnce({
        // SQL already LOWER()s the column; simulate that here.
        rows: [{ metric_name: "weekly_churn_rate" }],
        rowCount: 1,
      });
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows[0].status).toBe("resolved");
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/metrics-proposed");
    const rows = await mod.getSemanticGaps(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});
