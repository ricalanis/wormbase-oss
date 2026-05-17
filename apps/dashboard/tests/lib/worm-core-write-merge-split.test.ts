/**
 * Unit tests for the merge/split additions to the dashboard's
 * server-side worm-core write helper (A6).
 *
 * Mocks `fetch` so we exercise the request shape and error mapping
 * without hitting a live worm-core. Mirrors the structure of
 * `worm-core-write.test.ts`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN = "test-token-merge-xyz";
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

describe("worm-core-write merge/split helpers", () => {
  it("mergePersons posts to /api/v1/people/merge with the right body", async () => {
    const fetchSpy = fakeFetch(200, {
      keeper_id: "k",
      mergee_id: "m",
      identities_moved: 2,
      entry_ids: ["a", "b", "c"],
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { mergePersons } = await import(
      "../../lib/server/worm-core-write"
    );
    const result = await mergePersons({
      tenantSlug: "baseworm",
      keeperId: "k",
      mergeeId: "m",
      mergedBy: "admin",
    });

    expect(result.identities_moved).toBe(2);
    expect(result.entry_ids).toHaveLength(3);
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    expect(calls[0][0]).toBe(`${BASE}/api/v1/people/merge`);
    const init = calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
    expect(headers["X-Tenant-Slug"]).toBe("baseworm");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({
      keeper_id: "k",
      mergee_id: "m",
      merged_by: "admin",
    });
  });

  it("mergePersons propagates 4xx as Errors with body text", async () => {
    const fetchSpy = fakeFetch(422, { error: "validation_failed" });
    vi.stubGlobal("fetch", fetchSpy);
    const { mergePersons } = await import(
      "../../lib/server/worm-core-write"
    );
    await expect(
      mergePersons({
        tenantSlug: "baseworm",
        keeperId: "k",
        mergeeId: "k",
        mergedBy: "admin",
      }),
    ).rejects.toThrow(/422/);
  });

  it("splitPerson posts to /api/v1/people/{id}/split and snake_cases identities_to_move", async () => {
    const fetchSpy = fakeFetch(200, {
      source_person_id: "src",
      new_person_id: "newp",
      identities_moved: 2,
      entry_ids: ["a", "b"],
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { splitPerson } = await import(
      "../../lib/server/worm-core-write"
    );
    const result = await splitPerson("src/123", {
      tenantSlug: "baseworm",
      newPersonName: "Bob",
      newPersonEmail: "bob@x.co",
      newPersonPosition: "Engineer",
      identitiesToMove: [
        { platform: "discord", platformUserId: "bob#1234" },
        { platform: "teams", platformUserId: "bob@x.co" },
      ],
      splitBy: "admin",
    });

    expect(result.new_person_id).toBe("newp");
    expect(result.identities_moved).toBe(2);
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const url = calls[0][0] as string;
    // path segment is encoded
    expect(url).toContain("/api/v1/people/src%2F123/split");
    const init = calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.new_person_name).toBe("Bob");
    expect(body.new_person_email).toBe("bob@x.co");
    expect(body.new_person_position).toBe("Engineer");
    expect(body.split_by).toBe("admin");
    expect(body.identities_to_move).toEqual([
      { platform: "discord", platform_user_id: "bob#1234" },
      { platform: "teams", platform_user_id: "bob@x.co" },
    ]);
  });

  it("splitPerson sends null for unset email/position", async () => {
    const fetchSpy = fakeFetch(200, {
      source_person_id: "src",
      new_person_id: "newp",
      identities_moved: 1,
      entry_ids: [],
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { splitPerson } = await import(
      "../../lib/server/worm-core-write"
    );
    await splitPerson("src", {
      tenantSlug: "baseworm",
      newPersonName: "Bob",
      identitiesToMove: [
        { platform: "slack", platformUserId: "U-x" },
      ],
      splitBy: "admin",
    });
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const init = calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.new_person_email).toBeNull();
    expect(body.new_person_position).toBeNull();
  });
});
