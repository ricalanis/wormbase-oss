/**
 * API contract tests for /api/data-products route handlers (F3).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const PERSON_ID = "11111111-1111-1111-1111-111111111111";
const DP_ID = "22222222-2222-2222-2222-222222222222";

const fakeDp = {
  dataProductId: DP_ID,
  tenantId: COMPANY_ID,
  name: "Q3 Net Revenue",
  kind: "report",
  status: "generated",
  requestedByPersonId: PERSON_ID,
  domainId: null,
  generatedAt: "2026-04-25T10:00:00Z",
  contentHash: "abc",
  contentsUri: "file:///tmp/x.html",
  receipt: {
    hash: "abc",
    source: "ledger",
    owner: PERSON_ID,
    classification: "internal",
  },
};

const listDataProductsMock = vi.fn();
const getDataProductMock = vi.fn();
const listDataProductRunsMock = vi.fn();
const listDataProductConsumptionMock = vi.fn();
const proposeDataProductMock = vi.fn();
const regenerateDataProductMock = vi.fn();
const consumeDataProductMock = vi.fn();
const getCurrentPersonMock = vi.fn();
const getDomainAccessSetMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/server/data-products", () => ({
  listDataProducts: listDataProductsMock,
  getDataProduct: getDataProductMock,
  listDataProductRuns: listDataProductRunsMock,
  listDataProductConsumption: listDataProductConsumptionMock,
}));

vi.mock("../../lib/server/worm-core-write", () => ({
  proposeDataProduct: proposeDataProductMock,
  regenerateDataProduct: regenerateDataProductMock,
  consumeDataProduct: consumeDataProductMock,
}));

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
}));

vi.mock("../../lib/server/role-filter", () => ({
  getDomainAccessSet: getDomainAccessSetMock,
  filterByDomainAccess: <T,>(rows: T[]) => rows,
  memberHasNoAccess: () => false,
}));

beforeEach(() => {
  listDataProductsMock.mockReset();
  getDataProductMock.mockReset();
  listDataProductRunsMock.mockReset();
  listDataProductConsumptionMock.mockReset();
  proposeDataProductMock.mockReset();
  regenerateDataProductMock.mockReset();
  consumeDataProductMock.mockReset();
  getCurrentPersonMock.mockReset();
  getDomainAccessSetMock.mockReset();
  getCurrentPersonMock.mockResolvedValue({
    personId: PERSON_ID,
    name: "Alice",
    position: null,
    tenancyRole: "admin",
  });
  getDomainAccessSetMock.mockResolvedValue(new Set());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/data-products", () => {
  it("returns 200 with {dataProducts: [...]}", async () => {
    listDataProductsMock.mockResolvedValueOnce([fakeDp]);
    const { GET } = await import("../../app/api/data-products/route");
    const res = await GET(
      new Request("http://x/api/data-products?kind=report") as never,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.dataProducts).toHaveLength(1);
    expect(body.dataProducts[0].dataProductId).toBe(DP_ID);
  });

  it("passes kind/status filters through to the helper", async () => {
    listDataProductsMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/data-products/route");
    await GET(
      new Request(
        "http://x/api/data-products?kind=chart&status=generated",
      ) as never,
    );
    expect(listDataProductsMock).toHaveBeenCalledWith(
      COMPANY_ID,
      expect.objectContaining({ kind: "chart", status: "generated" }),
    );
  });
});

describe("GET /api/data-products/[id]", () => {
  it("returns 200 with dp + runs + consumption", async () => {
    getDataProductMock.mockResolvedValueOnce(fakeDp);
    listDataProductRunsMock.mockResolvedValueOnce([]);
    listDataProductConsumptionMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/data-products/[id]/route");
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: DP_ID }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.dataProduct.dataProductId).toBe(DP_ID);
    expect(body.runs).toEqual([]);
    expect(body.consumption).toEqual([]);
  });

  it("returns 404 when not found", async () => {
    getDataProductMock.mockResolvedValueOnce(null);
    listDataProductRunsMock.mockResolvedValueOnce([]);
    listDataProductConsumptionMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/data-products/[id]/route");
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: DP_ID }),
    });
    expect(res.status).toBe(404);
  });
});

describe("POST /api/data-products/[id]/regenerate", () => {
  it("forwards to worm-core regenerate and returns 200", async () => {
    regenerateDataProductMock.mockResolvedValueOnce({
      data_product_id: DP_ID,
      run_id: "r1",
      content_hash: "abc",
      entry_ids: ["e1", "e2", "e3", "e4"],
    });
    const { POST } = await import(
      "../../app/api/data-products/[id]/regenerate/route"
    );
    const res = await POST(
      new Request("http://x", {
        method: "POST",
        body: JSON.stringify({}),
      }),
      { params: Promise.resolve({ id: DP_ID }) },
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.run_id).toBe("r1");
    expect(regenerateDataProductMock).toHaveBeenCalledWith(
      DP_ID,
      expect.objectContaining({ tenantSlug: "baseworm" }),
    );
  });
});

describe("POST /api/data-products/[id]/consume", () => {
  it("records consumption with the current person", async () => {
    consumeDataProductMock.mockResolvedValueOnce({ entry_ids: ["e1"] });
    const { POST } = await import(
      "../../app/api/data-products/[id]/consume/route"
    );
    const res = await POST(
      new Request("http://x", {
        method: "POST",
        body: JSON.stringify({ surface: "dashboard" }),
      }),
      { params: Promise.resolve({ id: DP_ID }) },
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.recorded).toBe(true);
    expect(consumeDataProductMock).toHaveBeenCalledWith(
      DP_ID,
      expect.objectContaining({
        consumedByPersonId: PERSON_ID,
        surface: "dashboard",
      }),
    );
  });

  it("falls back to dashboard surface when none supplied", async () => {
    consumeDataProductMock.mockResolvedValueOnce({ entry_ids: [] });
    const { POST } = await import(
      "../../app/api/data-products/[id]/consume/route"
    );
    await POST(
      new Request("http://x", { method: "POST", body: "{}" }),
      { params: Promise.resolve({ id: DP_ID }) },
    );
    expect(consumeDataProductMock).toHaveBeenCalledWith(
      DP_ID,
      expect.objectContaining({ surface: "dashboard" }),
    );
  });
});
