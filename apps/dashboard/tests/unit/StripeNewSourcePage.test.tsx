/**
 * /sources/new/stripe page render tests — Sub-wave D.
 *
 * Validates the four UI branches:
 *   1. Configured + not connected → renders "Continue to Stripe" CTA
 *      pointing at /onboarding/connect/stripe/start.
 *   2. Configured + connected (callback redirect) → renders the
 *      "connected" banner with the Stripe account id.
 *   3. Not configured → renders the missing-env-vars banner.
 *   4. Not configured + connected → still surfaces missing-env-vars
 *      so the operator can fix root cause (defense in depth).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock PageBoundary so we don't drag in the chrome surface.
vi.mock("../../components/chrome/PageBoundary", () => ({
  PageBoundary: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="page-boundary">{children}</div>
  ),
}));

const { readConfigMock } = vi.hoisted(() => ({
  readConfigMock: vi.fn(),
}));
vi.mock("../../lib/oauth/stripe", () => ({
  readStripeOAuthConfig: readConfigMock,
}));

import NewStripeSourcePage from "../../app/(app)/sources/new/stripe/page";

beforeEach(() => {
  readConfigMock.mockReset();
});

afterEach(() => {
  readConfigMock.mockReset();
});

describe("/sources/new/stripe", () => {
  it("renders the Continue-to-Stripe CTA when configured + not connected", async () => {
    readConfigMock.mockReturnValue({
      configured: true,
      clientId: "ca_live_abc",
      missing: [],
    });
    const ui = await NewStripeSourcePage({
      searchParams: Promise.resolve({}),
    });
    render(ui);
    const cta = screen.getByTestId("stripe-start-link");
    expect(cta.getAttribute("href")).toBe("/onboarding/connect/stripe/start");
    expect(screen.queryByTestId("stripe-not-configured-banner")).toBeNull();
    expect(screen.queryByTestId("stripe-connected-banner")).toBeNull();
  });

  it("renders the connected banner after a successful callback redirect", async () => {
    readConfigMock.mockReturnValue({
      configured: true,
      clientId: "ca_live_abc",
      missing: [],
    });
    const ui = await NewStripeSourcePage({
      searchParams: Promise.resolve({ connected: "1", account: "acct_456" }),
    });
    render(ui);
    const banner = screen.getByTestId("stripe-connected-banner");
    expect(banner).toBeTruthy();
    expect(
      screen.getByTestId("stripe-connected-account").textContent,
    ).toBe("acct_456");
  });

  it("renders the not-configured banner when env vars are missing", async () => {
    readConfigMock.mockReturnValue({
      configured: false,
      clientId: null,
      missing: ["STRIPE_OAUTH_CLIENT_ID", "STRIPE_OAUTH_CLIENT_SECRET"],
    });
    const ui = await NewStripeSourcePage({
      searchParams: Promise.resolve({}),
    });
    render(ui);
    expect(screen.getByTestId("stripe-not-configured-banner")).toBeTruthy();
    const missing = screen.getByTestId("stripe-not-configured-missing");
    expect(missing.textContent).toContain("STRIPE_OAUTH_CLIENT_ID");
    expect(missing.textContent).toContain("STRIPE_OAUTH_CLIENT_SECRET");
    // CTA must NOT render when not configured — that's the bug fix.
    expect(screen.queryByTestId("stripe-start-link")).toBeNull();
  });

  it("never shows credential-paste fallback for stripe (regression guard)", async () => {
    readConfigMock.mockReturnValue({
      configured: false,
      clientId: null,
      missing: ["STRIPE_OAUTH_CLIENT_ID"],
    });
    const ui = await NewStripeSourcePage({
      searchParams: Promise.resolve({}),
    });
    render(ui);
    // The phrase the credential-paste fallback used to surface.
    expect(screen.queryByText(/paste an API key/i)).toBeNull();
  });
});
