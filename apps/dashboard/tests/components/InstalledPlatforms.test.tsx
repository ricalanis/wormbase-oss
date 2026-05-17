/**
 * D3 — InstalledPlatforms.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { InstalledPlatforms } from "../../components/channels/InstalledPlatforms";
import type { InstallRow } from "../../lib/ledger-client.types";

function install(over: Partial<InstallRow> = {}): InstallRow {
  return {
    installId: "i1",
    platform: "slack",
    installerPersonId: "p1",
    installerName: "Carol Reyes",
    installedAt: "2026-04-26T18:00:00Z",
    status: "active",
    scopes: ["chat:write", "files:read"],
    botUserId: "U-bot",
    oauthGrantRef: "dev://baseworm/slack/abc",
    setupMode: null,
    setupCompletedAt: null,
    receipt: {
      hash: "deadbeef0000",
      source: "install-projection",
      owner: "p1",
      classification: "internal",
    },
    ...over,
  };
}

describe("InstalledPlatforms", () => {
  it("renders one card per install", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({ installId: "i1", platform: "slack" }),
          install({ installId: "i2", platform: "discord" }),
        ]}
      />,
    );
    expect(screen.getByTestId("platform-card-slack")).toBeInTheDocument();
    expect(screen.getByTestId("platform-card-discord")).toBeInTheDocument();
    expect(screen.getByText("slack")).toBeInTheDocument();
    expect(screen.getByText("discord")).toBeInTheDocument();
  });

  it("renders the installer name when present", () => {
    render(<InstalledPlatforms installs={[install()]} />);
    expect(screen.getByText("Carol Reyes")).toBeInTheDocument();
  });

  it("renders the status badge", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({ installId: "i1", platform: "slack", status: "active" }),
          install({
            installId: "i2",
            platform: "teams",
            status: "revoked",
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("platform-status-slack").textContent).toBe(
      "active",
    );
    expect(screen.getByTestId("platform-status-teams").textContent).toBe(
      "revoked",
    );
    expect(
      screen.getByTestId("platform-card-teams").getAttribute("data-status"),
    ).toBe("revoked");
  });

  it("renders the empty-state placeholder when there are no installs", () => {
    render(<InstalledPlatforms installs={[]} />);
    expect(
      screen.getByTestId("installed-platforms-empty"),
    ).toBeInTheDocument();
  });

  it("renders scopes when present", () => {
    render(
      <InstalledPlatforms
        installs={[install({ scopes: ["chat:write", "files:read"] })]}
      />,
    );
    expect(screen.getByText(/chat:write, files:read/)).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Capability-honesty: preview installs surface a banner; cards mark
  // their capability status so users know what works and what doesn't.
  // ------------------------------------------------------------------

  it("renders no banner section when only production platforms are installed", () => {
    render(
      <InstalledPlatforms installs={[install({ platform: "slack" })]} />,
    );
    expect(
      screen.queryByTestId("installed-platforms-honesty-banners"),
    ).toBeNull();
  });

  it("surfaces a 'preview' banner for Discord installs", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({ installId: "i1", platform: "slack" }),
          install({ installId: "i2", platform: "discord" }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("installed-platforms-banner-preview"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("installed-platforms-banner-preview").textContent,
    ).toMatch(/preview/i);
  });

  it("preview platform cards render a 'preview' capability pill", () => {
    render(
      <InstalledPlatforms
        installs={[install({ installId: "i2", platform: "discord" })]}
      />,
    );
    const card = screen.getByTestId("platform-card-discord");
    expect(card.getAttribute("data-capability-status")).toBe("preview");
    expect(
      screen.getByTestId("platform-capability-pill-discord").textContent,
    ).toMatch(/preview/i);
  });

  it("production platform cards do not render a capability pill", () => {
    render(
      <InstalledPlatforms
        installs={[install({ platform: "slack" })]}
      />,
    );
    expect(
      screen.queryByTestId("platform-capability-pill-slack"),
    ).toBeNull();
  });

  // ------------------------------------------------------------------
  // Phase D1 (2026-05-06) — WhatsApp install rendering: pairing-status
  // vocabulary + Baileys ToS hover via the descriptor's statusNote.
  // ------------------------------------------------------------------

  it("WhatsApp install renders with paired pairing-status when active", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({
            installId: "i-wa",
            platform: "whatsapp",
            pairingStatus: "paired",
          }),
        ]}
      />,
    );
    const card = screen.getByTestId("platform-card-whatsapp");
    expect(card.getAttribute("data-pairing-status")).toBe("paired");
    expect(
      screen.getByTestId("platform-pairing-whatsapp").textContent,
    ).toBe("paired");
    // Capability badge surfaces as preview (per platform-status.ts).
    expect(card.getAttribute("data-capability-status")).toBe("preview");
    expect(
      screen.getByTestId("platform-capability-pill-whatsapp").textContent,
    ).toMatch(/preview/i);
  });

  it("WhatsApp install renders with expired pairing-status when revoked", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({
            installId: "i-wa",
            platform: "whatsapp",
            status: "revoked",
            pairingStatus: "expired",
          }),
        ]}
      />,
    );
    const card = screen.getByTestId("platform-card-whatsapp");
    expect(card.getAttribute("data-pairing-status")).toBe("expired");
    expect(
      screen.getByTestId("platform-pairing-whatsapp").textContent,
    ).toBe("expired");
  });

  it("WhatsApp capability pill exposes the Baileys ToS caveat via title hover", () => {
    render(
      <InstalledPlatforms
        installs={[install({ platform: "whatsapp", pairingStatus: "paired" })]}
      />,
    );
    const pill = screen.getByTestId("platform-capability-pill-whatsapp");
    expect(pill.getAttribute("title")).toMatch(/Baileys/i);
    expect(pill.getAttribute("title")).toMatch(/ToS|test number/i);
  });

  it("WhatsApp section banner surfaces a 'preview' notice when WA is installed", () => {
    render(
      <InstalledPlatforms
        installs={[install({ platform: "whatsapp", pairingStatus: "paired" })]}
      />,
    );
    expect(
      screen.getByTestId("installed-platforms-banner-preview"),
    ).toBeInTheDocument();
  });

  it("WhatsApp install defaults pairingStatus to paired when projection omits it", () => {
    render(
      <InstalledPlatforms
        installs={[
          install({
            platform: "whatsapp",
            // pairingStatus undefined: render-side default kicks in.
            pairingStatus: undefined,
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("platform-card-whatsapp").getAttribute(
        "data-pairing-status",
      ),
    ).toBe("paired");
  });

  // ------------------------------------------------------------------
  // W3-A (2026-05-07) — capability chips cascade. Render small chips
  // for descriptor.capabilities; omit when the descriptor omits them.
  // Slack/Discord/Teams/Signal byte-identical until they opt in.
  // ------------------------------------------------------------------

  it("WhatsApp install renders ingest/dm/send capability chips from the descriptor", () => {
    render(
      <InstalledPlatforms
        installs={[install({ platform: "whatsapp", pairingStatus: "paired" })]}
      />,
    );
    const strip = screen.getByTestId("platform-capability-chips-whatsapp");
    expect(strip).toBeInTheDocument();
    for (const cap of ["ingest", "dm", "send"]) {
      const chip = screen.getByTestId(
        `platform-capability-chip-whatsapp-${cap}`,
      );
      expect(chip.textContent?.toLowerCase()).toBe(cap);
      expect(chip.getAttribute("data-capability")).toBe(cap);
    }
  });

  it("WhatsApp send chip surfaces the operator-write-scope gate via title hover", () => {
    render(
      <InstalledPlatforms
        installs={[install({ platform: "whatsapp", pairingStatus: "paired" })]}
      />,
    );
    const sendChip = screen.getByTestId(
      "platform-capability-chip-whatsapp-send",
    );
    expect(sendChip.getAttribute("title")).toMatch(/CLI subprocess/i);
    expect(sendChip.getAttribute("title")).toMatch(/write-scope/i);
  });

  it("Slack install does not render a capability strip (descriptor omits capabilities)", () => {
    render(
      <InstalledPlatforms installs={[install({ platform: "slack" })]} />,
    );
    expect(
      screen.queryByTestId("platform-capability-chips-slack"),
    ).toBeNull();
  });

  it("Discord install does not render a capability strip (descriptor omits capabilities)", () => {
    render(
      <InstalledPlatforms
        installs={[install({ installId: "i2", platform: "discord" })]}
      />,
    );
    expect(
      screen.queryByTestId("platform-capability-chips-discord"),
    ).toBeNull();
  });
});
