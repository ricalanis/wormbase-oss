/**
 * Route-handler tests for the dashboard's A3.5 write endpoints.
 *
 * Mocks `lib/server/worm-core-write` + `lib/tenant-cookies` and asserts
 * each handler:
 *   - resolves the tenant from cookies
 *   - validates body shape (returns 400 on missing fields)
 *   - calls the right worm-core-write function with the right args
 *   - maps worm-core errors to 502
 *
 * The integration test under
 * `tests/integration/test_dashboard_to_wormcore_write.py` covers the
 * live HTTP path end-to-end.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const TENANT_SLUG = "baseworm";
const PERSON_ID = "11111111-1111-1111-1111-111111111111";
const ACTOR_ID = "22222222-2222-2222-2222-222222222222";
const DOMAIN_ID = "33333333-3333-3333-3333-333333333333";
const RESOURCE_ID = "44444444-4444-4444-4444-444444444444";
const GRANT_ID = "55555555-5555-5555-5555-555555555555";

const proposePersonMock = vi.fn();
const confirmPersonMock = vi.fn();
const archivePersonMock = vi.fn();
const linkIdentityMock = vi.fn();
const unlinkIdentityMock = vi.fn();
const grantRoleMock = vi.fn();
const revokeRoleMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: TENANT_SLUG,
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/server/worm-core-write", () => ({
  proposePerson: proposePersonMock,
  confirmPerson: confirmPersonMock,
  archivePerson: archivePersonMock,
  linkIdentity: linkIdentityMock,
  unlinkIdentity: unlinkIdentityMock,
  grantRole: grantRoleMock,
  revokeRole: revokeRoleMock,
}));

// Mock the read-side ledger client used by GET routes to keep the import
// graph clean (the write routes don't touch it, but Next.js routes that
// merge GET + POST in the same file do).
vi.mock("../../lib/ledger-client", () => ({
  getPeople: vi.fn(),
  getPersonById: vi.fn(),
  getIdentitiesForPerson: vi.fn(),
  getRolesForPerson: vi.fn(),
}));

beforeEach(() => {
  proposePersonMock.mockReset();
  confirmPersonMock.mockReset();
  archivePersonMock.mockReset();
  linkIdentityMock.mockReset();
  unlinkIdentityMock.mockReset();
  grantRoleMock.mockReset();
  revokeRoleMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonRequest(body: unknown): Request {
  return new Request("http://x", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

describe("POST /api/people", () => {
  it("calls proposePerson and returns 201 with the result", async () => {
    proposePersonMock.mockResolvedValueOnce({
      person_id: PERSON_ID,
      entry_ids: ["a", "b", "c", "d"],
    });
    const { POST } = await import("../../app/api/people/route");
    const res = await POST(
      // NextRequest extends Request; the route doesn't read NextRequest-only
      // properties, so a plain Request is interchangeable here.
       
      jsonRequest({
        name: "Alice",
        platform: "slack",
        platform_user_id: "U-alice",
      }) as any,
    );
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.person_id).toBe(PERSON_ID);
    expect(proposePersonMock).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantSlug: TENANT_SLUG,
        name: "Alice",
        platform: "slack",
        platformUserId: "U-alice",
      }),
    );
  });

  it("returns 400 on missing fields", async () => {
    const { POST } = await import("../../app/api/people/route");
    const res = await POST(
       
      jsonRequest({ name: "Alice" }) as any,
    );
    expect(res.status).toBe(400);
    expect(proposePersonMock).not.toHaveBeenCalled();
  });

  it("maps worm-core errors to 502", async () => {
    proposePersonMock.mockRejectedValueOnce(new Error("boom"));
    const { POST } = await import("../../app/api/people/route");
    const res = await POST(
       
      jsonRequest({
        name: "Alice",
        platform: "slack",
        platform_user_id: "U-alice",
      }) as any,
    );
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.error).toBe("worm_core_error");
    expect(body.message).toContain("boom");
  });
});

describe("POST /api/people/[id]/confirm", () => {
  it("calls confirmPerson and returns 200", async () => {
    confirmPersonMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import("../../app/api/people/[id]/confirm/route");
    const res = await POST(
       
      jsonRequest({ confirmed_by: ACTOR_ID }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(confirmPersonMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({ tenantSlug: TENANT_SLUG, confirmedBy: ACTOR_ID }),
    );
  });

  it("returns 400 on missing confirmed_by", async () => {
    const { POST } = await import("../../app/api/people/[id]/confirm/route");
    const res = await POST(
       
      jsonRequest({}) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(400);
  });
});

describe("POST /api/people/[id]/archive", () => {
  it("calls archivePerson and returns 200", async () => {
    archivePersonMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import("../../app/api/people/[id]/archive/route");
    const res = await POST(
       
      jsonRequest({ archived_by: ACTOR_ID, reason: "left" }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(archivePersonMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({
        archivedBy: ACTOR_ID,
        reason: "left",
        tenantSlug: TENANT_SLUG,
      }),
    );
  });
});

describe("POST /api/people/[id]/identities", () => {
  it("calls linkIdentity and returns 200", async () => {
    linkIdentityMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import(
      "../../app/api/people/[id]/identities/route"
    );
    const res = await POST(
       
      jsonRequest({
        platform: "discord",
        platform_user_id: "bob#1234",
        linked_by: ACTOR_ID,
      }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(linkIdentityMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({
        platform: "discord",
        platformUserId: "bob#1234",
        linkedBy: ACTOR_ID,
      }),
    );
  });
});

describe("DELETE /api/people/[id]/identities/[platform]/[platform_user_id]", () => {
  it("calls unlinkIdentity and returns 200", async () => {
    unlinkIdentityMock.mockResolvedValueOnce({
      entry_ids: ["a", "b", "c", "d"],
    });
    const { DELETE } = await import(
      "../../app/api/people/[id]/identities/[platform]/[platform_user_id]/route"
    );
    const req = new Request("http://x", {
      method: "DELETE",
      body: JSON.stringify({ unlinked_by: ACTOR_ID }),
      headers: { "Content-Type": "application/json" },
    });
    const res = await DELETE(
       
      req as any,
      {
        params: Promise.resolve({
          id: PERSON_ID,
          platform: "discord",
          platform_user_id: "bob#1234",
        }),
      },
    );
    expect(res.status).toBe(200);
    expect(unlinkIdentityMock).toHaveBeenCalledWith(
      PERSON_ID,
      "discord",
      "bob#1234",
      expect.objectContaining({ unlinkedBy: ACTOR_ID }),
    );
  });
});

describe("POST /api/people/[id]/roles", () => {
  it("calls grantRole for tenancy facet", async () => {
    grantRoleMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import("../../app/api/people/[id]/roles/route");
    const res = await POST(
       
      jsonRequest({
        facet: "tenancy",
        role: "admin",
        granted_by: ACTOR_ID,
      }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(grantRoleMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({ facet: "tenancy", role: "admin" }),
    );
  });

  it("returns 400 when domain facet has no scope_id", async () => {
    const { POST } = await import("../../app/api/people/[id]/roles/route");
    const res = await POST(
       
      jsonRequest({
        facet: "domain",
        role: "owner",
        granted_by: ACTOR_ID,
      }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(400);
    expect(grantRoleMock).not.toHaveBeenCalled();
  });

  it("calls grantRole for resource facet", async () => {
    grantRoleMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import("../../app/api/people/[id]/roles/route");
    const res = await POST(
       
      jsonRequest({
        facet: "resource",
        role: "maintainer",
        scope_id: RESOURCE_ID,
        scope_type: "kpi",
        granted_by: ACTOR_ID,
      }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(grantRoleMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({
        facet: "resource",
        role: "maintainer",
        scopeId: RESOURCE_ID,
        scopeType: "kpi",
      }),
    );
  });

  it("calls grantRole for domain facet with scope_id", async () => {
    grantRoleMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import("../../app/api/people/[id]/roles/route");
    const res = await POST(
       
      jsonRequest({
        facet: "domain",
        role: "owner",
        scope_id: DOMAIN_ID,
        granted_by: ACTOR_ID,
      }) as any,
      { params: Promise.resolve({ id: PERSON_ID }) },
    );
    expect(res.status).toBe(200);
    expect(grantRoleMock).toHaveBeenCalledWith(
      PERSON_ID,
      expect.objectContaining({
        facet: "domain",
        role: "owner",
        scopeId: DOMAIN_ID,
      }),
    );
  });
});

describe("POST /api/people/[id]/roles/[grant_id]/revoke", () => {
  it("calls revokeRole and returns 200", async () => {
    revokeRoleMock.mockResolvedValueOnce({ entry_ids: ["a", "b", "c", "d"] });
    const { POST } = await import(
      "../../app/api/people/[id]/roles/[grant_id]/revoke/route"
    );
    const res = await POST(
       
      jsonRequest({ revoked_by: ACTOR_ID, role: "admin" }) as any,
      {
        params: Promise.resolve({ id: PERSON_ID, grant_id: GRANT_ID }),
      },
    );
    expect(res.status).toBe(200);
    expect(revokeRoleMock).toHaveBeenCalledWith(
      PERSON_ID,
      GRANT_ID,
      expect.objectContaining({ role: "admin", revokedBy: ACTOR_ID }),
    );
  });
});
