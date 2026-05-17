/**
 * /reactivities — page-level tests (W5.A5).
 *
 * Server-component test: we mock the ledger-client accessor + tenant
 * cookies so we can exercise the page composition without standing up
 * worm-core.
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

vi.mock("../../../../lib/ledger-client", () => ({
  getReactivities: vi.fn(async () => []),
}));

import ReactivitiesPage from "../page";

describe("/reactivities page", () => {
  it("renders the editorial header", async () => {
    const ui = await ReactivitiesPage();
    render(ui);
    expect(screen.getByText("Reactivities")).toBeInTheDocument();
  });

  it("renders the empty state when no reactivities are registered", async () => {
    const ui = await ReactivitiesPage();
    render(ui);
    expect(screen.getByTestId("reactivities-empty")).toBeInTheDocument();
  });

  it("renders the active section + Propose CTA when at least one reactivity is registered", async () => {
    const lc = await import("../../../../lib/ledger-client");
    vi.mocked(lc.getReactivities).mockResolvedValueOnce([
      {
        id: "statement_to_owner",
        name: "Statement to Owner",
        description: "DM the owner.",
        scope: "company",
        state: "active",
        proposedBy: null,
        confirmedBy: null,
        disabledBy: null,
        disableReason: null,
        lastFiredAt: "2026-04-28T10:00:00.000Z",
        predicateSpec: {},
        conditionSpec: {},
        actionSpec: {},
      },
    ]);
    const ui = await ReactivitiesPage();
    render(ui);
    expect(screen.getByTestId("reactivities-view")).toBeInTheDocument();
    expect(screen.getByTestId("reactivities-active")).toBeInTheDocument();
    expect(screen.getByTestId("reactivities-propose-cta")).toBeInTheDocument();
    expect(
      screen.getByTestId("reactivity-card-statement_to_owner"),
    ).toBeInTheDocument();
  });

  it("renders the proposed section when a proposed reactivity exists", async () => {
    const lc = await import("../../../../lib/ledger-client");
    vi.mocked(lc.getReactivities).mockResolvedValueOnce([
      {
        id: "prop_xyz",
        name: "Proposed",
        description: "",
        scope: "person",
        state: "proposed",
        proposedBy: "p-admin",
        confirmedBy: null,
        disabledBy: null,
        disableReason: null,
        lastFiredAt: null,
        predicateSpec: {},
        conditionSpec: {},
        actionSpec: {},
      },
    ]);
    const ui = await ReactivitiesPage();
    render(ui);
    expect(screen.getByTestId("reactivities-proposed")).toBeInTheDocument();
    expect(
      screen.getByTestId("reactivity-card-prop_xyz"),
    ).toBeInTheDocument();
  });

  it("hides the disabled section by default and renders the Show toggle", async () => {
    const lc = await import("../../../../lib/ledger-client");
    vi.mocked(lc.getReactivities).mockResolvedValueOnce([
      {
        id: "stale",
        name: "Stale",
        description: "",
        scope: "company",
        state: "disabled",
        proposedBy: null,
        confirmedBy: null,
        disabledBy: null,
        disableReason: "noisy",
        lastFiredAt: null,
        predicateSpec: {},
        conditionSpec: {},
        actionSpec: {},
      },
    ]);
    const ui = await ReactivitiesPage();
    render(ui);
    expect(
      screen.getByTestId("reactivities-show-disabled-toggle"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("reactivities-disabled"),
    ).not.toBeInTheDocument();
  });

  it("active section sorts by lastFiredAt desc", async () => {
    const lc = await import("../../../../lib/ledger-client");
    vi.mocked(lc.getReactivities).mockResolvedValueOnce([
      {
        id: "a_old",
        name: "Old",
        description: "",
        scope: "person",
        state: "active",
        proposedBy: null,
        confirmedBy: null,
        disabledBy: null,
        disableReason: null,
        lastFiredAt: "2026-04-26T10:00:00.000Z",
        predicateSpec: {},
        conditionSpec: {},
        actionSpec: {},
      },
      {
        id: "z_new",
        name: "New",
        description: "",
        scope: "person",
        state: "active",
        proposedBy: null,
        confirmedBy: null,
        disabledBy: null,
        disableReason: null,
        lastFiredAt: "2026-04-28T10:00:00.000Z",
        predicateSpec: {},
        conditionSpec: {},
        actionSpec: {},
      },
    ]);
    const ui = await ReactivitiesPage();
    render(ui);
    const section = screen.getByTestId("reactivities-active");
    const cards = section.querySelectorAll("[data-testid^='reactivity-card-']");
    expect(cards[0].getAttribute("data-testid")).toBe(
      "reactivity-card-z_new",
    );
    expect(cards[1].getAttribute("data-testid")).toBe(
      "reactivity-card-a_old",
    );
  });
});
