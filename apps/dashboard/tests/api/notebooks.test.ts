/**
 * API contract tests for /api/notebooks route handlers (F4).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";
const PERSON_ID = "11111111-1111-1111-1111-111111111111";
const NB_ID = "22222222-2222-2222-2222-222222222222";

const fakeNb = {
  notebookId: NB_ID,
  tenantId: COMPANY_ID,
  name: "CFO autoresearch",
  kernel: "python_local",
  status: "published",
  ownerPersonId: PERSON_ID,
  domainId: null,
  latestRunId: "r1",
  latestPublishedRunId: "r1",
  version: "1",
  cells: [],
  receipt: {
    hash: "abc",
    source: "ledger",
    owner: PERSON_ID,
    classification: "internal",
  },
};

const listNotebooksMock = vi.fn();
const getNotebookMock = vi.fn();
const listNotebookRunsMock = vi.fn();
const proposeNotebookMock = vi.fn();
const runNotebookMock = vi.fn();
const publishNotebookMock = vi.fn();
const getCurrentPersonMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/server/notebooks", () => ({
  listNotebooks: listNotebooksMock,
  getNotebook: getNotebookMock,
  listNotebookRuns: listNotebookRunsMock,
}));

vi.mock("../../lib/server/worm-core-write", () => ({
  proposeNotebook: proposeNotebookMock,
  runNotebook: runNotebookMock,
  publishNotebook: publishNotebookMock,
}));

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
}));

vi.mock("../../lib/server/role-filter", () => ({
  getDomainAccessSet: vi.fn(async () => new Set()),
  filterByDomainAccess: <T,>(rows: T[]) => rows,
  memberHasNoAccess: () => false,
}));

beforeEach(() => {
  listNotebooksMock.mockReset();
  getNotebookMock.mockReset();
  listNotebookRunsMock.mockReset();
  proposeNotebookMock.mockReset();
  runNotebookMock.mockReset();
  publishNotebookMock.mockReset();
  getCurrentPersonMock.mockReset();
  getCurrentPersonMock.mockResolvedValue({
    personId: PERSON_ID,
    name: "Alice",
    position: null,
    tenancyRole: "admin",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/notebooks", () => {
  it("returns 200 with {notebooks: [...]}", async () => {
    listNotebooksMock.mockResolvedValueOnce([fakeNb]);
    const { GET } = await import("../../app/api/notebooks/route");
    const res = await GET(new Request("http://x/api/notebooks") as never);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.notebooks).toHaveLength(1);
    expect(body.notebooks[0].notebookId).toBe(NB_ID);
  });
});

describe("GET /api/notebooks/[id]", () => {
  it("returns 200 with notebook + runs", async () => {
    getNotebookMock.mockResolvedValueOnce(fakeNb);
    listNotebookRunsMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/notebooks/[id]/route");
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: NB_ID }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.notebook.notebookId).toBe(NB_ID);
  });

  it("returns 404 when not found", async () => {
    getNotebookMock.mockResolvedValueOnce(null);
    listNotebookRunsMock.mockResolvedValueOnce([]);
    const { GET } = await import("../../app/api/notebooks/[id]/route");
    const res = await GET(new Request("http://x"), {
      params: Promise.resolve({ id: NB_ID }),
    });
    expect(res.status).toBe(404);
  });
});

describe("POST /api/notebooks/[id]/run", () => {
  it("forwards to worm-core run", async () => {
    runNotebookMock.mockResolvedValueOnce({
      run_id: "r1",
      status: "ok",
      duration_ms: 100,
      entry_ids: ["e1"],
    });
    const { POST } = await import("../../app/api/notebooks/[id]/run/route");
    const res = await POST(
      new Request("http://x", { method: "POST", body: "{}" }),
      { params: Promise.resolve({ id: NB_ID }) },
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.run_id).toBe("r1");
    expect(runNotebookMock).toHaveBeenCalledWith(
      NB_ID,
      expect.objectContaining({ tenantSlug: "baseworm" }),
    );
  });
});

describe("POST /api/notebooks/[id]/publish", () => {
  it("forwards to worm-core publish using current Person as publisher", async () => {
    publishNotebookMock.mockResolvedValueOnce({ entry_ids: ["e1"] });
    const { POST } = await import(
      "../../app/api/notebooks/[id]/publish/route"
    );
    const res = await POST(
      new Request("http://x", {
        method: "POST",
        body: JSON.stringify({
          run_id: "r1",
          owner_person_id: PERSON_ID,
          version: "1",
        }),
      }),
      { params: Promise.resolve({ id: NB_ID }) },
    );
    expect(res.status).toBe(200);
    expect(publishNotebookMock).toHaveBeenCalledWith(
      NB_ID,
      expect.objectContaining({
        runId: "r1",
        ownerPersonId: PERSON_ID,
        publishedBy: PERSON_ID,
      }),
    );
  });

  it("returns 400 when run_id missing", async () => {
    const { POST } = await import(
      "../../app/api/notebooks/[id]/publish/route"
    );
    const res = await POST(
      new Request("http://x", {
        method: "POST",
        body: JSON.stringify({ owner_person_id: PERSON_ID, version: "1" }),
      }),
      { params: Promise.resolve({ id: NB_ID }) },
    );
    expect(res.status).toBe(400);
  });
});
