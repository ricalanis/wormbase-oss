/**
 * Unit tests for the people fold (A3, read-only scope).
 *
 * Strategy: mock the `pg` module so we can drive controlled ledger rows
 * through `getPeople`, `getPersonById`, `getIdentitiesForPerson`, and
 * `getRolesForPerson`. These tests exercise the fold semantics directly —
 * the SQL is tested by the existing `tests/unit/ledger-client.test.ts`
 * Postgres-path block.
 *
 * See docs/superpowers/plans/2026-04-26-production-dashboard.md → Task A3.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90"; // baseworm
const PERSON_A = "11111111-1111-1111-1111-111111111111";
const PERSON_B = "22222222-2222-2222-2222-222222222222";
const ADMIN = "99999999-9999-9999-9999-999999999999";
const DOMAIN_FINANCE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const DOMAIN_PRODUCT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

interface FakeLedgerRow {
  seq: number;
  ts: Date;
  tool: string;
  args: Record<string, unknown>;
  hash_hex: string;
}

let __seq = 0;
function row(
  tool: string,
  args: Record<string, unknown>,
  ts = "2026-04-26T10:00:00Z",
): FakeLedgerRow {
  __seq += 1;
  return {
    seq: __seq,
    ts: new Date(ts),
    tool,
    args,
    hash_hex: ("0".repeat(56) + __seq.toString(16).padStart(8, "0")),
  };
}

function proposed(personId: string, opts: Partial<{
  name: string;
  email: string;
  position: string;
  platform: string;
  platform_user_id: string;
  proposed_by: string;
}> = {}, ts?: string): FakeLedgerRow {
  return row(
    "emit_person_proposed",
    {
      person_id: personId,
      tenant_id: COMPANY_ID,
      name: opts.name ?? "Test Person",
      email: opts.email ?? null,
      platform: opts.platform ?? "slack",
      platform_user_id: opts.platform_user_id ?? `U-${personId.slice(0, 4)}`,
      position: opts.position ?? null,
      proposed_by: opts.proposed_by ?? "worm",
    },
    ts,
  );
}

function confirmed(personId: string, by = ADMIN, ts?: string): FakeLedgerRow {
  return row(
    "emit_person_confirmed",
    { person_id: personId, confirmed_by: by },
    ts,
  );
}

function archived(
  personId: string,
  reason = "duplicate",
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_person_archived",
    { person_id: personId, archived_by: ADMIN, reason },
    ts,
  );
}

function identityLinked(
  personId: string,
  platform: string,
  platformUserId: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_identity_linked",
    {
      person_id: personId,
      platform,
      platform_user_id: platformUserId,
      linked_by: ADMIN,
    },
    ts,
  );
}

function identityUnlinked(
  personId: string,
  platform: string,
  platformUserId: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_identity_unlinked",
    {
      person_id: personId,
      platform,
      platform_user_id: platformUserId,
      unlinked_by: ADMIN,
    },
    ts,
  );
}

function roleAssigned(
  personId: string,
  role: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_role_assigned",
    { person_id: personId, role, granted_by: ADMIN },
    ts,
  );
}

function roleRevoked(
  personId: string,
  role: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_role_revoked",
    { person_id: personId, role, revoked_by: ADMIN },
    ts,
  );
}

function domainRoleAssigned(
  personId: string,
  domainId: string,
  role: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_domain_role_assigned",
    {
      person_id: personId,
      domain_id: domainId,
      role,
      granted_by: ADMIN,
    },
    ts,
  );
}

function resourceRoleAssigned(
  personId: string,
  resourceId: string,
  resourceType: string,
  role: string,
  ts?: string,
): FakeLedgerRow {
  return row(
    "emit_resource_role_assigned",
    {
      person_id: personId,
      resource_id: resourceId,
      resource_type: resourceType,
      role,
      granted_by: ADMIN,
    },
    ts,
  );
}

describe("ledger-client people fold (A3)", () => {
  // Per-test mock of the pg module. Each test sets the rows the mocked
  // client will return, then imports the ledger-client fresh so the pool
  // singleton picks up the new mock.
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    __seq = 0;
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("two emit_person_proposed rows → two PersonRows with status='proposed'", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice", email: "alice@x.co" }),
        proposed(PERSON_B, { name: "Bob", email: "bob@x.co" }),
      ],
      rowCount: 2,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);

    expect(persons).toHaveLength(2);
    for (const p of persons) {
      expect(p.status).toBe("proposed");
      expect(p.tenancyRole).toBeNull();
      expect(p.identities).toHaveLength(1); // initial identity from the propose
      expect(p.domainGrantCount).toBe(0);
      expect(p.resourceGrantCount).toBe(0);
    }
    const alice = persons.find((p) => p.personId === PERSON_A)!;
    expect(alice.displayName).toBe("Alice");
    expect(alice.email).toBe("alice@x.co");
  });

  it("surfaces proposedBy + addedAt on the projected identity row (W4-D)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(
          PERSON_A,
          {
            name: "+5215512345678",
            platform: "whatsapp",
            platform_user_id: "5215512345678@s.whatsapp.net",
            proposed_by: "worm:whatsapp_organic_discovery",
          },
          "2026-04-26T10:00:00Z",
        ),
      ],
      rowCount: 1,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons).toHaveLength(1);
    const identity = persons[0].identities[0];
    expect(identity.proposedBy).toBe("worm:whatsapp_organic_discovery");
    expect(identity.addedAt).toBe("2026-04-26T10:00:00.000Z");
  });

  it("emit_person_proposed + emit_person_confirmed → status='active' and back-compat receipt set", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [proposed(PERSON_A, { name: "Alice" }), confirmed(PERSON_A)],
      rowCount: 2,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);

    expect(persons).toHaveLength(1);
    expect(persons[0].status).toBe("active");
    // Receipt should reflect the most-recent entry that touched the Person.
    expect(persons[0].receipt.hash).toBeTruthy();
  });

  it("emit_person_proposed + emit_person_archived → status='archived'", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        archived(PERSON_A, "duplicate"),
      ],
      rowCount: 2,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons).toHaveLength(1);
    expect(persons[0].status).toBe("archived");
  });

  it("emit_identity_linked after emit_person_proposed grows identities", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, {
          name: "Alice",
          platform: "slack",
          platform_user_id: "U-slack",
        }),
        identityLinked(PERSON_A, "discord", "alice#1234"),
      ],
      rowCount: 2,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].identities).toHaveLength(2);
    const platforms = persons[0].identities.map((i) => i.platform).sort();
    expect(platforms).toEqual(["discord", "slack"]);
  });

  it("emit_identity_unlinked shrinks identities", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, {
          name: "Alice",
          platform: "slack",
          platform_user_id: "U-slack",
        }),
        identityLinked(PERSON_A, "discord", "alice#1234"),
        identityUnlinked(PERSON_A, "slack", "U-slack"),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].identities).toHaveLength(1);
    expect(persons[0].identities[0].platform).toBe("discord");
  });

  it("emit_role_assigned 'admin' surfaces tenancyRole='admin'", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        confirmed(PERSON_A),
        roleAssigned(PERSON_A, "admin"),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].tenancyRole).toBe("admin");
    expect(persons[0].roles).toContain("admin");
  });

  it("emit_role_revoked admin → tenancyRole drops back to null (revoked)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        roleAssigned(PERSON_A, "admin"),
        roleRevoked(PERSON_A, "admin"),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].tenancyRole).toBeNull();
  });

  it("installer beats admin in tenancyRole priority when both are held", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        roleAssigned(PERSON_A, "admin"),
        roleAssigned(PERSON_A, "installer"),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].tenancyRole).toBe("installer");
  });

  it("two emit_domain_role_assigned grants → domainGrantCount=2", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        domainRoleAssigned(PERSON_A, DOMAIN_FINANCE, "owner"),
        domainRoleAssigned(PERSON_A, DOMAIN_PRODUCT, "owner"),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].domainGrantCount).toBe(2);
    // back-compat ownedDomains list mirrors owner-role grants.
    expect(persons[0].ownedDomains.sort()).toEqual(
      [DOMAIN_FINANCE, DOMAIN_PRODUCT].sort(),
    );
  });

  it("resourceGrantCount counts emit_resource_role_assigned grants", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        proposed(PERSON_A, { name: "Alice" }),
        resourceRoleAssigned(
          PERSON_A,
          "cccccccc-cccc-cccc-cccc-cccccccccccc",
          "kpi",
          "maintainer",
        ),
        resourceRoleAssigned(
          PERSON_A,
          "dddddddd-dddd-dddd-dddd-dddddddddddd",
          "source",
          "contributor",
        ),
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons[0].resourceGrantCount).toBe(2);
    expect(persons[0].ownedResources).toHaveLength(1); // only the maintainer grant
  });

  it("getPeople returns [] on empty ledger (no PEOPLE fixture leakage)", async () => {
    // PRD §11.1 — no fixture loads in production paths. Empty ledger ⇒
    // empty list, NOT the demo PEOPLE fixture.
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });

    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons).toEqual([]);
  });

  it("getPeople returns [] when Postgres throws (no fixture leakage)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/ledger-client");
    const persons = await mod.getPeople(COMPANY_ID);
    expect(persons).toEqual([]);
  });

  describe("getPersonById", () => {
    it("returns the folded PersonRow for a known person", async () => {
      queryMock.mockResolvedValueOnce({
        rows: [
          proposed(PERSON_A, { name: "Alice" }),
          confirmed(PERSON_A),
          roleAssigned(PERSON_A, "admin"),
        ],
        rowCount: 3,
      });

      const mod = await import("../../lib/ledger-client");
      const person = await mod.getPersonById(COMPANY_ID, PERSON_A);
      expect(person).not.toBeNull();
      expect(person!.personId).toBe(PERSON_A);
      expect(person!.status).toBe("active");
      expect(person!.tenancyRole).toBe("admin");
    });

    it("returns null when the Person doesn't exist in this tenant", async () => {
      queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
      const mod = await import("../../lib/ledger-client");
      const person = await mod.getPersonById(COMPANY_ID, PERSON_A);
      expect(person).toBeNull();
    });
  });

  describe("getIdentitiesForPerson", () => {
    it("folds initial + linked − unlinked", async () => {
      queryMock.mockResolvedValueOnce({
        rows: [
          proposed(PERSON_A, {
            name: "Alice",
            platform: "slack",
            platform_user_id: "U-slack",
          }),
          identityLinked(PERSON_A, "discord", "alice#1234"),
          identityLinked(PERSON_A, "teams", "alice@x.co"),
          identityUnlinked(PERSON_A, "discord", "alice#1234"),
        ],
        rowCount: 4,
      });

      const mod = await import("../../lib/ledger-client");
      const identities = await mod.getIdentitiesForPerson(COMPANY_ID, PERSON_A);
      const platforms = identities.map((i) => i.platform).sort();
      expect(platforms).toEqual(["slack", "teams"]);
      const slack = identities.find((i) => i.platform === "slack")!;
      expect(slack.platformUserId).toBe("U-slack");
      expect(slack.displayName).toBe("Alice");
      expect(slack.addedAt).toBeTruthy();
    });

    it("surfaces `proposed_by` from emit_person_proposed for organic-WhatsApp discovery (D2)", async () => {
      queryMock.mockResolvedValueOnce({
        rows: [
          proposed(PERSON_A, {
            name: "Bea",
            platform: "whatsapp",
            platform_user_id: "5511999998888@s.whatsapp.net",
            proposed_by: "worm:whatsapp_organic_discovery",
          }),
        ],
        rowCount: 1,
      });

      const mod = await import("../../lib/ledger-client");
      const identities = await mod.getIdentitiesForPerson(COMPANY_ID, PERSON_A);
      expect(identities).toHaveLength(1);
      expect(identities[0].platform).toBe("whatsapp");
      expect(identities[0].platformUserId).toBe(
        "5511999998888@s.whatsapp.net",
      );
      expect(identities[0].proposedBy).toBe(
        "worm:whatsapp_organic_discovery",
      );
    });

    it("surfaces `linked_by` on emit_identity_linked rows as the proposedBy attribution (D2)", async () => {
      queryMock.mockResolvedValueOnce({
        rows: [
          proposed(PERSON_A, {
            name: "Carol",
            platform: "slack",
            platform_user_id: "U-carol",
            proposed_by: "worm",
          }),
          identityLinked(PERSON_A, "whatsapp", "5511888887777@s.whatsapp.net"),
        ],
        rowCount: 2,
      });

      const mod = await import("../../lib/ledger-client");
      const identities = await mod.getIdentitiesForPerson(COMPANY_ID, PERSON_A);
      const wa = identities.find((i) => i.platform === "whatsapp")!;
      // identityLinked() helper sets linked_by = ADMIN
      expect(wa.proposedBy).toBe(ADMIN);
      const slack = identities.find((i) => i.platform === "slack")!;
      expect(slack.proposedBy).toBe("worm");
    });
  });

  describe("getRolesForPerson", () => {
    it("returns unrevoked tenancy + domain + resource grants", async () => {
      queryMock.mockResolvedValueOnce({
        rows: [
          roleAssigned(PERSON_A, "admin"),
          roleAssigned(PERSON_A, "member"),
          roleRevoked(PERSON_A, "member"),
          domainRoleAssigned(PERSON_A, DOMAIN_FINANCE, "owner"),
          resourceRoleAssigned(
            PERSON_A,
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "kpi",
            "maintainer",
          ),
        ],
        rowCount: 5,
      });

      const mod = await import("../../lib/ledger-client");
      const roles = await mod.getRolesForPerson(COMPANY_ID, PERSON_A);

      const tenancy = roles.filter((r) => r.facet === "tenancy");
      expect(tenancy).toHaveLength(1);
      expect(tenancy[0].role).toBe("admin");

      const domain = roles.filter((r) => r.facet === "domain");
      expect(domain).toHaveLength(1);
      expect(domain[0].role).toBe("owner");
      expect(domain[0].scopeId).toBe(DOMAIN_FINANCE);
      expect(domain[0].scopeType).toBe("domain");

      const resource = roles.filter((r) => r.facet === "resource");
      expect(resource).toHaveLength(1);
      expect(resource[0].role).toBe("maintainer");
      expect(resource[0].scopeType).toBe("kpi");
    });

    it("returns [] when the Person has no role grants", async () => {
      queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
      const mod = await import("../../lib/ledger-client");
      const roles = await mod.getRolesForPerson(COMPANY_ID, PERSON_A);
      expect(roles).toEqual([]);
    });
  });
});
