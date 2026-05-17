/**
 * No-installer redirect guard.
 *
 * Verifies the (app)/ layout's behavior when no Install row exists for
 * the current tenant: ``getCurrentInstall`` returns null. The matching
 * ``getCurrentPerson`` returns null when no installer/admin grant
 * exists. The dashboard's `(app)/layout.tsx` calls Next's `redirect`
 * to ``/onboarding`` in either case; this test exercises the upstream
 * helpers in isolation.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

const getInstallsMock = vi.fn();
const getPeopleMock = vi.fn();
const getRolesForPersonMock = vi.fn();

vi.mock("../../lib/ledger-client", () => ({
  getInstalls: getInstallsMock,
  getPeople: getPeopleMock,
  getRolesForPerson: getRolesForPersonMock,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("getCurrentInstall", () => {
  it("returns null when no install rows exist", async () => {
    getInstallsMock.mockResolvedValueOnce([]);
    const { getCurrentInstall } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentInstall(COMPANY_ID);
    expect(result).toBeNull();
  });

  it("returns null when getInstalls throws", async () => {
    getInstallsMock.mockRejectedValueOnce(new Error("pg down"));
    const { getCurrentInstall } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentInstall(COMPANY_ID);
    expect(result).toBeNull();
  });

  it("returns null when all installs are revoked", async () => {
    getInstallsMock.mockResolvedValueOnce([
      {
        installId: "install-1",
        platform: "slack",
        installerPersonId: "p-1",
        installerName: "Carol",
        installedAt: new Date().toISOString(),
        status: "revoked",
        scopes: [],
        botUserId: "UBOT",
        oauthGrantRef: "vault://local-dev/install-1",
        receipt: {
          hash: "deadbeef",
          source: "install-projection",
          owner: "p-1",
          classification: "internal",
        },
      },
    ]);
    const { getCurrentInstall } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentInstall(COMPANY_ID);
    expect(result).toBeNull();
  });

  it("returns the active Slack install when one exists", async () => {
    getInstallsMock.mockResolvedValueOnce([
      {
        installId: "install-1",
        platform: "slack",
        installerPersonId: "p-1",
        installerName: "Carol",
        installedAt: new Date().toISOString(),
        status: "active",
        scopes: [],
        botUserId: "UBOT",
        oauthGrantRef: "vault://local-dev/install-1",
        receipt: {
          hash: "deadbeef",
          source: "install-projection",
          owner: "p-1",
          classification: "internal",
        },
      },
    ]);
    const { getCurrentInstall } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentInstall(COMPANY_ID);
    expect(result).not.toBeNull();
    expect(result?.platform).toBe("slack");
    expect(result?.status).toBe("active");
  });
});

describe("getCurrentPerson", () => {
  it("returns null when the tenant has no people", async () => {
    getPeopleMock.mockResolvedValueOnce([]);
    const { getCurrentPerson } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentPerson(COMPANY_ID);
    expect(result).toBeNull();
  });

  it("returns null when no Person holds installer/admin grants", async () => {
    getPeopleMock.mockResolvedValueOnce([
      {
        personId: "p-1",
        displayName: "Carol",
        email: null,
        position: null,
        status: "active",
        tenancyRole: "member",
        identities: [],
        domainGrantCount: 0,
        resourceGrantCount: 0,
      },
    ]);
    getRolesForPersonMock.mockResolvedValue([]);
    const { getCurrentPerson } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentPerson(COMPANY_ID);
    expect(result).toBeNull();
  });

  it("returns the installer when one exists", async () => {
    getPeopleMock.mockResolvedValueOnce([
      {
        personId: "p-1",
        displayName: "Carol",
        email: null,
        position: "CFO",
        status: "active",
        tenancyRole: "installer",
        identities: [],
        domainGrantCount: 0,
        resourceGrantCount: 0,
      },
    ]);
    const { getCurrentPerson } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentPerson(COMPANY_ID);
    expect(result).not.toBeNull();
    expect(result?.tenancyRole).toBe("installer");
    expect(result?.personId).toBe("p-1");
    expect(result?.name).toBe("Carol");
    expect(result?.position).toBe("CFO");
  });

  it("falls back to the admin when no installer is present", async () => {
    getPeopleMock.mockResolvedValueOnce([
      {
        personId: "p-2",
        displayName: "Bob",
        email: null,
        position: null,
        status: "active",
        tenancyRole: "admin",
        identities: [],
        domainGrantCount: 0,
        resourceGrantCount: 0,
      },
    ]);
    const { getCurrentPerson } = await import(
      "../../lib/server/identity"
    );
    const result = await getCurrentPerson(COMPANY_ID);
    expect(result?.tenancyRole).toBe("admin");
    expect(result?.personId).toBe("p-2");
  });
});
