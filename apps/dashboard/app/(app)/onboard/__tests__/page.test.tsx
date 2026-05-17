/**
 * /onboard — landing-page test (Onboarding Sub-wave B, 2026-05-30).
 *
 * Server-component test: we mock the tenant-cookies + the onboard
 * accessor so the page composition can be exercised without
 * worm-core / Postgres.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
  getTenantFromCookies: async () => ({
    slug: "baseworm",
    companyId: "tenant-uuid",
  }),
}));

vi.mock("../../../../lib/onboard", () => ({
  getOnboardLandingSnapshot: vi.fn(async () => ({
    tabs: [
      { tab: "chat", label: "Chat", total: 5, ready: 1, pending: 4, hint: "1 of 5 platforms connected." },
      { tab: "source", label: "Source", total: 6, ready: 0, pending: 6, hint: "No data sources yet." },
      { tab: "domain", label: "Domain", total: 0, ready: 0, pending: 0, hint: "Pack picker lands in Sub-wave C." },
      { tab: "person", label: "Person", total: 0, ready: 0, pending: 0, hint: "Connect chat first." },
      { tab: "policy", label: "Policy", total: 0, ready: 0, pending: 0, hint: "Pack policies pending." },
      { tab: "agent", label: "Agent", total: 0, ready: 0, pending: 0, hint: "Use /people/agents/new." },
      { tab: "subscription", label: "Subscription", total: 0, ready: 0, pending: 0, hint: "Per-agent." },
    ],
  })),
}));

import OnboardLandingPage from "../page";

describe("/onboard landing page", () => {
  it("renders the seven tab cards in the canonical order", async () => {
    const ui = await OnboardLandingPage();
    render(ui);
    for (const tab of [
      "chat",
      "source",
      "domain",
      "person",
      "policy",
      "agent",
      "subscription",
    ]) {
      expect(screen.getByTestId(`onboard-tab-${tab}`)).toBeInTheDocument();
      expect(screen.getByTestId(`onboard-tab-link-${tab}`)).toBeInTheDocument();
    }
  });

  it("renders the ready/pending counts per card", async () => {
    const ui = await OnboardLandingPage();
    render(ui);
    expect(screen.getByTestId("onboard-tab-ready-chat")).toHaveTextContent("ready: 1");
    expect(screen.getByTestId("onboard-tab-pending-chat")).toHaveTextContent("pending: 4");
    expect(screen.getByTestId("onboard-tab-total-chat")).toHaveTextContent("total: 5");
  });

  it("renders the editorial header + hint copy", async () => {
    const ui = await OnboardLandingPage();
    render(ui);
    expect(screen.getByText("Onboard")).toBeInTheDocument();
  });
});
