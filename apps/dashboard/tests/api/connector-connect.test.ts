/**
 * G3 — connector-first connect handlers.
 *
 * Covers:
 *   - GET /onboarding/connect/{connector}/start — kind routing
 *     (csv_local → upload page; postgres → credentials; coming_soon →
 *     /onboarding error redirect; unknown → /onboarding error redirect).
 *   - GET /onboarding/connect/{connector}/callback — placeholder redirect
 *     to credentials with oauth_unconfigured hint.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

interface Ctx {
  params: Promise<{ connector: string }>;
}

function ctxFor(connector: string): Ctx {
  return { params: Promise.resolve({ connector }) };
}

// ---------------------------------------------------------------------------
// start handler
// ---------------------------------------------------------------------------

describe("GET /onboarding/connect/[connector]/start", () => {
  it("redirects csv_local to /onboarding/connect/csv/upload", async () => {
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/csv_local/start",
    );
    const res = await GET(req as never, ctxFor("csv_local"));
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/csv/upload",
    );
  });

  it("redirects postgres to /onboarding/connect/postgres/credentials", async () => {
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/postgres/start",
    );
    const res = await GET(req as never, ctxFor("postgres"));
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/postgres/credentials",
    );
  });

  it("redirects stripe (production) to credentials form (OAuth lands in v1.5)", async () => {
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/stripe/start",
    );
    const res = await GET(req as never, ctxFor("stripe"));
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toContain(
      "/onboarding/connect/stripe/credentials",
    );
  });

  it("redirects a coming_soon connector to /onboarding with error", async () => {
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/notion/start",
    );
    const res = await GET(req as never, ctxFor("notion"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding");
    expect(location).toContain("error=notion_coming_soon");
  });

  it("redirects an unknown connector kind to /onboarding with error", async () => {
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/quux/start",
    );
    const res = await GET(req as never, ctxFor("quux"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding");
    expect(location).toContain("error=unknown_connector");
  });
});

// ---------------------------------------------------------------------------
// callback handler (Sub-wave D Stripe OAuth + credential-paste fallback)
//
// Sub-wave D (2026-05-30) graduated Stripe off the credential-paste
// fallback: when STRIPE_OAUTH_CLIENT_ID + STRIPE_OAUTH_CLIENT_SECRET
// are unset, the Stripe callback redirects to /stripe/not-configured
// (honest disabled surface), NOT to /stripe/credentials. The other
// three OAuth-style connectors (salesforce / hubspot / gsheets) still
// use the credential-paste fallback until their OAuth ports land.
// See callback/route.ts §docstring + CREDENTIAL_PASTE_CONNECTORS set.
// ---------------------------------------------------------------------------

describe("GET /onboarding/connect/[connector]/callback", () => {
  it("Stripe callback without env vars lands on /not-configured (Sub-wave D honest-disabled)", async () => {
    // Ensure Stripe OAuth env vars are unset for the test — the
    // not-configured branch fires when readStripeOAuthConfig() reports
    // missing client_id / client_secret.
    const prevClientId = process.env.STRIPE_OAUTH_CLIENT_ID;
    const prevClientSecret = process.env.STRIPE_OAUTH_CLIENT_SECRET;
    delete process.env.STRIPE_OAUTH_CLIENT_ID;
    delete process.env.STRIPE_OAUTH_CLIENT_SECRET;
    try {
      const { GET } = await import(
        "../../app/onboarding/connect/[connector]/callback/route"
      );
      const req = new Request(
        "http://localhost:3000/onboarding/connect/stripe/callback?code=foo",
      );
      const res = await GET(req as never, ctxFor("stripe"));
      expect(res.status).toBe(303);
      const location = res.headers.get("location") ?? "";
      expect(location).toContain("/onboarding/connect/stripe/not-configured");
      // missing= param surfaces which env vars need to be set; honest
      // disabled posture per Sub-wave D / CLAUDE.md §"Onboarding
      // Production-Only" memory.
      expect(location).toContain("missing=");
    } finally {
      if (prevClientId !== undefined) {
        process.env.STRIPE_OAUTH_CLIENT_ID = prevClientId;
      }
      if (prevClientSecret !== undefined) {
        process.env.STRIPE_OAUTH_CLIENT_SECRET = prevClientSecret;
      }
    }
  });

  it("Salesforce callback redirects to credentials form with oauth_unconfigured hint", async () => {
    // Salesforce is in CREDENTIAL_PASTE_CONNECTORS (OAuth port lands
    // in a future wave). Its callback still uses the paste-the-key
    // fallback that Stripe graduated off in Sub-wave D.
    const { GET } = await import(
      "../../app/onboarding/connect/[connector]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/connect/salesforce/callback?code=foo",
    );
    const res = await GET(req as never, ctxFor("salesforce"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding/connect/salesforce/credentials");
    expect(location).toContain("oauth_unconfigured=1");
  });
});
