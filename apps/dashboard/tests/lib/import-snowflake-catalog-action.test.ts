/**
 * importSnowflakeCatalog server-action tests (Wave 3.2 Hole #2).
 *
 * Pin:
 *   * Admin role check rejects member callers.
 *   * Stub fallback fires honestly when no WORM_CORE_API_URL is set.
 *   * Happy path: forwards to worm-core with the connection shape +
 *     domain id; returns `{ok: true, sourceId}`.
 *   * 404 from worm-core surfaces an "endpoint v1.1" error.
 *   * Required fields are enforced (account/user/database/schema/warehouse).
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
  account: "abc12345.us-east-1.aws",
  user: "WORMBASE_INGEST",
  database: "ANALYTICS",
  schema: "MARTS",
  warehouse: "WORMBASE_WH",
  role: "WORMBASE_RO",
  domainId: "11111111-1111-1111-1111-111111111111",
};

const ORIG_ENV = { ...process.env };

beforeEach(() => {
  getCurrentPersonMock.mockReset();
  getRolesForPersonMock.mockReset();
  getCurrentCompanyIdMock.mockClear();
  getTenantFromCookiesMock.mockClear();
  vi.unstubAllGlobals();
  process.env = { ...ORIG_ENV };
  delete process.env.WORM_CORE_API_URL;
  delete process.env.WORMBASE_LEDGER_API_BASE;
  delete process.env.WORMBASE_LEDGER_API_TOKEN;
});

afterEach(() => {
  vi.restoreAllMocks();
  process.env = { ...ORIG_ENV };
});

describe("importSnowflakeCatalog — admin role gate", () => {
  it("rejects when no Person is authenticated", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(null);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
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
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("admin role required");
  });
});

describe("importSnowflakeCatalog — argument sanity", () => {
  it("rejects when account is missing", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({ ...BASE_FORM, account: "" });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing account");
  });

  it("rejects when user is missing", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({ ...BASE_FORM, user: "" });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing user");
  });

  it("rejects when database is missing", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({
      ...BASE_FORM,
      database: "",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing database");
  });

  it("rejects when warehouse is missing", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({
      ...BASE_FORM,
      warehouse: "",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing warehouse");
  });

  it("rejects when domain_id is missing", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({ ...BASE_FORM, domainId: "" });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing domain_id");
  });
});

describe("importSnowflakeCatalog — stub fallback", () => {
  it("returns honest stub error when WORM_CORE_API_URL is unset", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("import_snowflake_catalog endpoint v1.1");
    expect(result.error).toContain("no WORM_CORE_API_URL configured");
  });

  it("returns honest error when token is missing", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("WORMBASE_LEDGER_API_TOKEN");
  });
});

describe("importSnowflakeCatalog — happy path", () => {
  it("forwards to worm-core and returns {ok, sourceId}", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ source_id: "src-snow-1" }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);

    expect(result).toEqual({ ok: true, sourceId: "src-snow-1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe(
      "http://worm-core:8910/api/v1/write_actions/import_snowflake_catalog",
    );
    expect(init.method).toBe("POST");
     
    const headers = init.headers as any;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    const body = JSON.parse(init.body as string);
    expect(body.account).toBe("abc12345.us-east-1.aws");
    expect(body.user).toBe("WORMBASE_INGEST");
    expect(body.database).toBe("ANALYTICS");
    expect(body.schema).toBe("MARTS");
    expect(body.warehouse).toBe("WORMBASE_WH");
    expect(body.role).toBe("WORMBASE_RO");
    expect(body.domain_id).toBe("11111111-1111-1111-1111-111111111111");
    expect(body.imported_by).toBe("p-admin-1");
    expect(body.company_id).toBe(COMPANY_ID);
  });

  it("nulls role when blank/undefined", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ source_id: "src-snow-2" }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog({
      ...BASE_FORM,
      role: undefined,
    });
    expect(result.ok).toBe(true);
    const body = JSON.parse(
      (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1]
        .body as string,
    );
    expect(body.role).toBeNull();
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

    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("import_snowflake_catalog endpoint v1.1");
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

    const { importSnowflakeCatalog } = await import(
      "../../app/onboarding/connect/snowflake-catalog/actions"
    );
    const result = await importSnowflakeCatalog(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
    expect(result.error).toContain("boom");
  });
});
