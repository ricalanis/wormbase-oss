/**
 * D8 — role-aware filtering helpers.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../lib/ledger-client", () => ({
  getRolesForPerson: vi.fn(),
}));

import * as ledgerClient from "../../lib/ledger-client";
import {
  filterByDomainAccess,
  getDomainAccessSet,
  memberHasNoAccess,
} from "../../lib/server/role-filter";
import type { CurrentPerson } from "../../lib/server/identity";

const grantsMock = vi.mocked(ledgerClient.getRolesForPerson);

beforeEach(() => {
  vi.clearAllMocks();
});

const carolAdmin: CurrentPerson = {
  personId: "p_carol",
  name: "Carol",
  position: "CFO",
  tenancyRole: "admin",
};
const bobMember: CurrentPerson = {
  personId: "p_bob",
  name: "Bob",
  position: "DE",
  tenancyRole: "member",
};
const observerSarah: CurrentPerson = {
  personId: "p_sarah",
  name: "Sarah",
  position: "Auditor",
  tenancyRole: "observer",
};

describe("getDomainAccessSet", () => {
  it("returns empty set for the Unknown fallback (no personId)", async () => {
    // The Unknown-fallback shape historically appeared with a null personId
    // before the layout's redirect-on-null guard landed. The defensive
    // ``if (!me.personId)`` branch in ``getDomainAccessSet`` still exists;
    // the cast keeps the test exercising that branch even though the
    // ``CurrentPerson`` type now requires a string.
    const access = await getDomainAccessSet("c1", {
      personId: null,
      name: "Unknown",
      position: null,
      tenancyRole: "observer",
    } as unknown as CurrentPerson);
    expect(access.size).toBe(0);
  });

  it("includes domain ids where the Person is owner or contributor", async () => {
    grantsMock.mockResolvedValueOnce([
      {
        facet: "domain",
        role: "owner",
        scopeId: "d_finance",
        scopeType: "domain",
        grantedBy: "x",
        grantedAt: "2026-04-26T00:00:00Z",
        revokedAt: null,
      },
      {
        facet: "domain",
        role: "contributor",
        scopeId: "d_marketing",
        scopeType: "domain",
        grantedBy: "x",
        grantedAt: "2026-04-26T00:00:00Z",
        revokedAt: null,
      },
      {
        facet: "tenancy",
        role: "member",
        scopeId: null,
        scopeType: null,
        grantedBy: "x",
        grantedAt: "2026-04-26T00:00:00Z",
        revokedAt: null,
      },
    ]);
    const access = await getDomainAccessSet("c1", bobMember);
    expect(access.has("d_finance")).toBe(true);
    expect(access.has("d_marketing")).toBe(true);
    expect(access.size).toBe(2);
  });
});

describe("filterByDomainAccess", () => {
  const rows = [
    { id: 1, domain_id: "d_finance", label: "Q3 net" },
    { id: 2, domain_id: "d_marketing", label: "CAC payback" },
    { id: 3, domain_id: "d_engineering", label: "p99 latency" },
  ];

  it("admin sees every row regardless of access set", () => {
    const out = filterByDomainAccess(rows, carolAdmin, new Set(["d_finance"]));
    expect(out).toHaveLength(3);
  });

  it("observer sees every row (read-only enforced via chrome)", () => {
    const out = filterByDomainAccess(rows, observerSarah, new Set());
    expect(out).toHaveLength(3);
  });

  it("member sees only rows in their access set", () => {
    const out = filterByDomainAccess(
      rows,
      bobMember,
      new Set(["d_finance", "d_marketing"]),
    );
    expect(out.map((r) => r.id)).toEqual([1, 2]);
  });

  it("member with empty access set sees nothing", () => {
    const out = filterByDomainAccess(rows, bobMember, new Set());
    expect(out).toEqual([]);
  });
});

describe("memberHasNoAccess", () => {
  it("true for a member with no grants", () => {
    expect(memberHasNoAccess(bobMember, new Set())).toBe(true);
  });
  it("false for an admin even with empty access", () => {
    expect(memberHasNoAccess(carolAdmin, new Set())).toBe(false);
  });
  it("false for a member with grants", () => {
    expect(memberHasNoAccess(bobMember, new Set(["d_finance"]))).toBe(false);
  });
});
