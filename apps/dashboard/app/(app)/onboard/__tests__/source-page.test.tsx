/**
 * /onboard/source — page test (Onboarding Sub-wave B, 2026-05-30).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/onboard", () => ({
  getOnboardSource: vi.fn(async () => ({
    catalog: {
      production: [
        {
          kind: "stripe",
          label: "Stripe",
          description: "Stripe payments source",
          status: "production" as const,
          statusNote: "",
          capabilities: ["discover", "profile"],
          connectionState: "connected" as const,
          activeSourceCount: 1,
        },
      ],
      preview: [],
      comingSoon: [
        {
          kind: "salesforce",
          label: "Salesforce",
          description: "",
          status: "coming_soon" as const,
          statusNote: "",
          capabilities: [],
          connectionState: "disconnected" as const,
          activeSourceCount: 0,
        },
      ],
      registryUnreachable: false,
      registryError: null,
      upstreamUrl: "",
    },
    sources: [{ sourceId: "src-1", uri: "stripe://...", kind: "stripe" }],
  })),
}));

import OnboardSourcePage from "../source/page";

describe("/onboard/source page", () => {
  it("renders production + coming_soon rows from the catalog", async () => {
    const ui = await OnboardSourcePage();
    render(ui);
    expect(screen.getByTestId("onboard-source-row-stripe")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-source-row-salesforce")).toBeInTheDocument();
  });

  it("muting coming_soon rows: no Add link for salesforce, link for stripe", async () => {
    const ui = await OnboardSourcePage();
    render(ui);
    expect(screen.getByTestId("onboard-source-add-stripe")).toBeInTheDocument();
    expect(screen.queryByTestId("onboard-source-add-salesforce")).toBeNull();
  });
});
