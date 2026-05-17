/**
 * Tests for `/login` page (W1.A3).
 *
 * Renders the server-component page output as a stream-of-elements via
 * React's async component support, then asserts the tenant picker
 * surfaces. Postgres-empty is the steady state under test (no tenant has
 * any installs), so the bulk of the suite covers the empty path; a small
 * subset injects synthetic InstallSummary data via a vitest mock to
 * verify card rendering.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { InstallSummary } from "../../../lib/ledger-client.types";

const mockGetAllInstalls = vi.fn<() => Promise<InstallSummary[]>>();

vi.mock("../../../lib/ledger-client", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/ledger-client")>(
    "../../../lib/ledger-client",
  );
  return {
    ...actual,
    getAllInstalls: () => mockGetAllInstalls(),
  };
});

vi.mock("../actions", () => ({
  selectTenant: vi.fn(async () => undefined),
}));

vi.mock("@wormbase/design", () => ({
  Page: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="wb-page-shell">{children}</div>
  ),
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}));

import LoginPage from "../page";

function makeInstall(overrides: Partial<InstallSummary> = {}): InstallSummary {
  return {
    installId: "install-1",
    tenantSlug: "baseworm",
    tenantDisplayName: "Baseworm",
    companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
    platform: "slack",
    installerPersonId: "person-1",
    installerName: "Carol Installer",
    installerEmail: "carol@baseworm.example",
    installedAt: "2026-04-25T12:00:00.000Z",
    lastActivityAt: "2026-04-27T18:30:00.000Z",
    status: "active",
    scopes: ["chat:write", "channels:history"],
    receipt: {
      hash: "deadbeef0000",
      source: "install-projection",
      owner: "person-1",
      classification: "internal",
    },
    ...overrides,
  };
}

async function renderLogin() {
  const ui = await LoginPage();
  return render(ui);
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockGetAllInstalls.mockReset();
  });

  it("renders an honest empty state when no installs exist", async () => {
    mockGetAllInstalls.mockResolvedValue([]);
    await renderLogin();
    expect(screen.getByTestId("login-tenant-picker")).toBeInTheDocument();
    expect(screen.getByTestId("login-empty")).toBeInTheDocument();
    expect(screen.getByTestId("login-empty-cta")).toHaveAttribute(
      "href",
      "/onboarding",
    );
    // No tenant cards.
    expect(screen.queryByTestId("login-tenant-list")).toBeNull();
  });

  it("renders one card per tenant carrying installs", async () => {
    mockGetAllInstalls.mockResolvedValue([
      makeInstall({
        tenantSlug: "baseworm",
        tenantDisplayName: "Baseworm",
        installerEmail: "carol@baseworm.example",
        platform: "slack",
        lastActivityAt: "2026-04-27T18:30:00.000Z",
      }),
      makeInstall({
        installId: "install-2",
        tenantSlug: "democorp",
        tenantDisplayName: "Democorp",
        installerEmail: "dana@democorp.example",
        platform: "slack",
        installerPersonId: "person-2",
        lastActivityAt: "2026-04-26T09:15:00.000Z",
      }),
    ]);
    await renderLogin();
    expect(screen.getByTestId("login-tenant-list")).toBeInTheDocument();
    const baseworm = screen.getByTestId("login-tenant-baseworm");
    const democorp = screen.getByTestId("login-tenant-democorp");
    expect(baseworm).toBeInTheDocument();
    expect(democorp).toBeInTheDocument();
    // Most-recent activity on top: baseworm → democorp. Use direct
    // children of the outer list to avoid matching the per-install
    // nested <li> rows inside each button.
    const list = screen.getByTestId("login-tenant-list");
    const directChildren = Array.from(list.children).filter(
      (el) => el.tagName === "LI",
    ) as HTMLElement[];
    expect(directChildren.length).toBe(2);
    expect(
      directChildren[0].querySelector('[data-tenant-slug="baseworm"]'),
    ).not.toBeNull();
    expect(
      directChildren[1].querySelector('[data-tenant-slug="democorp"]'),
    ).not.toBeNull();
  });

  it("each card carries the installer email and platform", async () => {
    mockGetAllInstalls.mockResolvedValue([
      makeInstall({
        installId: "install-x",
        platform: "slack",
        installerEmail: "carol@baseworm.example",
      }),
    ]);
    await renderLogin();
    const platform = screen.getByTestId("login-install-install-x-platform");
    const installer = screen.getByTestId(
      "login-install-install-x-installer",
    );
    expect(platform.textContent).toBe("slack");
    expect(installer.textContent).toContain("carol@baseworm.example");
  });

  it("falls back to installer name when email is missing", async () => {
    mockGetAllInstalls.mockResolvedValue([
      makeInstall({
        installId: "install-y",
        installerEmail: null,
        installerName: "Carol Installer",
      }),
    ]);
    await renderLogin();
    const installer = screen.getByTestId(
      "login-install-install-y-installer",
    );
    expect(installer.textContent).toContain("Carol Installer");
  });

  it("each card submits to a server-action form keyed by slug", async () => {
    mockGetAllInstalls.mockResolvedValue([makeInstall({ tenantSlug: "baseworm" })]);
    await renderLogin();
    const form = screen.getByTestId("login-tenant-form-baseworm");
    expect(form.tagName).toBe("FORM");
    const hidden = form.querySelector('input[name="slug"]');
    expect(hidden?.getAttribute("value")).toBe("baseworm");
    const button = screen.getByTestId("login-tenant-baseworm");
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("type")).toBe("submit");
  });

  it("renders an email magic-link form (Phase 4C)", async () => {
    mockGetAllInstalls.mockResolvedValue([]);
    await renderLogin();
    expect(screen.getByTestId("login-magic-link-form")).toBeInTheDocument();
    const input = screen.getByTestId(
      "login-magic-link-input",
    ) as HTMLInputElement;
    expect(input.getAttribute("type")).toBe("email");
    expect(input.required).toBe(true);
    expect(screen.getByTestId("login-magic-link-submit")).toBeInTheDocument();
  });

  it("renders a Slack-OAuth start button (Phase 4C)", async () => {
    mockGetAllInstalls.mockResolvedValue([]);
    await renderLogin();
    const slack = screen.getByTestId("login-slack-start");
    expect(slack).toHaveAttribute("href", "/api/auth/slack/start");
  });
});
