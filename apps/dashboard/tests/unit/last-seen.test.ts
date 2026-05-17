/**
 * Phase 3 Task 3A — last-seen cookie boundary.
 *
 * Tests the read-then-bump contract that powers the WormActivityTile's
 * "since you logged off" boundary:
 *
 *   - First visit (no cookie)      → returns null, sets cookie to "now".
 *   - Subsequent visit (cookie set) → returns previous, sets cookie to "now".
 *   - Tampered / malformed cookie  → returns null (defensive).
 *   - Per-tenant isolation         → switching tenants reads a different cookie.
 */
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";

import { readAndBumpLastSeen } from "../../lib/server/last-seen";

interface MockCookieStore {
  store: Map<string, string>;
  setLog: Array<{
    name: string;
    value: string;
    httpOnly?: boolean;
    sameSite?: string;
    path?: string;
    maxAge?: number;
  }>;
  get: (name: string) => { value: string } | undefined;
  set: (
    opts:
      | string
      | {
          name: string;
          value: string;
          httpOnly?: boolean;
          sameSite?: string;
          path?: string;
          maxAge?: number;
        },
    value?: string,
  ) => void;
}

let mockStore: MockCookieStore | null = null;

vi.mock("next/headers", () => ({
  cookies: () => mockStore,
}));

function freshStore(): MockCookieStore {
  const store = new Map<string, string>();
  const setLog: MockCookieStore["setLog"] = [];
  return {
    store,
    setLog,
    get: (name: string) => {
      const value = store.get(name);
      return value === undefined ? undefined : { value };
    },
    set: (opts, value) => {
      const o =
        typeof opts === "string"
          ? { name: opts, value: value ?? "" }
          : opts;
      store.set(o.name, o.value);
      setLog.push(o);
    },
  };
}

describe("readAndBumpLastSeen (Phase 3 Task 3A)", () => {
  beforeEach(() => {
    mockStore = freshStore();
  });
  afterEach(() => {
    mockStore = null;
  });

  it("returns null on the first visit (no cookie set yet)", async () => {
    const now = new Date("2026-05-03T10:00:00Z");
    const got = await readAndBumpLastSeen("acme", now);
    expect(got).toBeNull();
    // The bump still happens — the next visit reads this timestamp.
    expect(mockStore!.setLog).toHaveLength(1);
    expect(mockStore!.setLog[0].name).toBe("wormbase-last-seen-acme");
    expect(mockStore!.setLog[0].value).toBe("2026-05-03T10:00:00.000Z");
    expect(mockStore!.setLog[0].httpOnly).toBe(true);
    expect(mockStore!.setLog[0].sameSite).toBe("lax");
    expect(mockStore!.setLog[0].path).toBe("/");
  });

  it("returns the previous timestamp on subsequent visits and bumps to now", async () => {
    mockStore!.store.set(
      "wormbase-last-seen-acme",
      "2026-05-02T08:00:00.000Z",
    );
    const now = new Date("2026-05-03T10:00:00Z");
    const got = await readAndBumpLastSeen("acme", now);
    expect(got).toBe("2026-05-02T08:00:00.000Z");
    expect(mockStore!.setLog[0].value).toBe("2026-05-03T10:00:00.000Z");
  });

  it("treats malformed cookie values as 'first visit' (returns null)", async () => {
    mockStore!.store.set("wormbase-last-seen-acme", "not-a-timestamp");
    const got = await readAndBumpLastSeen("acme");
    expect(got).toBeNull();
  });

  it("isolates cookies per tenant slug", async () => {
    mockStore!.store.set(
      "wormbase-last-seen-acme",
      "2026-05-02T08:00:00.000Z",
    );
    mockStore!.store.set(
      "wormbase-last-seen-globex",
      "2026-04-30T12:00:00.000Z",
    );
    const acme = await readAndBumpLastSeen("acme");
    const globex = await readAndBumpLastSeen("globex");
    expect(acme).toBe("2026-05-02T08:00:00.000Z");
    expect(globex).toBe("2026-04-30T12:00:00.000Z");
  });

  it("returns null when next/headers is unavailable (e.g. static gen)", async () => {
    mockStore = null;
    const got = await readAndBumpLastSeen("acme");
    expect(got).toBeNull();
  });
});
