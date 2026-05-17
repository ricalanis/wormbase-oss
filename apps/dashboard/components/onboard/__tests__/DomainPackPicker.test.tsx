/**
 * DomainPackPicker component tests — Onboarding Sub-wave C (2026-05-30).
 *
 * Pins the picker's surface contract: renders one card per pack with
 * a Pick button + status badge, and surfaces the action result
 * (success / already_seeded / error) into a per-card receipt strip.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../../app/(app)/onboard/domain/actions", () => ({
  selectDomainPackAction: vi.fn(),
}));

import { selectDomainPackAction } from "../../../app/(app)/onboard/domain/actions";
import { DomainPackPicker } from "../DomainPackPicker";

const mockedAction = vi.mocked(selectDomainPackAction);

const PACKS = [
  {
    packId: "generic",
    packVersion: "v1.0",
    label: "Generic Org",
    description: "Minimal pack.",
    domainCount: 1,
  },
  {
    packId: "saas",
    packVersion: "v1.0",
    label: "SaaS",
    description: "B2B SaaS shape.",
    domainCount: 4,
  },
];

describe("DomainPackPicker", () => {
  it("renders one card per pack with a Pick button", () => {
    render(<DomainPackPicker packs={PACKS} />);
    expect(screen.getByTestId("onboard-domain-pack-picker")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-domain-pack-generic")).toBeInTheDocument();
    expect(screen.getByTestId("onboard-domain-pack-saas")).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-pack-pick-generic"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-domain-pack-pick-saas"),
    ).toBeInTheDocument();
  });

  it("surfaces success receipt after successful pick", async () => {
    mockedAction.mockResolvedValueOnce({
      ok: true,
      packId: "generic",
      packVersion: "v1.0",
      alreadySeeded: false,
      domainIds: ["d1"],
      policyIds: ["p1"],
    });
    render(<DomainPackPicker packs={PACKS} />);
    fireEvent.click(screen.getByTestId("onboard-domain-pack-pick-generic"));
    await waitFor(() => {
      expect(
        screen.getByTestId("onboard-domain-pack-receipt-generic"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("onboard-domain-pack-receipt-generic"),
    ).toHaveTextContent("Seeded 1 domain · 1 policy");
  });

  it("surfaces already-seeded receipt when alreadySeeded=true", async () => {
    mockedAction.mockResolvedValueOnce({
      ok: true,
      packId: "generic",
      packVersion: "v1.0",
      alreadySeeded: true,
      domainIds: [],
      policyIds: [],
    });
    render(<DomainPackPicker packs={PACKS} />);
    fireEvent.click(screen.getByTestId("onboard-domain-pack-pick-generic"));
    await waitFor(() => {
      expect(
        screen.getByTestId("onboard-domain-pack-receipt-generic"),
      ).toHaveTextContent("Already seeded");
    });
  });

  it("surfaces error when action fails", async () => {
    mockedAction.mockResolvedValueOnce({
      ok: false,
      error: "tenant has no admin Person",
    });
    render(<DomainPackPicker packs={PACKS} />);
    fireEvent.click(screen.getByTestId("onboard-domain-pack-pick-generic"));
    await waitFor(() => {
      expect(
        screen.getByTestId("onboard-domain-pack-error-generic"),
      ).toHaveTextContent("tenant has no admin Person");
    });
  });
});
