/**
 * /onboard/{person,policy,agent,subscription} — page tests
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Compressed test surface for the lower-traffic tabs. Each tab gets
 * one focused render test that asserts the canonical testid and copy.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/onboard", () => ({
  getOnboardPerson: vi.fn(async () => ({
    people: [
      {
        personId: "p1",
        displayName: "Alice",
        email: null,
        position: "Founder",
        status: "active",
        tenancyRole: "admin",
        identities: [{ platform: "slack", platformUserId: "U1" }],
        domainGrantCount: 0,
        resourceGrantCount: 0,
        roles: ["admin"],
        ownedDomains: [],
        ownedResources: [],
        receipt: { hash: "", source: "", owner: "", classification: "internal" },
      },
    ],
    proposedCount: 0,
    confirmedCount: 1,
  })),
  getOnboardPolicy: vi.fn(async () => ({
    policies: [
      {
        policyId: "policy:retention",
        name: "Retention",
        plainLanguage: "Retain forever.",
        gateImpl: "",
        scope: "global",
        firesLast7d: 2,
        receipt: { hash: "", source: "", owner: "", classification: "internal" },
      },
    ],
    firedRecently: 1,
  })),
}));

// Sub-wave C — invite form lives on /onboard/person; mock the action.
vi.mock("../person/actions", () => ({
  invitePersonAction: vi.fn(async () => ({
    ok: true,
    inviteeEmail: "x@example.com",
    inviteePlatformId: null,
    roleIntent: "member",
  })),
}));

import OnboardPersonPage from "../person/page";
import OnboardPolicyPage from "../policy/page";
import OnboardAgentPage from "../agent/page";
import OnboardSubscriptionPage from "../subscription/page";

describe("/onboard/person page", () => {
  it("renders a Person row with the works accent", async () => {
    const ui = await OnboardPersonPage();
    render(ui);
    expect(screen.getByTestId("onboard-person-row-p1")).toBeInTheDocument();
    expect(
      screen.getByTestId("capability-status-person-p1-works"),
    ).toBeInTheDocument();
  });

  it("renders the co-admin invite form (Sub-wave C graduation)", async () => {
    const ui = await OnboardPersonPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-person-invite-form"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-email"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-submit"),
    ).toBeInTheDocument();
  });
});

describe("/onboard/policy page", () => {
  it("renders a Policy row with the works accent (fired recently)", async () => {
    const ui = await OnboardPolicyPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-policy-row-policy:retention"),
    ).toBeInTheDocument();
  });
});

describe("/onboard/agent page", () => {
  it("renders the navigation panel deep-linking to /people/agents/new", async () => {
    const ui = OnboardAgentPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-agent-navigation-panel"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-agent-register-link"),
    ).toHaveAttribute("href", "/people/agents/new");
  });
});

describe("/onboard/subscription page", () => {
  it("renders the navigation panel deep-linking to /people/agents", async () => {
    const ui = OnboardSubscriptionPage();
    render(ui);
    expect(
      screen.getByTestId("onboard-subscription-navigation-panel"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-subscription-agents-link"),
    ).toHaveAttribute("href", "/people/agents");
  });
});
