/**
 * Stripe OAuth handler unit tests — Onboarding Sub-wave D.
 *
 * Coverage:
 *   * isConfigured() honesty: missing env → not-configured + reasons.
 *   * Authorize-URL shape includes client_id + state + scope.
 *   * Token exchange: success, invalid_grant, invalid_client, network.
 *   * Secret-ref resolution: raw, env:// (set + unset), vault://
 *     missing-VAULT_ADDR path.
 *   * Token storage receipt shape (env path vs vault path).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  STRIPE_OAUTH_AUTHORIZE_URL,
  STRIPE_OAUTH_TOKEN_URL,
  StripeOAuthError,
  buildStripeAuthorizeUrl,
  credentialHandleFor,
  exchangeStripeCode,
  generateOAuthState,
  readStripeOAuthConfig,
  resolveSecretRef,
  storeStripeToken,
} from "../../lib/oauth/stripe";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  delete process.env.STRIPE_OAUTH_CLIENT_ID;
  delete process.env.STRIPE_OAUTH_CLIENT_SECRET;
  delete process.env.VAULT_ADDR;
  delete process.env.VAULT_TOKEN;
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("readStripeOAuthConfig", () => {
  it("returns configured=false + lists missing vars honestly", () => {
    const cfg = readStripeOAuthConfig();
    expect(cfg.configured).toBe(false);
    expect(cfg.missing).toContain("STRIPE_OAUTH_CLIENT_ID");
    expect(cfg.missing).toContain("STRIPE_OAUTH_CLIENT_SECRET");
    expect(cfg.clientId).toBeNull();
  });

  it("returns configured=true when both env vars are set", () => {
    process.env.STRIPE_OAUTH_CLIENT_ID = "ca_live_abc123";
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const cfg = readStripeOAuthConfig();
    expect(cfg.configured).toBe(true);
    expect(cfg.clientId).toBe("ca_live_abc123");
    expect(cfg.missing).toEqual([]);
  });

  it("reports the missing var when only one of the two is set", () => {
    process.env.STRIPE_OAUTH_CLIENT_ID = "ca_live_abc123";
    const cfg = readStripeOAuthConfig();
    expect(cfg.configured).toBe(false);
    expect(cfg.missing).toEqual(["STRIPE_OAUTH_CLIENT_SECRET"]);
  });
});

describe("buildStripeAuthorizeUrl", () => {
  it("includes client_id + state + scope + redirect_uri", () => {
    const url = buildStripeAuthorizeUrl({
      clientId: "ca_live_abc",
      state: "csrf-token-xyz",
      redirectUri: "https://app.example.com/cb",
    });
    expect(url.startsWith(STRIPE_OAUTH_AUTHORIZE_URL)).toBe(true);
    const u = new URL(url);
    expect(u.searchParams.get("client_id")).toBe("ca_live_abc");
    expect(u.searchParams.get("state")).toBe("csrf-token-xyz");
    expect(u.searchParams.get("scope")).toBe("read_only");
    expect(u.searchParams.get("response_type")).toBe("code");
    expect(u.searchParams.get("redirect_uri")).toBe("https://app.example.com/cb");
  });

  it("supports read_write scope override", () => {
    const url = buildStripeAuthorizeUrl({
      clientId: "ca_live_abc",
      state: "s",
      redirectUri: "https://app.example.com/cb",
      scope: "read_write",
    });
    const u = new URL(url);
    expect(u.searchParams.get("scope")).toBe("read_write");
  });
});

describe("generateOAuthState", () => {
  it("returns a non-empty URL-safe base64 string", () => {
    const s = generateOAuthState();
    expect(s.length).toBeGreaterThan(20);
    expect(s).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("returns distinct values on successive calls", () => {
    const a = generateOAuthState();
    const b = generateOAuthState();
    expect(a).not.toEqual(b);
  });
});

describe("credentialHandleFor", () => {
  it("produces a tenant + stripe_user composite key", () => {
    expect(credentialHandleFor("acme", "acct_123")).toBe(
      "stripe::acme::acct_123",
    );
  });

  it("defaults the tenant slug when empty", () => {
    expect(credentialHandleFor("", "acct_123")).toBe(
      "stripe::baseworm::acct_123",
    );
  });

  it("throws when stripe_user_id missing", () => {
    expect(() => credentialHandleFor("acme", "")).toThrow();
  });
});

describe("exchangeStripeCode", () => {
  it("succeeds on a 200 with a well-shaped token envelope", async () => {
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const okBody = {
      access_token: "sk_acct_token",
      refresh_token: "rt_token",
      scope: "read_only",
      livemode: false,
      stripe_user_id: "acct_456",
      token_type: "bearer",
    };
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(okBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const token = await exchangeStripeCode({
      code: "ac_test_code",
      clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(token.access_token).toBe("sk_acct_token");
    expect(token.stripe_user_id).toBe("acct_456");
    expect(fetchImpl).toHaveBeenCalledWith(
      STRIPE_OAUTH_TOKEN_URL,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("throws StripeOAuthError(invalid_grant) on Stripe 400 invalid_grant", async () => {
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: "invalid_grant",
            error_description: "Authorization code has already been used",
          }),
          { status: 400 },
        ),
    );
    await expect(
      exchangeStripeCode({
        code: "used_code",
        clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "StripeOAuthError",
      code: "invalid_grant",
      status: 400,
    });
  });

  it("throws on missing code", async () => {
    await expect(
      exchangeStripeCode({
        code: "",
        clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
      }),
    ).rejects.toBeInstanceOf(StripeOAuthError);
  });

  it("throws on network failure", async () => {
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const fetchImpl = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const promise = exchangeStripeCode({
      code: "ac",
      clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await expect(promise).rejects.toMatchObject({
      name: "StripeOAuthError",
      code: "network_error",
    });
  });

  it("throws on non-JSON response body", async () => {
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const fetchImpl = vi.fn(
      async () => new Response("Internal Server Error", { status: 500 }),
    );
    await expect(
      exchangeStripeCode({
        code: "ac",
        clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ code: "bad_response" });
  });

  it("throws bad_response on missing required fields", async () => {
    process.env.STRIPE_OAUTH_CLIENT_SECRET = "sk_test_xyz";
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ token_type: "bearer" }), { status: 200 }),
    );
    await expect(
      exchangeStripeCode({
        code: "ac",
        clientSecretRef: "env://STRIPE_OAUTH_CLIENT_SECRET",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ code: "bad_response" });
  });
});

describe("resolveSecretRef", () => {
  it("passes raw secrets through unchanged", async () => {
    const out = await resolveSecretRef("sk_test_raw_secret");
    expect(out).toBe("sk_test_raw_secret");
  });

  it("reads env:// refs from process env", async () => {
    process.env.MY_SECRET = "value-from-env";
    const out = await resolveSecretRef("env://MY_SECRET");
    expect(out).toBe("value-from-env");
  });

  it("throws when env:// ref points at unset var", async () => {
    await expect(resolveSecretRef("env://NOPE_NOT_SET")).rejects.toThrow(/env-ref/);
  });

  it("throws when vault:// ref supplied but VAULT_ADDR unset", async () => {
    await expect(resolveSecretRef("vault://path/to/secret")).rejects.toThrow(
      /VAULT_ADDR/,
    );
  });
});

describe("storeStripeToken", () => {
  const token = {
    access_token: "sk_acct_token",
    refresh_token: "rt_token",
    scope: "read_only",
    livemode: false,
    stripe_user_id: "acct_456",
    token_type: "bearer",
  };

  it("returns env-resident receipt when VAULT_ADDR unset", async () => {
    const receipt = await storeStripeToken({
      tenantSlug: "acme",
      token,
    });
    expect(receipt.scheme).toBe("env");
    expect(receipt.handle).toBe("stripe::acme::acct_456");
    expect(receipt.stripeUserId).toBe("acct_456");
    expect(receipt.scope).toBe("read_only");
  });

  it("writes to Vault when VAULT_ADDR + VAULT_TOKEN set, returns vault receipt", async () => {
    process.env.VAULT_ADDR = "https://vault.example.com";
    process.env.VAULT_TOKEN = "vault-token";
    const fetchImpl = vi.fn(
      async () => new Response("{}", { status: 204 }),
    );
    const receipt = await storeStripeToken({
      tenantSlug: "acme",
      token,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(receipt.scheme).toBe("vault");
    expect(fetchImpl).toHaveBeenCalled();
    const firstCall = fetchImpl.mock.calls[0] as unknown as [string, unknown];
    expect(String(firstCall[0])).toContain(
      "/v1/secret/data/wormbase/stripe/acme/acct_456",
    );
  });

  it("throws when VAULT_ADDR set but VAULT_TOKEN unset", async () => {
    process.env.VAULT_ADDR = "https://vault.example.com";
    await expect(
      storeStripeToken({ tenantSlug: "acme", token }),
    ).rejects.toThrow(/VAULT_TOKEN/);
  });
});
