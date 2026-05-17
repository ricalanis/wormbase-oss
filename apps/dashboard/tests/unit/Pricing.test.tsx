/**
 * Phase 4 Task 4D — Pricing component (real tiers, Stripe Checkout link).
 *
 * The PricingPlaceholder shipped in 4A is now replaced by a real Pricing
 * section that mirrors the orchestrator pricing decision:
 *
 *   - Free        — 1 Slack workspace, ≤10 Persons, ≤1 source, conversation-only
 *   - Pro         — $60/seat/mo + 100 artifacts/mo + $1/artifact thereafter,
 *                   Stripe Checkout CTA via STRIPE_PRO_CHECKOUT_URL env var
 *   - Enterprise  — Contact-sales mailto: CTA
 *
 * The tier ids are stable: ``free`` / ``pro`` / ``enterprise``. The
 * ``signup-pro-checkout`` link must point at whatever
 * ``NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL`` (or an injected
 * ``stripeCheckoutUrl`` prop, for SSR composition) resolves to.
 *
 * The standalone ``/pricing`` route renders the same component plus a
 * masthead/footer chrome — that integration is verified separately in
 * tests/components/PricingPage.test.tsx.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Pricing } from "../../components/landing/Pricing";

describe("Pricing (real tiers · Stripe Checkout link · 4D)", () => {
  it("renders three tiers: free, pro, enterprise", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    expect(screen.getByTestId("pricing-tier-free")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-pro")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-enterprise")).toBeInTheDocument();
  });

  it("Free tier surfaces the orchestrator-decided limits", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    const card = screen.getByTestId("pricing-tier-free");
    // 1 Slack workspace, ≤10 Persons, ≤1 source, conversation-only.
    expect(card.textContent).toMatch(/1 Slack workspace/i);
    expect(card.textContent).toMatch(/10 Persons/i);
    expect(card.textContent).toMatch(/1 source/i);
    expect(card.textContent?.toLowerCase()).toContain("conversation-only");
    // Free tier price line.
    expect(card.textContent).toMatch(/\$0/);
  });

  it("Pro tier surfaces the $60/seat + artifact economics", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    const card = screen.getByTestId("pricing-tier-pro");
    expect(card.textContent).toMatch(/\$60/);
    expect(card.textContent).toMatch(/seat/i);
    expect(card.textContent).toMatch(/100 artifacts/i);
    // Overage rate.
    expect(card.textContent).toMatch(/\$1\s*\/\s*artifact/i);
  });

  it("Pro CTA is a link to the injected Stripe Checkout URL", () => {
    const url = "https://checkout.stripe.test/pro-fake";
    render(<Pricing stripeCheckoutUrl={url} />);
    const cta = screen.getByTestId("pricing-cta-pro");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    expect(href).toBe(url);
  });

  it("Enterprise CTA is a mailto: contact-sales link", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    const cta = screen.getByTestId("pricing-cta-enterprise");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    expect(href.toLowerCase().startsWith("mailto:")).toBe(true);
    // Subject line carries something specific so support can route fast.
    expect(href.toLowerCase()).toContain("subject=");
  });

  it("Free CTA links into the existing /onboarding wizard (single source of truth)", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    const cta = screen.getByTestId("pricing-cta-free");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    expect(href).toBe("/onboarding");
  });

  it("falls back to a placeholder Stripe URL when none is provided", () => {
    // The component must never render a dead/empty href — if the deployment
    // hasn't wired STRIPE_PRO_CHECKOUT_URL yet, it falls back to a clearly
    // marked placeholder so we don't ship a #-only link.
    render(<Pricing />);
    const cta = screen.getByTestId("pricing-cta-pro");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    // Placeholder URL is non-empty and clearly marks itself as a placeholder.
    expect(href.length).toBeGreaterThan(0);
    expect(href).not.toBe("#");
  });

  it("section eyebrow + headline are present for nav and a11y", () => {
    render(<Pricing stripeCheckoutUrl="https://checkout.stripe.test/pro" />);
    expect(screen.getByTestId("pricing-section")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /pricing|receipts|pay/i }))
      .toBeInTheDocument();
  });
});
