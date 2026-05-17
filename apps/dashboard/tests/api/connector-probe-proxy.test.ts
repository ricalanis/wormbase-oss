/**
 * /api/v1/connectors/{kind}/probe proxy tests — Sub-wave D.
 *
 * Validates the dashboard proxy that forwards probe requests to
 * worm-core. The worm-core endpoint returns one of four honest
 * states; the proxy round-trips them unchanged + synthesizes an
 * honest ``unknown`` envelope on upstream unreachable (never a 502 —
 * the marketplace row renders a neutral badge so the page still
 * loads).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const ORIGINAL_ENV = { ...process.env };

const originalFetch = globalThis.fetch;

beforeEach(() => {
  delete process.env.WORMBASE_LEDGER_API_BASE;
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  globalThis.fetch = originalFetch;
});

import { GET as proxyGet } from "../../app/api/v1/connectors/[kind]/probe/route";

describe("/api/v1/connectors/{kind}/probe proxy", () => {
  it("forwards a 200 probe response unchanged", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ kind: "csv_local", state: "works", reason: null }),
          { status: 200 },
        ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await proxyGet(new Request("http://test/api/v1/connectors/csv_local/probe"), {
      params: Promise.resolve({ kind: "csv_local" }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.state).toBe("works");
  });

  it("synthesizes state=unknown when worm-core is unreachable", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await proxyGet(new Request("http://test/api/v1/connectors/stripe/probe"), {
      params: Promise.resolve({ kind: "stripe" }),
    });
    // Honest contract: still 200 from the proxy, body carries state=unknown.
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.state).toBe("unknown");
    expect(body.reason).toContain("worm-core unreachable");
  });

  it("returns 400 on empty kind", async () => {
    const res = await proxyGet(new Request("http://test/api/v1/connectors//probe"), {
      params: Promise.resolve({ kind: "" }),
    });
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.state).toBe("unknown");
  });

  it("preserves 404 from upstream", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            kind: "nonexistent",
            state: "unknown",
            reason: "unknown connector kind 'nonexistent'",
          }),
          { status: 404 },
        ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await proxyGet(
      new Request("http://test/api/v1/connectors/nonexistent/probe"),
      {
        params: Promise.resolve({ kind: "nonexistent" }),
      },
    );
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.state).toBe("unknown");
  });
});
