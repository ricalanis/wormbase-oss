/**
 * API contract tests for /api/people read-only endpoints (A3).
 *
 * Uses `vi.mock` on the ledger client + tenant-cookies modules so we can
 * exercise the route handlers directly without a live Postgres or a real
 * Next request scope.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90"; // baseworm
const PERSON_A = "11111111-1111-1111-1111-111111111111";

const fakePerson = {
  personId: PERSON_A,
  displayName: "Alice",
  email: "alice@x.co",
  position: null,
  status: "active" as const,
  tenancyRole: "admin" as const,
  identities: [
    { platform: "slack" as const, platformUserId: "U-slack" },
  ],
  domainGrantCount: 1,
  resourceGrantCount: 0,
  roles: ["admin"],
  ownedDomains: [],
  ownedResources: [],
  receipt: {
    hash: "abcdef012345",
    source: "people-projection",
    owner: PERSON_A,
    classification: "internal" as const,
  },
};

const getPeopleMock = vi.fn();
const getPersonByIdMock = vi.fn();
const getIdentitiesForPersonMock = vi.fn();
const getRolesForPersonMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/ledger-client", () => ({
  getPeople: getPeopleMock,
  getPersonById: getPersonByIdMock,
  getIdentitiesForPerson: getIdentitiesForPersonMock,
  getRolesForPerson: getRolesForPersonMock,
}));

beforeEach(() => {
  getPeopleMock.mockReset();
  getPersonByIdMock.mockReset();
  getIdentitiesForPersonMock.mockReset();
  getRolesForPersonMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/people", () => {
  it("returns 200 with {persons: [...]}", async () => {
    getPeopleMock.mockResolvedValueOnce([fakePerson]);
    const { GET } = await import("../../app/api/people/route");
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.persons)).toBe(true);
    expect(body.persons).toHaveLength(1);
    expect(body.persons[0].personId).toBe(PERSON_A);
    expect(getPeopleMock).toHaveBeenCalledWith(COMPANY_ID);
  });

  it("returns 200 with an empty list when no persons exist", async () => {
    getPeopleMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/people/route");
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.persons).toEqual([]);
  });
});

describe("POST /api/people (A3.5 — write through worm-core)", () => {
  // Write tests live in tests/api/people-write.test.ts. The route handler
  // imports the server-side worm-core-write helper; unit-testing GET here
  // doesn't exercise that path.
  it.skip("write tests live in people-write.test.ts", () => {});
});

describe("GET /api/people/[id]", () => {
  it("returns 200 with the person when found", async () => {
    getPersonByIdMock.mockResolvedValueOnce(fakePerson);
    const { GET } = await import("../../app/api/people/[id]/route");
    const res = await GET(new Request("http://x/api/people/x"), {
      params: Promise.resolve({ id: PERSON_A }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.person.personId).toBe(PERSON_A);
    expect(getPersonByIdMock).toHaveBeenCalledWith(COMPANY_ID, PERSON_A);
  });

  it("returns 404 when the person doesn't exist in this tenant", async () => {
    getPersonByIdMock.mockResolvedValueOnce(null);
    const { GET } = await import("../../app/api/people/[id]/route");
    const res = await GET(new Request("http://x/api/people/x"), {
      params: Promise.resolve({ id: PERSON_A }),
    });
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBe("not_found");
  });
});

describe("GET /api/people/[id]/identities", () => {
  it("returns 200 with the identities list", async () => {
    getIdentitiesForPersonMock.mockResolvedValueOnce([
      {
        platform: "slack",
        platformUserId: "U-slack",
        displayName: "Alice",
        addedAt: "2026-04-26T10:00:00.000Z",
      },
    ]);
    const { GET } = await import(
      "../../app/api/people/[id]/identities/route"
    );
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: PERSON_A }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.identities)).toBe(true);
    expect(body.identities).toHaveLength(1);
    expect(body.identities[0].platform).toBe("slack");
  });

  it("returns 200 with an empty list when there are no identities", async () => {
    getIdentitiesForPersonMock.mockResolvedValueOnce([]);
    const { GET } = await import(
      "../../app/api/people/[id]/identities/route"
    );
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: PERSON_A }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.identities).toEqual([]);
  });
});

describe("GET /api/people/[id]/roles", () => {
  it("returns 200 with the roles list (tenancy + domain + resource)", async () => {
    getRolesForPersonMock.mockResolvedValueOnce([
      {
        facet: "tenancy",
        role: "admin",
        scopeId: null,
        scopeType: null,
        grantedBy: "admin-uuid",
        grantedAt: "2026-04-26T10:00:00.000Z",
        revokedAt: null,
      },
      {
        facet: "domain",
        role: "owner",
        scopeId: "domain-uuid",
        scopeType: "domain",
        grantedBy: "admin-uuid",
        grantedAt: "2026-04-26T10:00:00.000Z",
        revokedAt: null,
      },
    ]);
    const { GET } = await import("../../app/api/people/[id]/roles/route");
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: PERSON_A }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.roles)).toBe(true);
    expect(body.roles).toHaveLength(2);
    expect(body.roles.map((r: { facet: string }) => r.facet).sort()).toEqual([
      "domain",
      "tenancy",
    ]);
  });
});
