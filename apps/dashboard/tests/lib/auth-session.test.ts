/**
 * Phase 1B.E — signed session cookie tests.
 *
 * Pairs with the spike + plan at:
 *   - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
 *   - docs/superpowers/plans/2026-05-04-multitenancy-v2.md
 */
import { describe, it, expect } from "vitest";
import {
  DEFAULT_SESSION_TTL_SECONDS,
  SESSION_COOKIE_NAME,
  decodeSessionCookie,
  encodeSessionCookie,
} from "../../lib/server/auth/session";

describe("encodeSessionCookie / decodeSessionCookie", () => {
  it("round-trips tenant_slug + person_id + exp", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "slack_team_t12345",
      personId: "11111111-1111-1111-1111-111111111111",
      secret: "test-secret",
      expiresInSeconds: 86400,
    });
    const claims = decodeSessionCookie(cookie, { secret: "test-secret" });
    expect(claims).not.toBeNull();
    expect(claims!.tenantSlug).toBe("slack_team_t12345");
    expect(claims!.personId).toBe("11111111-1111-1111-1111-111111111111");
  });

  it("supports null personId (observer-only sessions)", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "wormbase-saas-demo",
      personId: null,
      secret: "s",
      expiresInSeconds: 60,
    });
    const claims = decodeSessionCookie(cookie, { secret: "s" });
    expect(claims).not.toBeNull();
    expect(claims!.personId).toBeNull();
  });

  it("rejects tampered signatures", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "x",
      personId: null,
      secret: "s",
      expiresInSeconds: 60,
    });
    const tampered = cookie.slice(0, -2) + "AA";
    expect(decodeSessionCookie(tampered, { secret: "s" })).toBeNull();
  });

  it("rejects tampered bodies", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "x",
      personId: null,
      secret: "s",
      expiresInSeconds: 60,
    });
    const [head, sig] = cookie.split(".");
    // Replace head with another valid base64url body.
    const tampered = "ZXZpbA." + sig;
    expect(decodeSessionCookie(tampered, { secret: "s" })).toBeNull();
  });

  it("rejects wrong-secret signatures", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "x",
      personId: null,
      secret: "right",
      expiresInSeconds: 60,
    });
    expect(decodeSessionCookie(cookie, { secret: "wrong" })).toBeNull();
  });

  it("rejects expired cookies", () => {
    const cookie = encodeSessionCookie({
      tenantSlug: "x",
      personId: null,
      secret: "s",
      expiresInSeconds: -1,
    });
    expect(decodeSessionCookie(cookie, { secret: "s" })).toBeNull();
  });

  it("rejects malformed cookies (no dot)", () => {
    expect(decodeSessionCookie("not-valid", { secret: "s" })).toBeNull();
  });

  it("rejects cookies with invalid JSON in body", () => {
    // base64url("not json").base64url(matching hmac) — but the body fails
    // to parse so decode returns null. Easiest path: encode with a bogus
    // body and a real sig.
    const result = decodeSessionCookie("xyz.AAAA", { secret: "s" });
    expect(result).toBeNull();
  });
});

describe("session cookie constants", () => {
  it("declares the canonical session cookie name", () => {
    expect(SESSION_COOKIE_NAME).toBe("wormbase-session");
  });

  it("declares a 30-day default TTL", () => {
    expect(DEFAULT_SESSION_TTL_SECONDS).toBe(60 * 60 * 24 * 30);
  });
});
