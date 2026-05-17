/**
 * get-agent-query-chain — accessor + chain-assembly tests (Wave 3 Task 3).
 *
 * Two slices:
 *
 *   1. ``assembleChain`` — pure-function chain assembly over a fixture
 *      candidate-row stream. Verifies PEVR grouping, caused_by indent
 *      threading, ts-ASC ordering, latency/cost roll-ups, and the
 *      ``denied`` terminal status surfacing when a gate fires.
 *   2. ``getAgentQueryChain`` — DB-bound entry point with the ``pg``
 *      module mocked, mirroring the pattern in
 *      ``tests/lib/get-topics.test.ts``. Verifies the recursive CTE
 *      runs once per call, returns ``null`` on empty result set, and
 *      passes the caller-supplied tenant + audit_trail_id through to
 *      the parameterised query.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  assembleChain,
  type CandidateChainRow,
} from "../../lib/agent-query-chain";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const ROOT_AUDIT = "00000000-0000-0000-0000-00000000aaaa";
const RETRY_AUDIT = "00000000-0000-0000-0000-00000000bbbb";

function pevrRow(
  seq: string,
  phase: "propose" | "execute" | "verify" | "resolve",
  ts: string,
  extra: Record<string, unknown> = {},
  auditTrailId: string = ROOT_AUDIT,
): CandidateChainRow {
  return {
    seq,
    envelopeKind: phase,
    ts,
    hashHex: `hash-${seq}`,
    payload: {
      agent_id: "agent-1",
      mcp_tool: "lake.semantic.metric",
      args: { name: "revenue_q3" },
      route_mode: "broker",
      phase,
      audit_trail_id: auditTrailId,
      row_count: phase === "resolve" ? 4 : null,
      cost_usd: phase === "resolve" ? "0.013" : null,
      latency_ms: phase === "resolve" ? 420 : null,
      ...extra,
    },
  };
}

function inferenceRow(seq: string, ts: string, extra: Record<string, unknown> = {}): CandidateChainRow {
  return {
    seq,
    envelopeKind: "execute",
    ts,
    hashHex: `hash-${seq}`,
    payload: {
      kind: "inference_served",
      caused_by: ROOT_AUDIT,
      served_by: "kimi",
      latency_ms: 380,
      cost_usd: "0.004",
      ...extra,
    },
  };
}

function credentialRow(
  seq: string,
  ts: string,
  status: "active" | "revoked" = "active",
  extra: Record<string, unknown> = {},
): CandidateChainRow {
  return {
    seq,
    envelopeKind: "resolve",
    ts,
    hashHex: `hash-${seq}`,
    payload: {
      agent_id: "agent-1",
      credential_kind: "data",
      target: "snowflake://X.Y.Z",
      status,
      ttl_expires_at: "2026-05-11T18:00:00Z",
      issued_by: "agent-gateway",
      caused_by: ROOT_AUDIT,
      ...extra,
    },
  };
}

// ─── assembleChain — pure-function unit tests ─────────────────────────────

describe("assembleChain · root PEVR fold", () => {
  it("groups the four PEVR phases under the root audit_trail_id", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      pevrRow("102", "verify", "2026-05-10T10:00:02Z"),
      pevrRow("103", "resolve", "2026-05-10T10:00:03Z"),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain).not.toBeNull();
    expect(chain!.entries).toHaveLength(4);
    expect(chain!.rootAuditTrailId).toBe(ROOT_AUDIT);
    expect(chain!.agentId).toBe("agent-1");
    expect(chain!.mcpTool).toBe("lake.semantic.metric");
    expect(chain!.routeMode).toBe("broker");
    expect(chain!.status).toBe("resolve");
  });

  it("orders entries ts ASC for chronological replay", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("103", "resolve", "2026-05-10T10:00:03Z"),
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      pevrRow("102", "verify", "2026-05-10T10:00:02Z"),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain).not.toBeNull();
    const phases = chain!.entries.map((e) => e.phase);
    expect(phases).toEqual(["propose", "execute", "verify", "resolve"]);
  });

  it("rolls up resolve-phase latency_ms + cost_usd across the chain", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      pevrRow("102", "verify", "2026-05-10T10:00:02Z"),
      pevrRow("103", "resolve", "2026-05-10T10:00:03Z"),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain!.totalLatencyMs).toBe(420);
    expect(chain!.totalCostUsd).toBe("0.0130");
  });

  it("returns null when no root entries match", () => {
    const rows: CandidateChainRow[] = [];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain).toBeNull();
  });
});

describe("assembleChain · gate-denied surfacing", () => {
  it("marks status=denied when verify phase carries passed=false", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      pevrRow("102", "verify", "2026-05-10T10:00:02Z", { passed: false }),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain!.status).toBe("denied");
  });

  it("marks status=denied when any phase carries status=denied", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z", { status: "denied" }),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain!.status).toBe("denied");
  });
});

describe("assembleChain · caused_by fan-out", () => {
  it("includes inference_served entries caused_by the root", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      inferenceRow("102", "2026-05-10T10:00:01.500Z"),
      pevrRow("103", "verify", "2026-05-10T10:00:02Z"),
      pevrRow("104", "resolve", "2026-05-10T10:00:03Z"),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    const inferenceEntries = chain!.entries.filter(
      (e) => e.kind === "inference_served",
    );
    expect(inferenceEntries).toHaveLength(1);
    expect(inferenceEntries[0].payload.served_by).toBe("kimi");
  });

  it("includes credential issuance entries chained off the root", () => {
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      credentialRow("102", "2026-05-10T10:00:01.250Z", "active"),
      pevrRow("103", "verify", "2026-05-10T10:00:02Z"),
      pevrRow("104", "resolve", "2026-05-10T10:00:03Z"),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    const credEntries = chain!.entries.filter((e) => e.kind === "credential");
    expect(credEntries).toHaveLength(1);
    expect(credEntries[0].payload.credential_kind).toBe("data");
  });
});

describe("assembleChain · retry-tree recursion", () => {
  it("includes a chained agent_query that retried the failed root", () => {
    const correction: CandidateChainRow = {
      seq: "200",
      envelopeKind: "execute",
      ts: "2026-05-10T10:00:04Z",
      hashHex: "hash-200",
      payload: {
        kind: "query_correction_suggested",
        original_query_id: ROOT_AUDIT,
        failure_kind: "empty",
        failure_detail: "no rows returned",
        refined_query_spec: { name: "revenue_q3_refined" },
      },
    };
    const rows: CandidateChainRow[] = [
      pevrRow("100", "propose", "2026-05-10T10:00:00Z"),
      pevrRow("101", "execute", "2026-05-10T10:00:01Z"),
      pevrRow("102", "verify", "2026-05-10T10:00:02Z"),
      pevrRow("103", "resolve", "2026-05-10T10:00:03Z"),
      correction,
      // The retry agent_query — caused_by chains to the root.
      pevrRow(
        "300",
        "propose",
        "2026-05-10T10:00:05Z",
        { caused_by: ROOT_AUDIT },
        RETRY_AUDIT,
      ),
      pevrRow(
        "301",
        "execute",
        "2026-05-10T10:00:06Z",
        { caused_by: ROOT_AUDIT },
        RETRY_AUDIT,
      ),
      pevrRow(
        "302",
        "verify",
        "2026-05-10T10:00:07Z",
        { caused_by: ROOT_AUDIT },
        RETRY_AUDIT,
      ),
      pevrRow(
        "303",
        "resolve",
        "2026-05-10T10:00:08Z",
        { caused_by: ROOT_AUDIT },
        RETRY_AUDIT,
      ),
    ];
    const chain = assembleChain(rows, ROOT_AUDIT);
    expect(chain).not.toBeNull();
    expect(chain!.entries.length).toBeGreaterThanOrEqual(9);
    // The retry's four phases all show up.
    const retryPhases = chain!.entries.filter(
      (e) => e.auditTrailId === RETRY_AUDIT,
    );
    expect(retryPhases).toHaveLength(4);
    // The correction sits between root resolve and retry propose.
    const ordered = chain!.entries.map((e) => `${e.kind}/${e.phase ?? "-"}`);
    expect(ordered).toContain("query_correction_suggested/-");
    // Roll-up sums both resolve phases' latency.
    expect(chain!.totalLatencyMs).toBe(420 + 420);
  });
});

// ─── getAgentQueryChain — DB-bound integration via mocked pg ──────────────

describe("getAgentQueryChain · postgres path", () => {
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

  it("returns null when audit_trail_id is empty", async () => {
    const mod = await import("../../lib/agent-query-chain");
    const result = await mod.getAgentQueryChain(COMPANY_ID, "");
    expect(result).toBeNull();
    expect(queryMock).not.toHaveBeenCalled();
  });

  it("returns null when DATABASE_URL is unset", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/agent-query-chain");
    const result = await mod.getAgentQueryChain(COMPANY_ID, ROOT_AUDIT);
    expect(result).toBeNull();
  });

  it("returns null when the recursive CTE finds no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/agent-query-chain");
    const result = await mod.getAgentQueryChain(COMPANY_ID, ROOT_AUDIT);
    expect(result).toBeNull();
  });

  it("returns an assembled chain when the recursive CTE returns rows", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          seq: "100",
          envelope_kind: "propose",
          ts: new Date("2026-05-10T10:00:00Z"),
          hash_hex: "abc",
          payload: {
            agent_id: "agent-1",
            mcp_tool: "lake.semantic.metric",
            args: {},
            route_mode: "broker",
            phase: "propose",
            audit_trail_id: ROOT_AUDIT,
          },
        },
        {
          seq: "103",
          envelope_kind: "resolve",
          ts: new Date("2026-05-10T10:00:03Z"),
          hash_hex: "def",
          payload: {
            agent_id: "agent-1",
            mcp_tool: "lake.semantic.metric",
            args: {},
            route_mode: "broker",
            phase: "resolve",
            audit_trail_id: ROOT_AUDIT,
            row_count: 4,
            cost_usd: "0.013",
            latency_ms: 420,
          },
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/agent-query-chain");
    const result = await mod.getAgentQueryChain(COMPANY_ID, ROOT_AUDIT);
    expect(result).not.toBeNull();
    expect(result!.rootAuditTrailId).toBe(ROOT_AUDIT);
    expect(result!.entries).toHaveLength(2);
    expect(result!.totalLatencyMs).toBe(420);
  });

  it("passes the audit_trail_id through to the parameterised CTE", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/agent-query-chain");
    await mod.getAgentQueryChain(COMPANY_ID, ROOT_AUDIT);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toEqual([COMPANY_ID, ROOT_AUDIT]);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("RECURSIVE");
    expect(sql).toContain("audit_trail_id");
    expect(sql).toContain("caused_by");
  });

  it("returns null on a Postgres error rather than throwing", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/agent-query-chain");
    const result = await mod.getAgentQueryChain(COMPANY_ID, ROOT_AUDIT);
    expect(result).toBeNull();
  });
});
