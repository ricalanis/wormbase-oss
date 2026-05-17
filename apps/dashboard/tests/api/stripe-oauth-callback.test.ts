/**
 * /onboarding/connect/stripe/callback route handler tests — Sub-wave D.
 *
 * Exercises the four happy + error branches of the Stripe OAuth
 * callback. Heavy stubs on the stripe lib + the stripe-ledger glue
 * so the route's wire-level logic is what's under test, not the
 * downstream code paths (those are unit-tested separately).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

const ORIGINAL_ENV = { ...process.env };

const {
  exchangeStripeCodeMock,
  storeStripeTokenMock,
  readStripeOAuthConfigMock,
  emitStripeSourceConnectedMock,
} = vi.hoisted(() => ({
  exchangeStripeCodeMock: vi.fn(),
  storeStripeTokenMock: vi.fn(),
  readStripeOAuthConfigMock: vi.fn(),
  emitStripeSourceConnectedMock: vi.fn(async () => undefined),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      if (name === "wormbase-stripe-oauth-state") {
        return { value: "csrf-good" };
      }
      if (name === "wormbase-tenant-slug") {
        return { value: "acme" };
      }
      return undefined;
    },
  }),
}));

vi.mock("../../lib/oauth/stripe", async () => {
  // Preserve the real STRIPE_STATE_COOKIE constant + the readConfig
  // (which is what gates the "not configured" branch).
  const actual = await vi.importActual<
    typeof import("../../lib/oauth/stripe")
  >("../../lib/oauth/stripe");
  return {
    ...actual,
    exchangeStripeCode: exchangeStripeCodeMock,
    storeStripeToken: storeStripeTokenMock,
    readStripeOAuthConfig: readStripeOAuthConfigMock,
  };
});

vi.mock("../../lib/oauth/stripe-ledger", () => ({
  emitStripeSourceConnected: emitStripeSourceConnectedMock,
}));

import { GET as callbackGet } from "../../app/onboarding/connect/[connector]/callback/route";

beforeEach(() => {
  exchangeStripeCodeMock.mockReset();
  storeStripeTokenMock.mockReset();
  readStripeOAuthConfigMock.mockReset();
  emitStripeSourceConnectedMock.mockClear();
  // Default: env is configured.
  readStripeOAuthConfigMock.mockReturnValue({
    configured: true,
    clientId: "ca_live_abc",
    missing: [],
  });
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

function makeRequest(qs: Record<string, string>): NextRequest {
  const url = new URL("https://app.example.com/onboarding/connect/stripe/callback");
  for (const [k, v] of Object.entries(qs)) url.searchParams.set(k, v);
  return new NextRequest(url);
}

describe("stripe OAuth callback route", () => {
  it("redirects to not-configured when env vars are missing", async () => {
    readStripeOAuthConfigMock.mockReturnValue({
      configured: false,
      clientId: null,
      missing: ["STRIPE_OAUTH_CLIENT_ID", "STRIPE_OAUTH_CLIENT_SECRET"],
    });
    const res = await callbackGet(
      makeRequest({ code: "ac_test_code", state: "csrf-good" }),
      { params: Promise.resolve({ connector: "stripe" }) },
    );
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/stripe/not-configured",
    );
    expect(exchangeStripeCodeMock).not.toHaveBeenCalled();
  });

  it("returns 400 on CSRF state mismatch", async () => {
    const res = await callbackGet(
      makeRequest({ code: "ac_test_code", state: "wrong-csrf" }),
      { params: Promise.resolve({ connector: "stripe" }) },
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("state_mismatch");
    expect(exchangeStripeCodeMock).not.toHaveBeenCalled();
  });

  it("redirects to error page on token exchange failure", async () => {
    exchangeStripeCodeMock.mockRejectedValueOnce(
      Object.assign(new Error("Stripe rejected the code"), {
        code: "invalid_grant",
        status: 400,
      }),
    );
    const res = await callbackGet(
      makeRequest({ code: "ac_used", state: "csrf-good" }),
      { params: Promise.resolve({ connector: "stripe" }) },
    );
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding/connect/stripe/error");
    expect(location).toContain("error=invalid_grant");
    expect(location).toContain("phase=token_exchange");
  });

  it("succeeds end-to-end + redirects to source detail with account", async () => {
    exchangeStripeCodeMock.mockResolvedValueOnce({
      access_token: "sk_acct_token",
      refresh_token: "rt",
      scope: "read_only",
      livemode: false,
      stripe_user_id: "acct_456",
      token_type: "bearer",
    });
    storeStripeTokenMock.mockResolvedValueOnce({
      handle: "stripe::acme::acct_456",
      scheme: "env",
      stripeUserId: "acct_456",
      livemode: false,
      scope: "read_only",
    });
    const res = await callbackGet(
      makeRequest({ code: "ac_good", state: "csrf-good" }),
      { params: Promise.resolve({ connector: "stripe" }) },
    );
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/sources/new/stripe");
    expect(location).toContain("connected=1");
    expect(location).toContain("account=acct_456");
    expect(emitStripeSourceConnectedMock).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantSlug: "acme",
        stripeUserId: "acct_456",
        scope: "read_only",
        credentialHandle: "stripe::acme::acct_456",
      }),
    );
  });

  it("salesforce stays on credential-paste fallback (not Stripe-graduated)", async () => {
    const res = await callbackGet(
      makeRequest({}),
      { params: Promise.resolve({ connector: "salesforce" }) },
    );
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/salesforce/credentials",
    );
    expect(res.headers.get("location")).toContain("oauth_unconfigured=1");
  });

  it("hubspot stays on credential-paste fallback", async () => {
    const res = await callbackGet(
      makeRequest({}),
      { params: Promise.resolve({ connector: "hubspot" }) },
    );
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/hubspot/credentials",
    );
  });

  it("redirects to error when user cancels on Stripe consent screen", async () => {
    const res = await callbackGet(
      makeRequest({ error: "access_denied" }),
      { params: Promise.resolve({ connector: "stripe" }) },
    );
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding/connect/stripe/error");
    expect(location).toContain("error=access_denied");
    expect(location).toContain("phase=consent");
  });
});
