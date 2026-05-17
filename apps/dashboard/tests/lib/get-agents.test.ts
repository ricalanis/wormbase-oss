/**
 * Wave 3 Task 2 — getAgents + getAgentGrants accessors.
 *
 * Strategy: mock the `pg` module to drive controlled rows through
 * `getAgents` / `getAgentGrants`. Verifies the empty-state contract,
 * the activeGrantCount + budgetRemainingUsdSum derivations, and the
 * shape of the per-agent grant list.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getAgents (Wave 3 Task 2)", () => {
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

  it("returns [] when DATABASE_URL is not set", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/agents");
    const agents = await mod.getAgents(COMPANY_ID);
    expect(agents).toEqual([]);
  });

  it("returns [] when no agents are registered", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/agents");
    const agents = await mod.getAgents(COMPANY_ID);
    expect(agents).toEqual([]);
  });

  it("derives activeGrantCount and budgetRemainingUsdSum from the fold", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "agent-1",
          person_id: "agent-1",
          external_provider: "claude",
          display_name: "Claude Research Agent",
          registered_at: new Date("2026-05-10T10:00:00Z"),
          registered_by: "admin-1",
          status: "active",
          active_grant_count: "3",
          budget_remaining_usd_sum: "12.5000",
        },
        {
          id: "agent-2",
          person_id: "agent-2",
          external_provider: "kimi",
          display_name: "Kimi Researcher",
          registered_at: new Date("2026-05-10T11:00:00Z"),
          registered_by: "admin-1",
          status: "active",
          active_grant_count: "0",
          budget_remaining_usd_sum: null,
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/agents");
    const agents = await mod.getAgents(COMPANY_ID);
    expect(agents).toHaveLength(2);
    expect(agents[0].id).toBe("agent-1");
    expect(agents[0].externalProvider).toBe("claude");
    expect(agents[0].displayName).toBe("Claude Research Agent");
    expect(agents[0].activeGrantCount).toBe(3);
    expect(agents[0].budgetRemainingUsdSum).toBe("12.5000");
    expect(agents[1].activeGrantCount).toBe(0);
    expect(agents[1].budgetRemainingUsdSum).toBeNull();
  });

  it("scopes the SQL by company_id", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/agents");
    await mod.getAgents(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toContain(COMPANY_ID);
  });
});

describe("getAgentGrants (Wave 3 Task 2)", () => {
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

  it("returns [] when DATABASE_URL is not set", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/agents");
    const grants = await mod.getAgentGrants(COMPANY_ID, "agent-1");
    expect(grants).toEqual([]);
  });

  it("returns rows shaped as AgentGrant entries", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "grant-1",
          agent_id: "agent-1",
          grant_kind: "domain.read",
          grant_target: "domain-finance",
          status: "active",
          granted_by: "admin-1",
          granted_at: new Date("2026-05-10T10:00:00Z"),
          budget_remaining_usd: null,
        },
        {
          id: "grant-2",
          agent_id: "agent-1",
          grant_kind: "model.access",
          grant_target: "kimi",
          status: "active",
          granted_by: "admin-1",
          granted_at: new Date("2026-05-10T11:00:00Z"),
          budget_remaining_usd: "5.0000",
        },
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/agents");
    const grants = await mod.getAgentGrants(COMPANY_ID, "agent-1");
    expect(grants).toHaveLength(2);
    expect(grants[0].grantKind).toBe("domain.read");
    expect(grants[0].status).toBe("active");
    expect(grants[1].budgetRemainingUsd).toBe("5.0000");
  });

  it("filters grants by the requested agent_id", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/agents");
    await mod.getAgentGrants(COMPANY_ID, "agent-42");
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toContain("agent-42");
    expect(params).toContain(COMPANY_ID);
  });
});
