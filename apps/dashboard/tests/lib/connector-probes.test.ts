/**
 * lib/connector-probes accessor tests — Sub-wave D.
 *
 * Coverage:
 *   * Successful ``works`` probe round-trips through the proxy.
 *   * ``unknown`` for unwired kinds is preserved (not flipped to works).
 *   * 404 from worm-core surfaces as ``state="unknown"`` (no false-positive).
 *   * Network error → ``state="unknown"`` with reason carrying the error.
 *   * Non-JSON / malformed body → ``state="unknown"`` honestly.
 *   * Batched ``probeConnectors`` returns a map keyed by kind.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const { headersMock } = vi.hoisted(() => ({
  headersMock: vi.fn(async () => {
    throw new Error("not inside an RSC context");
  }),
}));

vi.mock("next/headers", () => ({
  headers: headersMock,
}));

import {
  probeConnector,
  probeConnectors,
} from "../../lib/connector-probes";

beforeEach(() => {
  headersMock.mockReset();
  // Default: outside RSC — force the direct-upstream path so tests
  // can assert against the worm-core base URL.
  headersMock.mockImplementation(async () => {
    throw new Error("not inside an RSC context");
  });
});

describe("probeConnector", () => {
  it("returns works on a 200 probe response", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ kind: "csv_local", state: "works", reason: null }),
          { status: 200 },
        ),
    );
    const probe = await probeConnector("csv_local", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("works");
    expect(probe.kind).toBe("csv_local");
  });

  it("preserves unknown state for unwired kinds (no fake-positive)", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            kind: "stripe",
            state: "unknown",
            reason: "probe not yet implemented for kind 'stripe'",
          }),
          { status: 200 },
        ),
    );
    const probe = await probeConnector("stripe", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("unknown");
    expect(probe.reason).toContain("probe not yet implemented");
  });

  it("surfaces 404 as state=unknown (never flips to works)", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            kind: "not_a_real_kind",
            state: "unknown",
            reason: "unknown connector kind 'not_a_real_kind'",
          }),
          { status: 404 },
        ),
    );
    const probe = await probeConnector("not_a_real_kind", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("unknown");
    expect(probe.reason).toContain("unknown connector kind");
  });

  it("returns state=unknown on network error (honest, never fake-works)", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const probe = await probeConnector("stripe", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("unknown");
    expect(probe.reason).toContain("probe fetch failed");
  });

  it("returns state=unknown on malformed (non-JSON) body", async () => {
    const fetchImpl = vi.fn(
      async () => new Response("not json", { status: 200 }),
    );
    const probe = await probeConnector("stripe", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("unknown");
  });

  it("returns state=unknown when state field is missing or invalid", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ kind: "stripe", reason: "x" }), {
          status: 200,
        }),
    );
    const probe = await probeConnector("stripe", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(probe.state).toBe("unknown");
    expect(probe.reason).toContain("missing or invalid 'state'");
  });
});

describe("probeConnectors", () => {
  it("returns a kind-keyed Map of probes", async () => {
    const fetchImpl = vi.fn(async (input) => {
      const url = String(input);
      if (url.includes("csv_local")) {
        return new Response(
          JSON.stringify({ kind: "csv_local", state: "works", reason: null }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({
          kind: "stripe",
          state: "unknown",
          reason: "probe not wired",
        }),
        { status: 200 },
      );
    });
    const map = await probeConnectors(["csv_local", "stripe"], {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(map.size).toBe(2);
    expect(map.get("csv_local")?.state).toBe("works");
    expect(map.get("stripe")?.state).toBe("unknown");
  });
});
