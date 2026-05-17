/**
 * Tests for `/onboarding/welcome` (W1.A3).
 *
 * Covers all three sections (hero, cascade panel, CTA stack) and both
 * states for the install summary (folded + still-propagating).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { InstallRow } from "../../../../lib/ledger-client.types";
import type { Tenant } from "../../../../lib/tenants";

const mockGetCurrentInstall = vi.fn<
  (companyId: string) => Promise<InstallRow | null>
>();
const mockGetTenantFromCookies = vi.fn<() => Promise<Tenant>>();
const mockGetCurrentCompanyId = vi.fn<() => Promise<string>>();

vi.mock("../../../../lib/ledger-client", async () => {
  const actual = await vi.importActual<
    typeof import("../../../../lib/ledger-client")
  >("../../../../lib/ledger-client");
  return {
    ...actual,
    getCurrentInstall: (companyId: string) => mockGetCurrentInstall(companyId),
  };
});

vi.mock("../../../../lib/tenant-cookies", () => ({
  TENANT_COOKIE_NAME: "wormbase-tenant-slug",
  getTenantFromCookies: () => mockGetTenantFromCookies(),
  getCurrentCompanyId: () => mockGetCurrentCompanyId(),
}));

vi.mock("@wormbase/design", () => ({
  Page: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="wb-page-shell">{children}</div>
  ),
}));

// The cascade panel is a client component with EventSource lifecycles.
// Stub it so this server-component page test stays focused on the page
// composition; the panel has its own dedicated test suite.
vi.mock("../../../../components/onboarding/InstallCascadePanel", () => ({
  InstallCascadePanel: (props: { installId: string; sinceSeq: number | null }) => (
    <div
      data-testid="install-cascade-panel-stub"
      data-install-id={props.installId}
      data-since-seq={props.sinceSeq === null ? "null" : String(props.sinceSeq)}
    />
  ),
}));

import WelcomePage from "../page";

const TENANT: Tenant = {
  slug: "baseworm",
  companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
  displayName: "Baseworm",
};

function makeInstall(overrides: Partial<InstallRow> = {}): InstallRow {
  return {
    installId: "install-42",
    platform: "slack",
    installerPersonId: "person-42",
    installerName: "Carol Installer",
    installedAt: "2026-04-27T12:00:00.000Z",
    status: "active",
    scopes: ["chat:write", "channels:history"],
    botUserId: "U_BOT",
    oauthGrantRef: "vault://local-dev/install-42",
    setupMode: null,
    setupCompletedAt: null,
    receipt: {
      hash: "deadbeef0000",
      source: "install-projection",
      owner: "person-42",
      classification: "internal",
    },
    ...overrides,
  };
}

async function renderWelcome() {
  const ui = await WelcomePage();
  return render(ui);
}

describe("WelcomePage", () => {
  beforeEach(() => {
    mockGetCurrentInstall.mockReset();
    mockGetTenantFromCookies.mockReset();
    mockGetCurrentCompanyId.mockReset();
    mockGetTenantFromCookies.mockResolvedValue(TENANT);
    mockGetCurrentCompanyId.mockResolvedValue(TENANT.companyId);
  });

  it("renders the hero with installer summary when install is folded", async () => {
    mockGetCurrentInstall.mockResolvedValue(makeInstall());
    await renderWelcome();
    expect(screen.getByTestId("welcome-hero")).toBeInTheDocument();
    expect(
      screen.getByTestId("welcome-install-summary"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("welcome-install-id").textContent).toBe(
      "install-42",
    );
    expect(screen.getByTestId("welcome-install-platform").textContent).toBe(
      "slack",
    );
    expect(
      screen.getByTestId("welcome-install-installer").textContent,
    ).toContain("Carol Installer");
    expect(screen.getByTestId("welcome-install-scopes").textContent).toContain(
      "chat:write",
    );
  });

  it("renders an honest 'still propagating' fallback when no install is folded yet", async () => {
    mockGetCurrentInstall.mockResolvedValue(null);
    await renderWelcome();
    expect(screen.getByTestId("welcome-hero")).toBeInTheDocument();
    expect(
      screen.queryByTestId("welcome-install-summary"),
    ).toBeNull();
    expect(
      screen.getByTestId("welcome-install-pending"),
    ).toBeInTheDocument();
  });

  it("mounts the InstallCascadePanel with the install id from the ledger", async () => {
    mockGetCurrentInstall.mockResolvedValue(
      makeInstall({ installId: "install-99" }),
    );
    await renderWelcome();
    const panel = screen.getByTestId("install-cascade-panel-stub");
    expect(panel.getAttribute("data-install-id")).toBe("install-99");
    expect(panel.getAttribute("data-since-seq")).toBe("null");
  });

  it("mounts the cascade panel with an empty install id when none is folded", async () => {
    mockGetCurrentInstall.mockResolvedValue(null);
    await renderWelcome();
    const panel = screen.getByTestId("install-cascade-panel-stub");
    expect(panel.getAttribute("data-install-id")).toBe("");
  });

  it("renders the CTA stack with /sources, /onboarding/tier2, and /trace", async () => {
    mockGetCurrentInstall.mockResolvedValue(makeInstall());
    await renderWelcome();
    expect(screen.getByTestId("welcome-cta-stack")).toBeInTheDocument();
    expect(screen.getByTestId("welcome-cta-sources")).toHaveAttribute(
      "href",
      "/sources",
    );
    expect(screen.getByTestId("welcome-cta-tier2")).toHaveAttribute(
      "href",
      "/onboarding/tier2",
    );
    expect(screen.getByTestId("welcome-cta-trace")).toHaveAttribute(
      "href",
      "/trace",
    );
  });

  it("greets the user with the tenant display name from the cookie", async () => {
    mockGetTenantFromCookies.mockResolvedValue({
      ...TENANT,
      displayName: "Democorp",
    });
    mockGetCurrentInstall.mockResolvedValue(makeInstall());
    await renderWelcome();
    expect(screen.getByTestId("welcome-hero").textContent).toContain(
      "Democorp",
    );
  });
});
