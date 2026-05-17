/**
 * /api/people/[id]/audit — GET returns 200 with audit entries, 404 when
 * the Person does not exist in this tenant.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const PERSON_ID = "11111111-1111-1111-1111-111111111111";

const getPersonByIdMock = vi.fn();
const getAuditLogForPersonMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/ledger-client", () => ({
  getPersonById: getPersonByIdMock,
  getAuditLogForPerson: getAuditLogForPersonMock,
}));

beforeEach(() => {
  getPersonByIdMock.mockReset();
  getAuditLogForPersonMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const fakePerson = {
  personId: PERSON_ID,
  displayName: "Alice",
  email: "alice@x.co",
  position: null,
  status: "active" as const,
  tenancyRole: "admin" as const,
  identities: [],
  domainGrantCount: 0,
  resourceGrantCount: 0,
  roles: ["admin"],
  ownedDomains: [],
  ownedResources: [],
  receipt: {
    hash: "abcdef012345",
    source: "people-projection",
    owner: PERSON_ID,
    classification: "internal" as const,
  },
};

describe("GET /api/people/[id]/audit", () => {
  it("returns 200 with the audit entries for an existing Person", async () => {
    getPersonByIdMock.mockResolvedValueOnce(fakePerson);
    getAuditLogForPersonMock.mockResolvedValueOnce([
      {
        seq: "42",
        ts: "2026-04-26T10:00:00.000Z",
        kind: "execute",
        tool: "emit_role_assigned",
        hash: "deadbeef0000",
        args: { person_id: PERSON_ID, role: "admin" },
      },
    ]);
    const { GET } = await import("../../app/api/people/[id]/audit/route");
    const req = new Request("http://x/api/people/x/audit");
     
    const res = await GET(req as any, {
      params: Promise.resolve({ id: PERSON_ID }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.entries)).toBe(true);
    expect(body.entries).toHaveLength(1);
    expect(body.entries[0].seq).toBe("42");
    expect(getAuditLogForPersonMock).toHaveBeenCalledWith(
      COMPANY_ID,
      PERSON_ID,
      50,
    );
  });

  it("returns 404 when the Person doesn't exist in this tenant", async () => {
    getPersonByIdMock.mockResolvedValueOnce(null);
    const { GET } = await import("../../app/api/people/[id]/audit/route");
    const req = new Request("http://x/api/people/x/audit");
     
    const res = await GET(req as any, {
      params: Promise.resolve({ id: PERSON_ID }),
    });
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBe("not_found");
    expect(getAuditLogForPersonMock).not.toHaveBeenCalled();
  });

  it("respects the limit query parameter (capped at 200)", async () => {
    getPersonByIdMock.mockResolvedValueOnce(fakePerson);
    getAuditLogForPersonMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/people/[id]/audit/route");
    const req = new Request("http://x/api/people/x/audit?limit=10");
     
    const res = await GET(req as any, {
      params: Promise.resolve({ id: PERSON_ID }),
    });
    expect(res.status).toBe(200);
    expect(getAuditLogForPersonMock).toHaveBeenCalledWith(
      COMPANY_ID,
      PERSON_ID,
      10,
    );
  });

  it("caps an excessive limit to 200", async () => {
    getPersonByIdMock.mockResolvedValueOnce(fakePerson);
    getAuditLogForPersonMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/people/[id]/audit/route");
    const req = new Request("http://x/api/people/x/audit?limit=99999");
     
    const res = await GET(req as any, {
      params: Promise.resolve({ id: PERSON_ID }),
    });
    expect(res.status).toBe(200);
    expect(getAuditLogForPersonMock).toHaveBeenCalledWith(
      COMPANY_ID,
      PERSON_ID,
      200,
    );
  });
});
