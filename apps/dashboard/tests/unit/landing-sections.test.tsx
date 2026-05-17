/**
 * Phase 4 Task 4A — landing-page section components.
 *
 * The landing at `/` composes five sections beneath the existing hero
 * (which `tests/landing.spec.ts` continues to pin):
 *
 *   1. HeroDemo            — wire-replay viewer (Phase 4B replaced 4A's
 *                            placeholder; real ledger replay drives the
 *                            Slack-thread scaffold + receipt footer)
 *   2. ArchitectureDiagram — clickable 6-agent diagram with per-agent modal
 *   3. HowItWorks          — 5-beat product-arc walkthrough (CONNECT / GROW /
 *                            BUILD / PRODUCE / SELF-IMPROVE)
 *   4. Pricing             — three real tiers (Free / Pro Stripe / Enterprise)
 *   5. SignupCTA           — placeholder/disabled buttons (real wire-up in 4C)
 *
 * Each component renders in isolation against the Field Notebook design
 * tokens. The architecture diagram is the on-thesis pitch surface — every
 * named worm has a modal showing its responsibility + which Reactivities it
 * ships, sourced from the post-portfolio decomposition recorded in
 * `Projects/wormbase/CLAUDE.md` §1.5.
 */
import { describe, expect, it } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";

import { HeroDemo } from "../../components/landing/HeroDemo";
import {
  ArchitectureDiagram,
  AGENTS,
} from "../../components/landing/ArchitectureDiagram";
import { HowItWorks } from "../../components/landing/HowItWorks";
import { Pricing } from "../../components/landing/Pricing";
import { SignupCTA } from "../../components/landing/SignupCTA";

describe("HeroDemo (Phase 4B wire-replay viewer — server entry shape)", () => {
  // The component is now an async server component that fetches a
  // deterministic replay payload SSR-side and hands it to
  // HeroDemoClient. Rendering it directly under @testing-library is
  // not the intended unit test (the SSR fetch round-trips the helper);
  // HeroDemoClient.test.tsx covers the client behaviour. Here we only
  // assert that the module exports a callable component — keeping the
  // original test grouping intact for the suite report.
  it("exports a callable component (server entry)", () => {
    expect(typeof HeroDemo).toBe("function");
  });
});

describe("ArchitectureDiagram (clickable 6-agent pitch)", () => {
  it("exposes exactly six agents, one per named-actor worm", () => {
    expect(AGENTS).toHaveLength(6);
    const ids = AGENTS.map((a) => a.id).sort();
    expect(ids).toEqual([
      "chat",
      "governance",
      "identity",
      "lake",
      "process",
      "research",
    ]);
  });

  it("renders one node per agent, all clickable buttons", () => {
    render(<ArchitectureDiagram />);
    for (const agent of AGENTS) {
      const node = screen.getByTestId(`agent-node-${agent.id}`);
      expect(node).toBeInTheDocument();
      // Nodes are buttons so keyboard users can open the modal.
      expect(node.tagName.toLowerCase()).toBe("button");
    }
  });

  it("opens a modal with the agent's responsibilities + reactivities on click", () => {
    render(<ArchitectureDiagram />);
    const lake = screen.getByTestId("agent-node-lake");
    fireEvent.click(lake);
    const modal = screen.getByTestId("agent-modal");
    expect(modal).toBeInTheDocument();
    // Modal carries the agent's title in its dialog heading + an explicit
    // reactivities section. Title selector is role+name to avoid matching
    // the same word inside reactivity strings.
    expect(
      within(modal).getByRole("heading", { name: /lake maintainer/i }),
    ).toBeInTheDocument();
    expect(
      within(modal).getByTestId("agent-modal-reactivities"),
    ).toBeInTheDocument();
    // Each agent ships at least one reactivity in the diagram.
    const items = within(modal)
      .getByTestId("agent-modal-reactivities")
      .querySelectorAll("li");
    expect(items.length).toBeGreaterThanOrEqual(1);
  });

  it("modal closes when the close control is activated", () => {
    render(<ArchitectureDiagram />);
    fireEvent.click(screen.getByTestId("agent-node-research"));
    expect(screen.getByTestId("agent-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("agent-modal-close"));
    expect(screen.queryByTestId("agent-modal")).not.toBeInTheDocument();
  });

  it("clicking a different agent swaps the modal contents in place", () => {
    render(<ArchitectureDiagram />);
    fireEvent.click(screen.getByTestId("agent-node-identity"));
    expect(
      within(screen.getByTestId("agent-modal")).getByRole("heading", {
        name: /identity tracker/i,
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("agent-node-governance"));
    expect(
      within(screen.getByTestId("agent-modal")).getByRole("heading", {
        name: /^governance$/i,
      }),
    ).toBeInTheDocument();
  });

  it("includes the architecture-section eyebrow + headline anchors", () => {
    render(<ArchitectureDiagram />);
    expect(screen.getByTestId("architecture-section")).toBeInTheDocument();
    expect(screen.getByTestId("architecture-headline")).toBeInTheDocument();
  });
});

describe("HowItWorks (5-beat product arc)", () => {
  it("renders the five canonical CLAUDE.md product-arc beats", () => {
    render(<HowItWorks />);
    // Beats from docs/superpowers/specs/2026-04-26-wormbase-product-arc.md
    const beats = [
      "CONNECT",
      "GROW THE LAKE",
      "BUILD CONCURRENTLY",
      "PRODUCE",
      "SELF-IMPROVE",
    ];
    for (const beat of beats) {
      expect(
        screen.getByTestId(`how-it-works-beat-${beat.toLowerCase().split(" ")[0]}`),
      ).toBeInTheDocument();
    }
  });

  it("each beat carries a numeric kicker", () => {
    render(<HowItWorks />);
    for (const n of ["1", "2", "3", "4", "5"]) {
      expect(screen.getByTestId(`how-it-works-step-${n}`)).toBeInTheDocument();
    }
  });
});

describe("Pricing (Phase 4D — three real tiers, Stripe Checkout)", () => {
  // Detailed economics + Stripe wiring assertions live in
  // tests/unit/Pricing.test.tsx. This block keeps the landing-sections
  // suite focused on the section's place in the landing composition.
  it("renders three real tiers (free / pro / enterprise)", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    expect(screen.getAllByTestId(/^pricing-tier-/).length).toBe(3);
    expect(screen.getByTestId("pricing-tier-free")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-pro")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-enterprise")).toBeInTheDocument();
  });

  it("CTAs are real, not disabled — every tier ships a working link", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    for (const id of ["free", "pro", "enterprise"]) {
      const cta = screen.getByTestId(`pricing-cta-${id}`);
      const href =
        cta.getAttribute("href") ??
        cta.closest("a")?.getAttribute("href") ??
        "";
      expect(href.length).toBeGreaterThan(0);
      expect(cta).not.toBeDisabled();
    }
  });
});

describe("SignupCTA (Phase 4C — wired to /api/auth/slack/start)", () => {
  // Detailed coverage of the magic-link form lives in
  // tests/unit/SignupCTA.test.tsx. This block keeps the landing-sections
  // suite focused on the primary + secondary CTA contract.
  it("primary CTA links at /api/auth/slack/start", () => {
    render(<SignupCTA />);
    const cta = screen.getByTestId("signup-primary");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    expect(href).toBe("/api/auth/slack/start");
  });

  it("offers a working secondary CTA into the existing /onboarding wizard", () => {
    render(<SignupCTA />);
    const secondary = screen.getByTestId("signup-secondary");
    expect(secondary).toHaveAttribute("href", "/onboarding");
  });
});
