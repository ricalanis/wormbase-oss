/**
 * importDbtManifest server-action tests (Wave 3.2 Hole #2).
 *
 * Pin:
 *   * Admin role check rejects member callers (defense in depth against
 *     direct action POSTs that bypass the page-level gate).
 *   * Stub fallback fires honestly when no WORM_CORE_API_URL is set.
 *   * Happy path: forwards to worm-core, threads the bearer token +
 *     tenant slug, and returns `{ok: true, sourceId}`.
 *   * 404 from worm-core surfaces an "endpoint v1.1" error.
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
  manifestUri: "https://artifacts.example.com/manifest.json",
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

describe("importDbtManifest — admin role gate", () => {
  it("rejects when no Person is authenticated", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(null);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
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
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("admin role required");
  });

  it("permits a member who holds a fallback admin grant in the grants probe", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(MEMBER_PERSON);
    getRolesForPersonMock.mockResolvedValueOnce([
      {
        facet: "tenancy",
        role: "admin",
        revokedAt: null,
        grantedAt: "2026-04-01T00:00:00.000Z",
      },
    ]);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("import_dbt_catalog endpoint v1.1");
  });
});

describe("importDbtManifest — argument sanity", () => {
  it("rejects an empty manifest URI", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest({ ...BASE_FORM, manifestUri: "  " });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing manifest_uri");
  });

  it("rejects an empty domain id", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest({ ...BASE_FORM, domainId: "" });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("missing domain_id");
  });
});

describe("importDbtManifest — stub fallback", () => {
  it("returns honest stub error when WORM_CORE_API_URL is unset", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("import_dbt_catalog endpoint v1.1");
    expect(result.error).toContain("no WORM_CORE_API_URL configured");
  });

  it("returns honest error when token is missing", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);
    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("WORMBASE_LEDGER_API_TOKEN");
  });
});

describe("importDbtManifest — happy path", () => {
  it("forwards to worm-core and returns {ok, sourceId}", async () => {
    process.env.WORM_CORE_API_URL = "http://worm-core:8910";
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    getCurrentPersonMock.mockResolvedValueOnce(ADMIN_PERSON);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ source_id: "src-dbt-1" }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);

    expect(result).toEqual({ ok: true, sourceId: "src-dbt-1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe(
      "http://worm-core:8910/api/v1/write_actions/import_dbt_catalog",
    );
    expect(init.method).toBe("POST");
     
    const headers = init.headers as any;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    const body = JSON.parse(init.body as string);
    expect(body.manifest_uri).toBe(
      "https://artifacts.example.com/manifest.json",
    );
    expect(body.domain_id).toBe("11111111-1111-1111-1111-111111111111");
    expect(body.imported_by).toBe("p-admin-1");
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

    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("import_dbt_catalog endpoint v1.1");
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

    const { importDbtManifest } = await import(
      "../../app/onboarding/connect/dbt-manifest/actions"
    );
    const result = await importDbtManifest(BASE_FORM);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
    expect(result.error).toContain("boom");
  });
});
