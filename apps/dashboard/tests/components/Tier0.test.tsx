/**
 * Block I3 — Tier 0 simplification.
 *
 * After Block I, /onboarding renders only the chat-platform connect
 * buttons (and a sign-in link). The connector grid is gone — external
 * data sources land via /sources/new or via worm conversation. Tests
 * verify the surface contract:
 *
 *   - production + preview platform buttons render
 *   - no connector grid (no `connector-first-card-*` testIds)
 *   - sign-in escape hatch is present
 *   - error/hint query-param surface still shows when set
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { Tier0 } from "../../components/onboarding/Tier0";

const searchParams = new Map<string, string | null>();
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (k: string) => searchParams.get(k) ?? null,
  }),
}));

describe("Tier0 (Block I3)", () => {
  it("renders the chat-platform buttons (production + preview)", () => {
    render(<Tier0 />);
    expect(screen.getByTestId("tier0-connect-slack")).toBeInTheDocument();
    expect(screen.getByTestId("tier0-connect-discord")).toBeInTheDocument();
    expect(screen.getByTestId("tier0-connect-teams")).toBeInTheDocument();
  });

  it("marks the production platform with a botanical-green primary", () => {
    render(<Tier0 />);
    const slack = screen.getByTestId("tier0-connect-slack");
    expect(slack.getAttribute("data-platform-status")).toBe("production");
    expect(slack.getAttribute("href")).toBe("/onboarding/oauth/slack/start");
  });

  it("marks preview platforms with a preview badge", () => {
    render(<Tier0 />);
    expect(
      screen.getByTestId("tier0-discord-preview-badge"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("tier0-teams-preview-badge"),
    ).toBeInTheDocument();
  });

  it("does NOT render the connector grid (Block I3 retirement)", () => {
    render(<Tier0 />);
    // Connector grid testIds: connector-first-card-* and the section
    // wrapper onboarding-tier0-connector-first.
    expect(
      screen.queryByTestId("onboarding-tier0-connector-first"),
    ).toBeNull();
    // None of the catalog connectors should appear at this surface.
    expect(screen.queryByTestId("connector-first-card-postgres")).toBeNull();
    expect(screen.queryByTestId("connector-first-card-stripe")).toBeNull();
    expect(screen.queryByTestId("connector-first-card-csv_local")).toBeNull();
  });

  it("does NOT render the IdentityForm (post-install path)", () => {
    render(<Tier0 />);
    // IdentityForm has data-testid="onboarding-identity-form"; absent here.
    expect(
      screen.queryByTestId("onboarding-identity-form"),
    ).toBeNull();
  });

  it("renders an 'already installed? sign in' link", () => {
    render(<Tier0 />);
    expect(screen.getByTestId("tier0-sign-in")).toBeInTheDocument();
  });

  it("sign-in link points at /login (W1.A3 — no longer a 404)", () => {
    render(<Tier0 />);
    const link = screen.getByTestId("tier0-sign-in");
    expect(link.getAttribute("href")).toBe("/login");
  });

  it("does not render coming_soon platforms (filtered out)", () => {
    render(<Tier0 />);
    // Signal remains coming_soon; WhatsApp graduated to preview on
    // 2026-05-06 (Phase D1) so it now renders alongside Discord/Teams.
    expect(screen.queryByTestId("tier0-connect-signal")).toBeNull();
  });

  it("renders preview platforms (Discord, Teams, WhatsApp) with a preview badge", () => {
    render(<Tier0 />);
    expect(screen.getByTestId("tier0-connect-whatsapp")).toBeInTheDocument();
    expect(
      screen.getByTestId("tier0-whatsapp-preview-badge").textContent,
    ).toMatch(/preview/i);
  });

  it("surfaces an error banner when query string carries error+hint", () => {
    searchParams.set("error", "platform_not_configured");
    searchParams.set(
      "hint",
      "Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET in the env.",
    );
    render(<Tier0 />);
    const banner = screen.getByTestId("tier0-error");
    expect(banner.textContent).toContain("platform_not_configured");
    expect(banner.textContent).toContain("SLACK_CLIENT_ID");
    searchParams.clear();
  });
});
