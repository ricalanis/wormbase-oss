/**
 * Phase 4 Task 4C — end-to-end tests for the magic-link confirm route.
 *
 * Validates that /api/auth/email/confirm decodes a signed token, picks
 * one of the demo tenant slugs from the carousel, and binds a session
 * cookie that resolves under the dashboard's tenant lookup. The session
 * cookie this route emits is a signed `wormbase-session` cookie (not the
 * legacy unsigned slug cookie) so subsequent requests can be verified
 * against the same signing surface as the rest of the dashboard.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import {
  encodeMagicLinkToken,
  DEFAULT_DEMO_TENANT_SLUGS,
} from "../../lib/server/auth/magic-link";
import {
  SESSION_COOKIE_NAME,
  decodeSessionCookie,
} from "../../lib/server/auth/session";
import { GET as confirmRoute } from "../../app/api/auth/email/confirm/route";

const SECRET = "test-confirm-secret";

function makeRequest(token: string | null): Request {
  const url = new URL("https://dashboard.example/api/auth/email/confirm");
  if (token !== null) url.searchParams.set("token", token);
  return new Request(url.toString());
}

describe("/api/auth/email/confirm — Phase 4C wire-up", () => {
  let oldSecret: string | undefined;
  let oldDashboard: string | undefined;
  let oldDemo: string | undefined;
  beforeEach(() => {
    oldSecret = process.env.WORMBASE_LEDGER_API_TOKEN;
    oldDashboard = process.env.WORMBASE_DASHBOARD_URL;
    oldDemo = process.env.WORMBASE_DEMO_TENANT_SLUGS;
    process.env.WORMBASE_LEDGER_API_TOKEN = SECRET;
    delete process.env.WORMBASE_DEMO_TENANT_SLUGS;
  });
  afterEach(() => {
    if (oldSecret === undefined) delete process.env.WORMBASE_LEDGER_API_TOKEN;
    else process.env.WORMBASE_LEDGER_API_TOKEN = oldSecret;
    if (oldDashboard === undefined) delete process.env.WORMBASE_DASHBOARD_URL;
    else process.env.WORMBASE_DASHBOARD_URL = oldDashboard;
    if (oldDemo === undefined) delete process.env.WORMBASE_DEMO_TENANT_SLUGS;
    else process.env.WORMBASE_DEMO_TENANT_SLUGS = oldDemo;
  });

  it("rejects missing tokens with 400 missing_token", async () => {
    const res = await confirmRoute(makeRequest(null) as unknown as never);
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.error).toBe("missing_token");
  });

  it("rejects invalid/expired tokens with 400 invalid_or_expired", async () => {
    const res = await confirmRoute(makeRequest("not-a-token") as unknown as never);
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.error).toBe("invalid_or_expired");
  });

  it("rejects when WORMBASE_LEDGER_API_TOKEN is unset with 503", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const token = encodeMagicLinkToken({
      email: "x@x.com",
      secret: SECRET,
      expiresInSeconds: 600,
    });
    const res = await confirmRoute(makeRequest(token) as unknown as never);
    expect(res.status).toBe(503);
    const json = await res.json();
    expect(json.error).toBe("auth_secret_unset");
  });

  it("303-redirects to /dashboard?welcome=email on success", async () => {
    const token = encodeMagicLinkToken({
      email: "evaluator@example.com",
      secret: SECRET,
      expiresInSeconds: 600,
    });
    const res = await confirmRoute(makeRequest(token) as unknown as never);
    expect(res.status).toBe(303);
    const loc = res.headers.get("location") ?? "";
    expect(loc).toContain("/dashboard");
    expect(loc).toContain("welcome=email");
  });

  it("sets a signed session cookie pointing at one of the demo tenants", async () => {
    const token = encodeMagicLinkToken({
      email: "evaluator@example.com",
      secret: SECRET,
      expiresInSeconds: 600,
    });
    const res = await confirmRoute(makeRequest(token) as unknown as never);
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain(`${SESSION_COOKIE_NAME}=`);
    // Extract the value of wormbase-session.
    const match = setCookie.match(
      new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`),
    );
    expect(match).not.toBeNull();
    const value = decodeURIComponent(match![1]);
    const claims = decodeSessionCookie(value, { secret: SECRET });
    expect(claims).not.toBeNull();
    expect(DEFAULT_DEMO_TENANT_SLUGS).toContain(claims!.tenantSlug);
    // observer-only session — no Person grant yet.
    expect(claims!.personId).toBeNull();
  });

  it("the session cookie is httpOnly + secure-pathed for the dashboard root", async () => {
    const token = encodeMagicLinkToken({
      email: "x@y.com",
      secret: SECRET,
      expiresInSeconds: 600,
    });
    const res = await confirmRoute(makeRequest(token) as unknown as never);
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("path=/");
    expect(setCookie.toLowerCase()).toContain("samesite=lax");
  });

  it("is deterministic per email — same email always lands on the same demo tenant", async () => {
    const token1 = encodeMagicLinkToken({
      email: "stable@example.com",
      secret: SECRET,
      expiresInSeconds: 600,
    });
    const token2 = encodeMagicLinkToken({
      email: "stable@example.com",
      secret: SECRET,
      expiresInSeconds: 600,
      issuedAtSeconds: Math.floor(Date.now() / 1000) + 1,
    });
    const r1 = await confirmRoute(makeRequest(token1) as unknown as never);
    const r2 = await confirmRoute(makeRequest(token2) as unknown as never);
    const c1 = r1.headers.get("set-cookie") ?? "";
    const c2 = r2.headers.get("set-cookie") ?? "";
    const m1 = c1.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const m2 = c2.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const claims1 = decodeSessionCookie(decodeURIComponent(m1![1]), {
      secret: SECRET,
    });
    const claims2 = decodeSessionCookie(decodeURIComponent(m2![1]), {
      secret: SECRET,
    });
    expect(claims1!.tenantSlug).toBe(claims2!.tenantSlug);
  });
});
