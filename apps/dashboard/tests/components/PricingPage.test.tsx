/**
 * Phase 4 Task 4D — standalone /pricing route.
 *
 * Verifies the dedicated `/pricing` page renders the Pricing component with
 * the Field Notebook chrome (masthead + footer). The page reads the Stripe
 * Checkout URL from the env var ``NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL`` (or
 * the server-side ``STRIPE_PRO_CHECKOUT_URL`` in tests/dev) and threads it
 * into the section.
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

import PricingPage from "../../app/pricing/page";

describe("PricingPage (/pricing standalone route)", () => {
  const ORIGINAL = process.env.STRIPE_PRO_CHECKOUT_URL;
  const ORIGINAL_PUBLIC = process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL;

  beforeEach(() => {
    process.env.STRIPE_PRO_CHECKOUT_URL =
      "https://checkout.stripe.test/pro-route-test";
    delete process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL;
  });

  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.STRIPE_PRO_CHECKOUT_URL;
    else process.env.STRIPE_PRO_CHECKOUT_URL = ORIGINAL;
    if (ORIGINAL_PUBLIC === undefined) {
      delete process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL;
    } else {
      process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL = ORIGINAL_PUBLIC;
    }
  });

  it("renders the Pricing section and the deployment-wired Stripe URL", () => {
    render(<PricingPage />);
    expect(screen.getByTestId("pricing-section")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-free")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-pro")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-tier-enterprise")).toBeInTheDocument();
    const cta = screen.getByTestId("pricing-cta-pro");
    const href =
      cta.getAttribute("href") ?? cta.closest("a")?.getAttribute("href") ?? "";
    expect(href).toBe("https://checkout.stripe.test/pro-route-test");
  });

  it("includes a masthead linking back to home for direct-link visitors", () => {
    render(<PricingPage />);
    const home = screen.getByTestId("pricing-page-home");
    expect(home).toHaveAttribute("href", "/");
  });
});
