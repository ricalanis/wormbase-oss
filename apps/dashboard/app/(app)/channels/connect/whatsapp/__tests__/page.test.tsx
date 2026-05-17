/**
 * Phase W2-C (2026-05-07) — /channels/connect/whatsapp page.
 *
 * The page is admin-only and reads the ledger to decide whether to
 * render the pairing steps or the post-pair success card. Tests mock
 * tenant-cookies + identity + ledger so the server component exercises
 * its composition without standing up Postgres.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../../../lib/tenant-cookies", () => ({
  getTenantFromCookies: async () => ({
    slug: "baseworm",
    companyId: "tenant-uuid",
  }),
}));

vi.mock("../../../../../../lib/server/identity", () => ({
  getCurrentPerson: vi.fn(async () => ({
    personId: "p1",
    name: "Admin Adelaide",
    position: "ops",
    tenancyRole: "admin",
  })),
}));

vi.mock("../../../../../../lib/ledger-client", () => ({
  getInstalls: vi.fn(async () => []),
}));

// Mock next/navigation so the client component's useRouter doesn't crash
// during render. The pairing-flow tests cover the refresh interaction; this
// page test only asserts composition + role gating.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn(),
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

import ConnectWhatsAppPage from "../page";

describe("/channels/connect/whatsapp page", () => {
  it("renders the pairing flow with header + back link for an admin viewer", async () => {
    const ui = await ConnectWhatsAppPage();
    render(ui);
    expect(
      screen.getByTestId("connect-whatsapp-back-to-channels"),
    ).toHaveAttribute("href", "/channels");
    expect(screen.getByTestId("whatsapp-pairing-flow")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-step-3")).toBeInTheDocument();
  });

  it("links to the operator runbook in the page footer", async () => {
    const ui = await ConnectWhatsAppPage();
    render(ui);
    const link = screen.getByTestId("connect-whatsapp-runbook-link");
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/wormbase/wormbase/blob/main/infra/openclaw/WHATSAPP_PAIRING.md",
    );
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders the paired-success state when an active WhatsApp install row exists", async () => {
    const lc = await import("../../../../../../lib/ledger-client");
    vi.mocked(lc.getInstalls).mockResolvedValueOnce([
      {
        installId: "i1",
        tenantId: "tenant-uuid",
        platform: "whatsapp",
        installerPersonId: "p1",
        installedAt: "2026-05-07T10:00:00Z",
        status: "active",
        scopes: [],
        botUserId: "bot-jid",
      } as never,
    ]);
    const ui = await ConnectWhatsAppPage();
    render(ui);
    expect(screen.getByTestId("whatsapp-pairing-success")).toBeInTheDocument();
    // The pairing steps should NOT render when paired.
    expect(screen.queryByTestId("pairing-step-1")).toBeNull();
  });

  it("renders the admin-only empty state when the viewer is a member", async () => {
    const id = await import("../../../../../../lib/server/identity");
    vi.mocked(id.getCurrentPerson).mockResolvedValueOnce({
      personId: "p2",
      name: "Member Marcus",
      position: null,
      tenancyRole: "member",
    });
    const ui = await ConnectWhatsAppPage();
    render(ui);
    expect(
      screen.getByTestId("connect-whatsapp-not-admin"),
    ).toBeInTheDocument();
    // Neither the pairing flow nor the success card render for a non-admin.
    expect(screen.queryByTestId("whatsapp-pairing-flow")).toBeNull();
    expect(screen.queryByTestId("whatsapp-pairing-success")).toBeNull();
    // Empty state names the viewer's role honestly.
    expect(
      screen.getByTestId("connect-whatsapp-not-admin").textContent,
    ).toContain("member");
  });

  it("renders the admin-only empty state when no Person is resolved at all", async () => {
    const id = await import("../../../../../../lib/server/identity");
    vi.mocked(id.getCurrentPerson).mockResolvedValueOnce(null);
    const ui = await ConnectWhatsAppPage();
    render(ui);
    expect(
      screen.getByTestId("connect-whatsapp-not-admin"),
    ).toBeInTheDocument();
  });

  it("treats installer role as admin-equivalent for pairing", async () => {
    const id = await import("../../../../../../lib/server/identity");
    vi.mocked(id.getCurrentPerson).mockResolvedValueOnce({
      personId: "p3",
      name: "Installer Iris",
      position: null,
      tenancyRole: "installer",
    });
    const ui = await ConnectWhatsAppPage();
    render(ui);
    expect(screen.getByTestId("whatsapp-pairing-flow")).toBeInTheDocument();
  });
});
