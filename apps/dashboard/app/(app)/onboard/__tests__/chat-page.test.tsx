/**
 * /onboard/chat — page test (Onboarding Sub-wave B, 2026-05-30).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/onboard", () => ({
  getOnboardChat: vi.fn(async () => ({
    rows: [
      {
        platform: "slack",
        label: "Slack",
        status: "production" as const,
        statusNote: "Real OAuth, ingest, send.",
        capabilities: ["ingest", "send"],
        envHint: "SLACK_CLIENT_ID + SLACK_CLIENT_SECRET",
        connected: true,
        installCount: 1,
      },
      {
        platform: "discord",
        label: "Discord",
        status: "preview" as const,
        statusNote: "Install + listen real.",
        capabilities: [],
        envHint: "DISCORD_CLIENT_ID + DISCORD_CLIENT_SECRET",
        connected: false,
        installCount: 0,
      },
      {
        platform: "signal",
        label: "Signal",
        status: "coming_soon" as const,
        statusNote: "Coming soon.",
        capabilities: [],
        envHint: null,
        connected: false,
        installCount: 0,
      },
    ],
    installs: [],
  })),
}));

import OnboardChatPage from "../chat/page";

describe("/onboard/chat page", () => {
  it("renders a row per channel adapter", async () => {
    const ui = await OnboardChatPage();
    render(ui);
    expect(screen.getByTestId("onboard-chat-row-slack")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-chat-row-discord")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-chat-row-signal")).toBeInTheDocument();
  });

  it("shows the Add affordance only for non-coming_soon rows", async () => {
    const ui = await OnboardChatPage();
    render(ui);
    expect(screen.getByTestId("onboard-chat-connect-slack")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-chat-connect-discord")).toBeInTheDocument();
    expect(screen.queryByTestId("onboard-chat-connect-signal")).toBeNull();
  });

  it("renders production status accent for slack via CapabilityBadges", async () => {
    const ui = await OnboardChatPage();
    render(ui);
    expect(
      screen.getByTestId("capability-status-channel-slack-production"),
    ).toBeInTheDocument();
  });
});
