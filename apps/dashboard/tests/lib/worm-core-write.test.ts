/**
 * Unit tests for the dashboard's server-side worm-core write helper.
 *
 * A3.5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Mocks `fetch` so we exercise the request shape and error mapping
 * without hitting a live worm-core. The integration test under
 * `tests/integration/test_dashboard_to_wormcore_write.py` covers
 * the live HTTP path end-to-end.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN = "test-token-xyz";
const BASE = "http://worm-core-test:8910";

beforeEach(() => {
  vi.stubEnv("WORMBASE_LEDGER_API_TOKEN", TOKEN);
  vi.stubEnv("WORMBASE_LEDGER_API_BASE", BASE);
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

function fakeFetch(
  status: number,
  body: unknown,
): typeof globalThis.fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  ) as unknown as typeof globalThis.fetch;
}

describe("worm-core-write helper", () => {
  it("proposePerson sends bearer token + tenant header + JSON body", async () => {
    const fetchSpy = fakeFetch(200, {
      person_id: "11111111-2222-3333-4444-555555555555",
      entry_ids: ["a", "b", "c", "d"],
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { proposePerson } = await import(
      "../../lib/server/worm-core-write"
    );
    const result = await proposePerson({
      tenantSlug: "baseworm",
      name: "Alice",
      platform: "slack",
      platformUserId: "U-alice",
    });

    expect(result.person_id).toBe("11111111-2222-3333-4444-555555555555");
    expect(result.entry_ids).toHaveLength(4);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/people`);
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    expect(headers["Content-Type"]).toBe("application/json");
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.name).toBe("Alice");
    expect(body.platform).toBe("slack");
    expect(body.platform_user_id).toBe("U-alice");
  });

  it("throws when WORMBASE_LEDGER_API_TOKEN is unset", async () => {
    vi.unstubAllEnvs();
    vi.stubEnv("WORMBASE_LEDGER_API_BASE", BASE);
    // Important: stub fetch so a missing-token call does not
    // accidentally hit a real network.
    vi.stubGlobal("fetch", fakeFetch(200, {}));
    vi.resetModules();
    const { proposePerson } = await import(
      "../../lib/server/worm-core-write"
    );
    await expect(
      proposePerson({
        tenantSlug: "baseworm",
        name: "Alice",
        platform: "slack",
        platformUserId: "U-alice",
      }),
    ).rejects.toThrow(/WORMBASE_LEDGER_API_TOKEN is not set/);
  });

  it("propagates non-2xx responses as Errors with body text", async () => {
    const fetchSpy = fakeFetch(422, { error: "validation_failed" });
    vi.stubGlobal("fetch", fetchSpy);
    const { proposePerson } = await import(
      "../../lib/server/worm-core-write"
    );
    await expect(
      proposePerson({
        tenantSlug: "baseworm",
        name: "Alice",
        platform: "slack",
        platformUserId: "U-alice",
      }),
    ).rejects.toThrow(/422/);
  });

  it("confirmPerson encodes the person_id segment", async () => {
    const fetchSpy = fakeFetch(200, { entry_ids: ["x"] });
    vi.stubGlobal("fetch", fetchSpy);
    const { confirmPerson } = await import(
      "../../lib/server/worm-core-write"
    );
    await confirmPerson("aa/bb", {
      tenantSlug: "baseworm",
      confirmedBy: "actor",
    });
    const url = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/people/aa%2Fbb/confirm");
  });

  it("unlinkIdentity uses DELETE and encodes path segments", async () => {
    const fetchSpy = fakeFetch(200, { entry_ids: ["x"] });
    vi.stubGlobal("fetch", fetchSpy);
    const { unlinkIdentity } = await import(
      "../../lib/server/worm-core-write"
    );
    await unlinkIdentity("p1", "discord", "bob#1234", {
      tenantSlug: "baseworm",
      unlinkedBy: "actor",
    });
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const init = calls[0][1] as RequestInit;
    expect(init.method).toBe("DELETE");
    const url = calls[0][0] as string;
    expect(url).toContain("bob%231234");
  });

  it("grantRole forwards facet/scope/role payload", async () => {
    const fetchSpy = fakeFetch(200, { entry_ids: ["x"] });
    vi.stubGlobal("fetch", fetchSpy);
    const { grantRole } = await import("../../lib/server/worm-core-write");
    await grantRole("p1", {
      tenantSlug: "baseworm",
      facet: "domain",
      role: "owner",
      scopeId: "domain-uuid",
      grantedBy: "actor",
    });
    const init = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.facet).toBe("domain");
    expect(body.role).toBe("owner");
    expect(body.scope_id).toBe("domain-uuid");
  });
});
