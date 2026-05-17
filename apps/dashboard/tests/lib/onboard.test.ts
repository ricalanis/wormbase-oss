/**
 * lib/onboard accessor tests — Onboarding Sub-wave B (2026-05-30).
 *
 * Exercises the per-tab accessors + landing snapshot + status/logs
 * helpers. Underlying ledger-client / connectors / platform-status
 * dependencies are mocked so the tests don't need worm-core or
 * Postgres.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../lib/ledger-client", () => ({
  getInstalls: vi.fn(async () => []),
  getSources: vi.fn(async () => []),
  getDomains: vi.fn(async () => []),
  getPeople: vi.fn(async () => []),
  getPolicies: vi.fn(async () => []),
  getTraceEntries: vi.fn(async () => ({ entries: [], nextCursor: null })),
}));

vi.mock("../../lib/connectors", () => ({
  getConnectorCatalog: vi.fn(async () => ({
    production: [
      {
        kind: "stripe",
        label: "Stripe",
        description: "",
        status: "production" as const,
        statusNote: "",
        capabilities: ["discover", "profile"],
        connectionState: "disconnected" as const,
        activeSourceCount: 0,
      },
    ],
    preview: [],
    comingSoon: [
      {
        kind: "salesforce",
        label: "Salesforce",
        description: "",
        status: "coming_soon" as const,
        statusNote: "",
        capabilities: [],
        connectionState: "disconnected" as const,
        activeSourceCount: 0,
      },
    ],
    registryUnreachable: false,
    registryError: null,
    upstreamUrl: "",
  })),
}));

import * as ledger from "../../lib/ledger-client";
import * as connectors from "../../lib/connectors";
import {
  getOnboardChat,
  getOnboardSource,
  getOnboardDomain,
  getOnboardPerson,
  getOnboardPolicy,
  getOnboardLandingSnapshot,
  getObjectStatus,
  getObjectLogs,
  isStatusKind,
  __test__,
} from "../../lib/onboard";

describe("isStatusKind", () => {
  it("accepts each of the 7 known kinds", () => {
    for (const kind of [
      "connector",
      "channel",
      "domain",
      "person",
      "policy",
      "agent",
      "subscription",
    ]) {
      expect(isStatusKind(kind)).toBe(true);
    }
  });

  it("rejects unknown kinds", () => {
    expect(isStatusKind("unknown")).toBe(false);
    expect(isStatusKind("")).toBe(false);
    expect(isStatusKind("connect")).toBe(false);
  });
});

describe("getOnboardChat", () => {
  beforeEach(() => {
    vi.mocked(ledger.getInstalls).mockResolvedValue([]);
  });

  it("renders a row per PLATFORM descriptor with connected=false on empty installs", async () => {
    const view = await getOnboardChat("tenant-x");
    expect(view.rows.length).toBeGreaterThan(0);
    expect(view.rows.every((r) => r.connected === false)).toBe(true);
    const slack = view.rows.find((r) => r.platform === "slack");
    expect(slack?.status).toBe("production");
  });

  it("marks a platform as connected when an active install exists", async () => {
    vi.mocked(ledger.getInstalls).mockResolvedValueOnce([
      {
        installId: "install-1",
        platform: "slack",
        installerPersonId: null,
        installerName: null,
        installedAt: "2026-05-30T00:00:00Z",
        status: "active",
      },
    ] as never);
    const view = await getOnboardChat("tenant-x");
    const slack = view.rows.find((r) => r.platform === "slack");
    expect(slack?.connected).toBe(true);
    expect(slack?.installCount).toBe(1);
  });
});

describe("getOnboardSource", () => {
  it("composes the registry catalog with active sources", async () => {
    vi.mocked(ledger.getSources).mockResolvedValueOnce([
      { sourceId: "src-1", uri: "stripe://prod", kind: "stripe" },
    ] as never);
    const view = await getOnboardSource("tenant-x");
    expect(view.catalog.production.length).toBe(1);
    expect(view.sources.length).toBe(1);
  });
});

describe("getOnboardDomain", () => {
  it("returns the four canonical domain packs (Sub-wave C shipped)", async () => {
    const view = await getOnboardDomain("tenant-x");
    expect(view.packsAvailable).toBe(true);
    const ids = view.packs.map((p) => p.packId).sort();
    expect(ids).toEqual(["fintech", "generic", "marketplace", "saas"]);
  });

  it("forwards existing registered domains", async () => {
    vi.mocked(ledger.getDomains).mockResolvedValueOnce([
      {
        domainId: "domain-1",
        name: "Sales",
        owner: "owner-uuid",
        classificationDefault: "internal",
        resourceCount: 3,
        receipt: { hash: "h", source: "s", owner: "o", classification: "internal" },
      },
    ] as never);
    const view = await getOnboardDomain("tenant-x");
    expect(view.domains.length).toBe(1);
    expect(view.domains[0].name).toBe("Sales");
  });
});

describe("getOnboardPerson", () => {
  it("splits Persons into confirmed/proposed counts", async () => {
    vi.mocked(ledger.getPeople).mockResolvedValueOnce([
      { personId: "p1", status: "active", displayName: "Alice" },
      { personId: "p2", status: "proposed", displayName: "Bob" },
      { personId: "p3", status: "archived", displayName: "Carol" },
    ] as never);
    const view = await getOnboardPerson("tenant-x");
    expect(view.confirmedCount).toBe(1);
    expect(view.proposedCount).toBe(1);
    expect(view.people.length).toBe(3);
  });
});

describe("getOnboardPolicy", () => {
  it("counts policies that fired in the last 7 days", async () => {
    vi.mocked(ledger.getPolicies).mockResolvedValueOnce([
      { policyId: "pol-1", name: "Retention", firesLast7d: 3 },
      { policyId: "pol-2", name: "PII", firesLast7d: 0 },
    ] as never);
    const view = await getOnboardPolicy("tenant-x");
    expect(view.policies.length).toBe(2);
    expect(view.firedRecently).toBe(1);
  });
});

describe("getOnboardLandingSnapshot", () => {
  it("produces 7 tab summaries in the canonical order", async () => {
    const snapshot = await getOnboardLandingSnapshot("tenant-x");
    expect(snapshot.tabs.map((t) => t.tab)).toEqual([
      "chat",
      "source",
      "domain",
      "person",
      "policy",
      "agent",
      "subscription",
    ]);
    for (const tab of snapshot.tabs) {
      expect(typeof tab.hint).toBe("string");
      expect(tab.hint.length).toBeGreaterThan(0);
    }
  });
});

describe("getObjectStatus", () => {
  it("returns unknown when the install id can't be folded", async () => {
    vi.mocked(ledger.getInstalls).mockResolvedValueOnce([]);
    const status = await getObjectStatus("tenant-x", "channel", "nope-id");
    expect(status.state).toBe("unknown");
    expect(status.probeImplemented).toBe(false);
  });

  it("returns works for an active install", async () => {
    vi.mocked(ledger.getInstalls).mockResolvedValueOnce([
      {
        installId: "install-1",
        platform: "slack",
        installerPersonId: null,
        installerName: "Alice",
        installedAt: "2026-05-30T00:00:00Z",
        status: "active",
      },
    ] as never);
    const status = await getObjectStatus("tenant-x", "channel", "install-1");
    expect(status.state).toBe("works");
    expect(status.summary).toContain("Alice");
  });

  it("returns failed for a revoked install", async () => {
    vi.mocked(ledger.getInstalls).mockResolvedValueOnce([
      {
        installId: "install-2",
        platform: "slack",
        installerPersonId: null,
        installerName: null,
        installedAt: "2026-05-30T00:00:00Z",
        status: "revoked",
      },
    ] as never);
    const status = await getObjectStatus("tenant-x", "channel", "install-2");
    expect(status.state).toBe("failed");
    expect(status.recoveryHint).toBeTruthy();
  });

  it("returns degraded for a domain without an owner", async () => {
    vi.mocked(ledger.getDomains).mockResolvedValueOnce([
      {
        domainId: "d1",
        name: "Ops",
        owner: "unassigned",
        classificationDefault: "internal",
        resourceCount: 0,
        receipt: { hash: "", source: "", owner: "", classification: "internal" },
      },
    ] as never);
    const status = await getObjectStatus("tenant-x", "domain", "d1");
    expect(status.state).toBe("degraded");
  });

  it("renders agent + subscription as unknown with probe-not-wired note", async () => {
    const agent = await getObjectStatus("tenant-x", "agent", "agent-1");
    expect(agent.state).toBe("unknown");
    expect(agent.probeImplemented).toBe(false);
    const sub = await getObjectStatus("tenant-x", "subscription", "sub-1");
    expect(sub.state).toBe("unknown");
    expect(sub.probeImplemented).toBe(false);
  });
});

describe("getObjectLogs", () => {
  it("returns empty page when no entries match", async () => {
    vi.mocked(ledger.getTraceEntries).mockResolvedValueOnce({
      entries: [],
      nextCursor: null,
    });
    const page = await getObjectLogs("tenant-x", "connector", "src-1");
    expect(page.entries).toEqual([]);
    expect(page.total).toBe(0);
    expect(page.nextOffset).toBeNull();
    expect(page.scanned).toBe(true);
  });

  it("paginates with limit + offset", async () => {
    vi.mocked(ledger.getTraceEntries).mockResolvedValueOnce({
      entries: Array.from({ length: 50 }, (_, i) => ({
        id: `e${i}`,
        ts: "2026-05-30T00:00:00Z",
        kind: "source_proposed",
        quadrant: "execute" as const,
        hash: `abc${i.toString().padStart(3, "0")}`,
        prevHash: null,
        payload: { args: { source_id: "src-target" }, tool: "emit_source_proposed" },
        receipt: { hash: "", source: "", owner: "", classification: "internal" },
      })),
      nextCursor: null,
    });
    const page = await getObjectLogs("tenant-x", "connector", "src-target", {
      limit: 10,
      offset: 0,
    });
    expect(page.entries.length).toBe(10);
    expect(page.total).toBe(50);
    expect(page.nextOffset).toBe(10);
  });
});

describe("matchesObject", () => {
  it("matches person by actor field", () => {
    expect(
      __test__.matchesObject(
        { args: {}, actor: "person-xyz" },
        "person",
        "person-xyz",
      ),
    ).toBe(true);
  });

  it("matches policy by policy_name in args", () => {
    expect(
      __test__.matchesObject(
        { args: { policy_name: "PII" } },
        "policy",
        "PII",
      ),
    ).toBe(true);
  });

  it("falls back to deep substring match", () => {
    expect(
      __test__.matchesObject(
        { args: { applies_to: { policy_id: "deep-id" } } },
        "policy",
        "deep-id",
      ),
    ).toBe(true);
  });

  it("returns false when id is absent", () => {
    expect(
      __test__.matchesObject({ args: {} }, "policy", "nope"),
    ).toBe(false);
  });
});
