/**
 * Integration test for ``POST /api/v1/voice/ask`` (W3.A12).
 *
 * The dashboard route is a thin proxy to the voice-agent service. The
 * tests cover:
 *
 *   - Happy path: forwards transcript + person_id + tenant_id to
 *     voice-agent, returns the upstream envelope verbatim.
 *   - Empty transcript → 400 (no upstream call).
 *   - Upstream unreachable → 503 with honest message (no fixture).
 *   - Upstream returns non-OK → propagates message + status.
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
const PERSON_ID = "11111111-1111-1111-1111-111111111111";

const getCurrentPersonMock = vi.fn();

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: vi.fn(async () => COMPANY_ID),
  getTenantFromCookies: vi.fn(async () => ({
    slug: "baseworm",
    companyId: COMPANY_ID,
  })),
}));

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
}));

beforeEach(() => {
  getCurrentPersonMock.mockReset();
  getCurrentPersonMock.mockResolvedValue({
    personId: PERSON_ID,
    name: "Carol",
    position: "Head of Data",
    tenancyRole: "admin",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("POST /api/v1/voice/ask", () => {
  it("forwards to the voice-agent service and returns the upstream envelope", async () => {
    const upstream = {
      answer: "Q3 net revenue was four point two million dollars.",
      hash_receipt: "a".repeat(64),
      ledger_seq: 247,
      model: "kimi-k2.6:cloud",
      session_id: "dashboard-baseworm-" + PERSON_ID,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(upstream),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/v1/voice/ask/route");
    const res = await POST(
      new Request("http://x/api/v1/voice/ask", {
        method: "POST",
        body: JSON.stringify({ transcript: "what was Q3 net revenue?" }),
      }) as never,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.answer).toBe(upstream.answer);
    expect(body.hash_receipt).toBe(upstream.hash_receipt);
    expect(body.ledger_seq).toBe(247);
    expect(body.model).toBe("kimi-k2.6:cloud");

    // Verify the upstream request shape.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/v1\/ask$/);
    expect((init as RequestInit).method).toBe("POST");
    const upstreamBody = JSON.parse(
      (init as RequestInit).body as string,
    );
    expect(upstreamBody).toMatchObject({
      transcript: "what was Q3 net revenue?",
      person_id: PERSON_ID,
      tenant_id: "baseworm",
    });
  });

  it("returns 400 with no upstream call when transcript is missing/empty", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/v1/voice/ask/route");
    const res = await POST(
      new Request("http://x/api/v1/voice/ask", {
        method: "POST",
        body: JSON.stringify({ transcript: "   " }),
      }) as never,
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("transcript_required");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 503 when the voice-agent service is unreachable (no fixture fallback)", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new Error("ECONNREFUSED voice-agent:8090"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/v1/voice/ask/route");
    const res = await POST(
      new Request("http://x/api/v1/voice/ask", {
        method: "POST",
        body: JSON.stringify({ transcript: "anything" }),
      }) as never,
    );
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.error).toBe("voice_agent_unreachable");
    expect(body.message).toMatch(/ECONNREFUSED/);
  });

  it("propagates upstream non-OK with a useful message", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () =>
        JSON.stringify({ detail: "inference router unavailable" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("../../app/api/v1/voice/ask/route");
    const res = await POST(
      new Request("http://x/api/v1/voice/ask", {
        method: "POST",
        body: JSON.stringify({ transcript: "anything" }),
      }) as never,
    );
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.error).toBe("voice_agent_error");
    expect(body.message).toMatch(/inference router unavailable/i);
    expect(body.upstream_status).toBe(503);
  });
});
