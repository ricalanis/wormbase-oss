/**
 * Route-handler tests for the dashboard's /api/v1/reactivities/* wrappers
 * (W5.A5).
 *
 * Mocks ``lib/server/reactivities`` + ``lib/tenant-cookies`` +
 * ``lib/server/identity`` and asserts each handler:
 *   - resolves the tenant from cookies
 *   - validates body shape (returns 400 on missing fields)
 *   - threads the current admin Person id through where required
 *   - returns 401 when no admin Person can be resolved (mutating routes)
 *   - maps worm-core errors to 502
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const TENANT_SLUG = "baseworm";
const ADMIN_ID = "11111111-1111-1111-1111-111111111111";
const REACTIVITY_ID = "statement_to_owner";

const listReactivitiesMock = vi.fn();
const proposeReactivityMock = vi.fn();
const confirmReactivityMock = vi.fn();
const disableReactivityMock = vi.fn();
const listReactivityFiresMock = vi.fn();
const getCurrentPersonMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: TENANT_SLUG,
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/server/reactivities", () => ({
  listReactivities: listReactivitiesMock,
  proposeReactivity: proposeReactivityMock,
  confirmReactivity: confirmReactivityMock,
  disableReactivity: disableReactivityMock,
  listReactivityFires: listReactivityFiresMock,
}));

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
  getCurrentInstall: vi.fn(),
}));

beforeEach(() => {
  listReactivitiesMock.mockReset();
  proposeReactivityMock.mockReset();
  confirmReactivityMock.mockReset();
  disableReactivityMock.mockReset();
  listReactivityFiresMock.mockReset();
  getCurrentPersonMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonRequest(body: unknown, url = "http://x"): Request {
  return new Request(url, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

describe("GET /api/v1/reactivities/list", () => {
  it("returns the list payload from worm-core", async () => {
    listReactivitiesMock.mockResolvedValueOnce({
      reactivities: [{ id: "rx_a", name: "x" }],
    });
    const { GET } = await import("../../app/api/v1/reactivities/list/route");
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ reactivities: [{ id: "rx_a", name: "x" }] });
  });

  it("maps worm-core errors to 502 with an honest empty list", async () => {
    listReactivitiesMock.mockRejectedValueOnce(new Error("boom"));
    const { GET } = await import("../../app/api/v1/reactivities/list/route");
    const res = await GET();
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.reactivities).toEqual([]);
    expect(body.message).toContain("boom");
  });
});

describe("POST /api/v1/reactivities/propose", () => {
  it("rejects missing description with 400", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    const { POST } = await import(
      "../../app/api/v1/reactivities/propose/route"
    );
     
    const res = await POST(jsonRequest({}) as any);
    expect(res.status).toBe(400);
  });

  it("threads the current admin Person id as proposedBy", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    proposeReactivityMock.mockResolvedValueOnce({
      sketch: { id: "x", confidence: 0.8 },
      persisted: true,
    });
    const { POST } = await import(
      "../../app/api/v1/reactivities/propose/route"
    );
    const res = await POST(
       
      jsonRequest({ description: "ping me on revenue" }) as any,
    );
    expect(res.status).toBe(201);
    expect(proposeReactivityMock).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantSlug: TENANT_SLUG,
        description: "ping me on revenue",
        proposedBy: ADMIN_ID,
        preview: false,
      }),
    );
  });

  it("forwards ?preview=1 and returns 200 (no persistence)", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    proposeReactivityMock.mockResolvedValueOnce({
      sketch: { id: "x", confidence: 0.8 },
      persisted: false,
    });
    const { POST } = await import(
      "../../app/api/v1/reactivities/propose/route"
    );
    const res = await POST(
      jsonRequest(
        { description: "ping me" },
        "http://x/api/v1/reactivities/propose?preview=1",
         
      ) as any,
    );
    expect(res.status).toBe(200);
    expect(proposeReactivityMock).toHaveBeenCalledWith(
      expect.objectContaining({ preview: true }),
    );
  });
});

describe("POST /api/v1/reactivities/[id]/confirm", () => {
  it("returns 401 when no admin Person can be resolved", async () => {
    getCurrentPersonMock.mockResolvedValueOnce(null);
    const { POST } = await import(
      "../../app/api/v1/reactivities/[id]/confirm/route"
    );
    const res = await POST(
       
      jsonRequest({}) as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(401);
    expect(confirmReactivityMock).not.toHaveBeenCalled();
  });

  it("calls confirmReactivity with the admin Person id", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    confirmReactivityMock.mockResolvedValueOnce({ ok: true });
    const { POST } = await import(
      "../../app/api/v1/reactivities/[id]/confirm/route"
    );
    const res = await POST(
       
      jsonRequest({}) as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(200);
    expect(confirmReactivityMock).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantSlug: TENANT_SLUG,
        reactivityId: REACTIVITY_ID,
        confirmedBy: ADMIN_ID,
      }),
    );
  });
});

describe("POST /api/v1/reactivities/[id]/disable", () => {
  it("rejects missing reason with 400", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    const { POST } = await import(
      "../../app/api/v1/reactivities/[id]/disable/route"
    );
    const res = await POST(
       
      jsonRequest({}) as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(400);
  });

  it("calls disableReactivity with reason + admin Person id", async () => {
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: ADMIN_ID,
      name: "A",
      position: null,
      tenancyRole: "admin",
    });
    disableReactivityMock.mockResolvedValueOnce({ ok: true });
    const { POST } = await import(
      "../../app/api/v1/reactivities/[id]/disable/route"
    );
    const res = await POST(
       
      jsonRequest({ reason: "noisy" }) as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(200);
    expect(disableReactivityMock).toHaveBeenCalledWith(
      expect.objectContaining({
        reactivityId: REACTIVITY_ID,
        disabledBy: ADMIN_ID,
        reason: "noisy",
      }),
    );
  });
});

describe("GET /api/v1/reactivities/[id]/fires", () => {
  it("returns the fires payload from worm-core", async () => {
    listReactivityFiresMock.mockResolvedValueOnce({ fires: [{ seq: 1 }] });
    const { GET } = await import(
      "../../app/api/v1/reactivities/[id]/fires/route"
    );
    const res = await GET(
      new Request(
        "http://x/api/v1/reactivities/r/fires?limit=10",
         
      ) as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(200);
    expect(listReactivityFiresMock).toHaveBeenCalledWith(
      expect.objectContaining({ reactivityId: REACTIVITY_ID, limit: 10 }),
    );
  });

  it("maps worm-core errors to 502 with an honest empty fires array", async () => {
    listReactivityFiresMock.mockRejectedValueOnce(new Error("boom"));
    const { GET } = await import(
      "../../app/api/v1/reactivities/[id]/fires/route"
    );
    const res = await GET(
       
      new Request("http://x/api/v1/reactivities/r/fires") as any,
      { params: Promise.resolve({ id: REACTIVITY_ID }) },
    );
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.fires).toEqual([]);
  });
});
