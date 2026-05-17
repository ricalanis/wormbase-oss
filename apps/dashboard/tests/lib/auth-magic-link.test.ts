/**
 * Phase 1B.D — magic-link backend tests.
 *
 * Pairs with the spike + plan at:
 *   - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
 *   - docs/superpowers/plans/2026-05-04-multitenancy-v2.md
 */
import { describe, it, expect } from "vitest";
import {
  DEFAULT_DEMO_TENANT_SLUGS,
  decodeMagicLinkToken,
  encodeMagicLinkToken,
  getDemoTenantSlugs,
  hashTokenForLedger,
  isValidEmailShape,
  pickDemoTenantForEmail,
} from "../../lib/server/auth/magic-link";

describe("encodeMagicLinkToken / decodeMagicLinkToken", () => {
  it("round-trips email + signed timestamp", () => {
    const token = encodeMagicLinkToken({
      email: "evaluator@example.com",
      secret: "test-secret",
      expiresInSeconds: 900,
    });
    const claims = decodeMagicLinkToken(token, { secret: "test-secret" });
    expect(claims).not.toBeNull();
    expect(claims!.email).toBe("evaluator@example.com");
  });

  it("rejects tokens signed with the wrong secret", () => {
    const token = encodeMagicLinkToken({
      email: "x@x.com",
      secret: "right-secret",
      expiresInSeconds: 900,
    });
    expect(decodeMagicLinkToken(token, { secret: "wrong-secret" })).toBeNull();
  });

  it("rejects expired tokens", () => {
    const token = encodeMagicLinkToken({
      email: "x@x.com",
      secret: "s",
      expiresInSeconds: -1,
    });
    expect(decodeMagicLinkToken(token, { secret: "s" })).toBeNull();
  });

  it("rejects malformed tokens (no dot)", () => {
    expect(decodeMagicLinkToken("not-a-token", { secret: "s" })).toBeNull();
  });

  it("rejects tokens with tampered body", () => {
    const token = encodeMagicLinkToken({
      email: "x@x.com",
      secret: "s",
      expiresInSeconds: 60,
    });
    // Replace the body with a different valid base64url (different email).
    const tampered = "ZXZpbA." + token.split(".")[1];
    expect(decodeMagicLinkToken(tampered, { secret: "s" })).toBeNull();
  });

  it("rejects tokens with tampered signature", () => {
    const token = encodeMagicLinkToken({
      email: "x@x.com",
      secret: "s",
      expiresInSeconds: 60,
    });
    const [head] = token.split(".");
    const tampered = head + ".AAAA";
    expect(decodeMagicLinkToken(tampered, { secret: "s" })).toBeNull();
  });
});

describe("hashTokenForLedger", () => {
  it("produces 64 lowercase hex chars", () => {
    const h = hashTokenForLedger("anything");
    expect(h).toHaveLength(64);
    expect(h).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic", () => {
    const a = hashTokenForLedger("hello");
    const b = hashTokenForLedger("hello");
    expect(a).toBe(b);
  });
});

describe("pickDemoTenantForEmail", () => {
  it("picks the first unvisited demo tenant", () => {
    const slug = pickDemoTenantForEmail({
      email: "new@example.com",
      demoTenants: [
        { slug: "wormbase-saas-demo", visitors: [] },
        { slug: "wormbase-fintech-demo", visitors: [] },
      ],
    });
    expect(slug).toBe("wormbase-fintech-demo"); // alphabetical wins on ties
  });

  it("skips a tenant the email previously visited", () => {
    const slug = pickDemoTenantForEmail({
      email: "repeat@example.com",
      demoTenants: [
        {
          slug: "wormbase-saas-demo",
          visitors: [
            { email: "repeat@example.com", visited_at: "2026-05-01T00:00:00Z" },
          ],
        },
        { slug: "wormbase-fintech-demo", visitors: [] },
      ],
    });
    expect(slug).toBe("wormbase-fintech-demo");
  });

  it("round-robins to least-recently-visited when all visited", () => {
    const slug = pickDemoTenantForEmail({
      email: "frequent@example.com",
      demoTenants: [
        {
          slug: "wormbase-saas-demo",
          visitors: [
            {
              email: "frequent@example.com",
              visited_at: "2026-04-30T00:00:00Z",
            },
          ],
        },
        {
          slug: "wormbase-fintech-demo",
          visitors: [
            {
              email: "frequent@example.com",
              visited_at: "2026-04-10T00:00:00Z",
            },
          ],
        },
      ],
    });
    expect(slug).toBe("wormbase-fintech-demo"); // older visit
  });

  it("throws when no demo tenants are configured", () => {
    expect(() =>
      pickDemoTenantForEmail({ email: "x@x.com", demoTenants: [] }),
    ).toThrow(/no demo tenants/);
  });
});

describe("getDemoTenantSlugs", () => {
  it("returns the canonical 5-slug carousel by default", () => {
    delete process.env.WORMBASE_DEMO_TENANT_SLUGS;
    expect(getDemoTenantSlugs()).toEqual(DEFAULT_DEMO_TENANT_SLUGS);
  });

  it("respects WORMBASE_DEMO_TENANT_SLUGS env override", () => {
    process.env.WORMBASE_DEMO_TENANT_SLUGS = "alpha,beta, gamma";
    expect(getDemoTenantSlugs()).toEqual(["alpha", "beta", "gamma"]);
    delete process.env.WORMBASE_DEMO_TENANT_SLUGS;
  });
});

describe("isValidEmailShape", () => {
  it("accepts canonical email shapes", () => {
    expect(isValidEmailShape("a@b.com")).toBe(true);
    expect(isValidEmailShape("evaluator+test@acme.io")).toBe(true);
  });

  it("rejects empty / unstructured", () => {
    expect(isValidEmailShape("")).toBe(false);
    expect(isValidEmailShape("nope")).toBe(false);
    expect(isValidEmailShape("x@x")).toBe(false);
    expect(isValidEmailShape("x x@x.com")).toBe(false);
  });
});

describe("default demo tenant slugs", () => {
  it("contains exactly 5 thematic slugs", () => {
    expect(DEFAULT_DEMO_TENANT_SLUGS).toHaveLength(5);
  });

  it("matches the canonical thematic set", () => {
    expect(new Set(DEFAULT_DEMO_TENANT_SLUGS)).toEqual(
      new Set([
        "wormbase-saas-demo",
        "wormbase-fintech-demo",
        "wormbase-marketplace-demo",
        "wormbase-ecommerce-demo",
        "wormbase-agency-demo",
      ]),
    );
  });
});
