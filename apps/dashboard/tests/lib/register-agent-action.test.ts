/**
 * registerAgent server-action tests (Wave 3.2 Hole #1).
 *
 * Pin:
 *   * Admin role check rejects member/observer callers (defense in depth
 *     against direct action POSTs that bypass the page-level gate).
 *   * Stub fallback fires honestly when no WORM_CORE_API_URL is set,
 *     matching the `/lake/metrics-proposed/actions.ts` shape.
 *   * Happy path: forwards to worm-core, threads the bearer token +
 *     tenant slug, and returns `{ok: true, agentId}`.
 *   * 404 from worm-core surfaces a "endpoint v1.1" error so the admin
 *     sees the migration state inline.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

const getCurrentPersonMock = vi.fn();
const getCurrentCompanyIdMock = vi.fn(async () => COMPANY_ID);
const getTenantFromCookiesMock = vi.fn(async () => ({
  slug: "baseworm",
  companyId: COMPANY_ID,
}));
const getRolesForPersonMock = vi.fn();

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
}));

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: getCurrentCompanyIdMock,
  getTenantFromCookies: getTenantFromCookiesMock,
}));

vi.mock("../../lib/ledger-client", () => ({
  getRolesForPerson: getRolesForPersonMock,
}));

const ADMIN_PERSON = {
  personId: "p-admin-1",
  name: "Carol",
  position: "CFO",
  tenancyRole: "admin" as const,
};

const MEMBER_PERSON = {
  personId: "p-member-1",
  name: "Bob",
  position: "DE",
  tenancyRole: "member" as const,
};

const BASE_FORM = {
  externalProvider: "claude" as const,
  displayName: "revenue-bot",
  domainReadIds: ["d-1"],
  modelAccessBudgetUsd: "25.00",
};

const ORIG_ENV = { ...process.env };

beforeEach(() => {
  getCurrentPersonMock.mockReset();
  getRolesForPersonMock.mockReset();
  getCurrentCompanyIdMock.mockClear();
  getTenantFromCookiesMock.mockClear();
  vi.unstubAllGlobals();
  // Reset env between tests so stub-fallback assertions are independent.
  process.env = { ...ORIG_ENV };
  delete process.env.WORM_CORE_API_URL;
  delete process.env.WORMBASE_LEDGER_API_BASE;
  delete process.env.WORMBASE_LEDGER_API_TOKEN;
});

afterEach(() => {
  vi.restoreAllMocks();
  process.env = { ...ORIG_ENV };
});

describe("registerAgent — admin role gate", () => {
  it("rejects when no Person is authenticated", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(null);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("no authenticated person");
  });

  it("rejects when caller is a member with no admin grant", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(MEMBER_PERSON);
    getRolesForPersonMock.mockResolvedValueOnce([
      {
        facet: "tenancy",
        role: "member",
        revokedAt: null,
        grantedAt: "2026-04-01T00:00:00.000Z",
      },
    ]);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("admin role required");
  });

  it("permits a member who holds a fallback admin grant in the grants probe", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(MEMBER_PERSON);
    getRolesForPersonMock.mockResolvedValueOnce([
      // Roster projection said "member" but grants say admin (projection lag).
      {
        facet: "tenancy",
        role: "admin",
        revokedAt: null,
        grantedAt: "2026-04-01T00:00:00.000Z",
      },
    ]);
    // No worm-core endpoint configured → stub-fallback error (not 403).
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("register_agent endpoint v1.1");
  });
});

describe("registerAgent — argument sanity", () => {
  it("rejects an invalid external_provider", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent({
      ...BASE_FORM,
       
      externalProvider: "not-a-real-provider" as any,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("invalid external_provider");
  });

  it("rejects an empty display_name", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent({ ...BASE_FORM, displayName: "  " });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing display_name");
  });

  it("rejects display_name > 80 chars", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent({
      ...BASE_FORM,
      displayName: "x".repeat(81),
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("80");
  });
});

describe("registerAgent — stub fallback", () => {
  it("returns honest stub error when WORM_CORE_API_URL is unset", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("register_agent endpoint v1.1");
    expect(result.error).toContain("no WORM_CORE_API_URL configured");
  });

  it("returns honest error when token is missing", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("WORMBASE_LEDGER_API_TOKEN");
  });
});

describe("registerAgent — happy path", () => {
  it("forwards to worm-core and returns {ok, agentId}", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ agent_id: "agent-xyz" }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);

    expect(result).toEqual({ ok: true, agentId: "agent-xyz" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe(
      "http://worm-core:8910/api/v1/write_actions/register_agent",
    );
    expect(init.method).toBe("POST");
     
    const headers = init.headers as any;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    const body = JSON.parse(init.body as string);
    expect(body.external_provider).toBe("claude");
    expect(body.display_name).toBe("revenue-bot");
    expect(body.domain_read_ids).toEqual(["d-1"]);
    expect(body.model_access_budget_usd).toBe("25.00");
    expect(body.registered_by).toBe("p-admin-1");
    expect(body.company_id).toBe(COMPANY_ID);
  });

  it("surfaces 404 as an endpoint-v1.1 error", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({}),
      text: async () => "not found",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("register_agent endpoint v1.1");
    expect(result.error).toContain("worm-core has not exposed");
  });

  it("surfaces a non-2xx worm-core error inline", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({}),
      text: async () => "boom",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { registerAgent } = await import(
      "../../app/(app)/people/agents/new/actions"
    );
    const result = await registerAgent(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
    expect(result.error).toContain("boom");
  });
});
