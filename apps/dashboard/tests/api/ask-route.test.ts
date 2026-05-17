/**
 * Phase 3 Task 3B — POST /api/ask route handler.
 *
 * The dashboard route is a thin pass-through to worm-core's
 * ``POST /api/v1/worm/ask`` when ``WORMBASE_LEDGER_API_TOKEN`` is set.
 * Without the token, it returns the honest "wiring note" stub so
 * evaluators see truthful copy. The body shape is identical regardless.
 *
 * Tests cover:
 *   - 400 on missing/empty question
 *   - 400 on non-JSON body
 *   - Pass-through enabled (token set): forwards to worm-core, returns
 *     upstream answer with passthrough=true
 *   - Pass-through disabled (no token): returns honest stub with
 *     passthrough=false (no upstream call)
 *   - Upstream error: returns 502 with truthful failure message
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

const ORIGINAL_TOKEN = process.env.WORMBASE_LEDGER_API_TOKEN;
const ORIGINAL_BASE = process.env.WORMBASE_LEDGER_API_BASE;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (ORIGINAL_TOKEN === undefined) {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
  } else {
    process.env.WORMBASE_LEDGER_API_TOKEN = ORIGINAL_TOKEN;
  }
  if (ORIGINAL_BASE === undefined) {
    delete process.env.WORMBASE_LEDGER_API_BASE;
  } else {
    process.env.WORMBASE_LEDGER_API_BASE = ORIGINAL_BASE;
  }
});

describe("POST /api/ask", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("returns 400 when question is missing", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({}),
      }) as never,
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.passthrough).toBe(false);
  });

  it("returns 400 when question is empty/whitespace", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "   " }),
      }) as never,
    );
    expect(res.status).toBe(400);
  });

  it("returns 400 when body is not JSON", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: "not json",
      }) as never,
    );
    expect(res.status).toBe(400);
  });

  it("returns the honest stub when WORMBASE_LEDGER_API_TOKEN is unset", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "What is Q3 net revenue?" }),
      }) as never,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.passthrough).toBe(false);
    expect(body.answer).toMatch(/worm-core is not reachable/i);
    expect(body.references).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards to worm-core /api/v1/worm/ask when token is set", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    process.env.WORMBASE_LEDGER_API_BASE = "http://worm-core:8910";
    const upstream = {
      ok: true,
      answer: "Acknowledged.",
      references: [],
      passthrough: true,
      channel_id: "in_app:abc",
      chat_reply_id: "11111111-1111-1111-1111-111111111111",
      chat_received_seq: 42,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(upstream),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "What is Q3?" }),
      }) as never,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.passthrough).toBe(true);
    expect(body.answer).toBe("Acknowledged.");
    expect(body.channel_id).toBe("in_app:abc");
    expect(body.chat_reply_id).toBe("11111111-1111-1111-1111-111111111111");

    // Verify upstream call shape.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/v1\/worm\/ask$/);
    expect((init as RequestInit).method).toBe("POST");
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    const upstreamBody = JSON.parse((init as RequestInit).body as string);
    expect(upstreamBody).toEqual({ question: "What is Q3?" });
  });

  it("returns 502 with truthful message when upstream fails", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new Error("ECONNREFUSED worm-core:8910"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "ping" }),
      }) as never,
    );
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.passthrough).toBe(false);
    expect(body.answer).toMatch(/passthrough failed/);
    expect(body.answer).toMatch(/ECONNREFUSED/);
  });

  it("returns 502 when upstream returns non-OK status", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "test-token";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => '{"error":"boom"}',
    });
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/ask/route");
    const res = await POST(
      new Request("http://x/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "ping" }),
      }) as never,
    );
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.passthrough).toBe(false);
  });
});
