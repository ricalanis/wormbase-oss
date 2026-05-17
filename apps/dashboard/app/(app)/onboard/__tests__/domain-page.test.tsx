/**
 * /onboard/domain — page test
 * (Onboarding Sub-wave B initial, graduated by Sub-wave C 2026-05-30).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/onboard", () => ({
  getOnboardDomain: vi.fn(async () => ({
    packs: [],
    domains: [],
    packsAvailable: false,
  })),
}));

// Mock the server action — the picker imports it but the test
// renders the component statically without clicking through.
vi.mock("../domain/actions", () => ({
  selectDomainPackAction: vi.fn(async () => ({ ok: true })),
}));

import OnboardDomainPage from "../domain/page";

describe("/onboard/domain page", () => {
  it("renders the unavailable empty state when packsAvailable is false", async () => {
    const ui = await OnboardDomainPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-domain-packs-empty"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-existing-empty"),
    ).toBeInTheDocument();
  });

  it("renders the pack picker when packs are available", async () => {
    const lo = await import("../../../../lib/onboard");
    vi.mocked(lo.getOnboardDomain).mockResolvedValueOnce({
      packs: [
        {
          packId: "generic",
          packVersion: "v1.0",
          label: "Generic Org",
          description: "Minimal baseline.",
          domainCount: 1,
        },
        {
          packId: "saas",
          packVersion: "v1.0",
          label: "SaaS",
          description: "B2B SaaS shape.",
          domainCount: 4,
        },
      ],
      domains: [],
      packsAvailable: true,
    });
    const ui = await OnboardDomainPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-domain-pack-picker"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-pack-generic"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-pack-saas"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-pack-pick-generic"),
    ).toBeInTheDocument();
  });

  it("renders a list when domains exist", async () => {
    const lo = await import("../../../../lib/onboard");
    vi.mocked(lo.getOnboardDomain).mockResolvedValueOnce({
      packs: [],
      domains: [
        {
          domainId: "d1",
          name: "Sales",
          owner: "owner-uuid",
          classificationDefault: "internal" as const,
          resourceCount: 0,
          receipt: { hash: "", source: "", owner: "", classification: "internal" },
        },
      ],
      packsAvailable: false,
    });
    const ui = await OnboardDomainPage();
    render(ui);
    expect(screen.getByTestId("onboard-domain-row-d1")).toBeInTheDocument();
  });
});
