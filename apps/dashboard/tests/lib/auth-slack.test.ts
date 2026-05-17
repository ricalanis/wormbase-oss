/**
 * Phase 1B.C — Slack OAuth signup-vs-reauth decision logic tests.
 *
 * Pairs with the spike + plan at:
 *   - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
 *   - docs/superpowers/plans/2026-05-04-multitenancy-v2.md
 */
import { describe, it, expect } from "vitest";
import {
  decideSignupVsReauth,
  deriveTenantSlug,
  safeWorkspaceDisplayName,
  sha256HexHash,
  type ProjectionTenantRow,
} from "../../lib/server/auth/slack";

describe("decideSignupVsReauth", () => {
  it("routes unknown workspace to signup", () => {
    const decision = decideSignupVsReauth({
      tenantSlug: "slack_team_t99999",
      existingProjectionRow: null,
    });
    expect(decision.kind).toBe("signup");
  });

  it("routes existing active workspace to reauth", () => {
    const decision = decideSignupVsReauth({
      tenantSlug: "slack_team_t12345",
      existingProjectionRow: {
        slug: "slack_team_t12345",
        status: "active",
      } as ProjectionTenantRow,
    });
    expect(decision.kind).toBe("reauth");
  });

  it("routes pending workspace to signup (resume)", () => {
    const decision = decideSignupVsReauth({
      tenantSlug: "slack_team_t12345",
      existingProjectionRow: {
        slug: "slack_team_t12345",
        status: "pending",
      } as ProjectionTenantRow,
    });
    expect(decision.kind).toBe("signup");
  });

  it("rejects suspended workspace with a 'suspended' hint", () => {
    const decision = decideSignupVsReauth({
      tenantSlug: "slack_team_t12345",
      existingProjectionRow: {
        slug: "slack_team_t12345",
        status: "suspended",
      } as ProjectionTenantRow,
    });
    expect(decision.kind).toBe("rejected");
    if (decision.kind === "rejected") {
      expect(decision.reason).toMatch(/suspended/);
    }
  });

  it("rejects deleted workspace with a 'deleted' hint", () => {
    const decision = decideSignupVsReauth({
      tenantSlug: "slack_team_t12345",
      existingProjectionRow: {
        slug: "slack_team_t12345",
        status: "deleted",
      } as ProjectionTenantRow,
    });
    expect(decision.kind).toBe("rejected");
    if (decision.kind === "rejected") {
      expect(decision.reason).toMatch(/deleted/);
    }
  });
});

describe("deriveTenantSlug", () => {
  it("matches the canonical slack_team_<lower(team_id)> shape", () => {
    expect(deriveTenantSlug("slack", "T1234ABCD")).toBe(
      "slack_team_t1234abcd",
    );
  });

  it("preserves non-slack platforms in the prefix", () => {
    expect(deriveTenantSlug("discord", "9999")).toBe("discord_team_9999");
  });

  it("lower-cases mixed-case workspace ids", () => {
    expect(deriveTenantSlug("slack", "TaBcDeFg")).toBe(
      "slack_team_tabcdefg",
    );
  });
});

describe("sha256HexHash", () => {
  it("produces 64 lowercase hex chars", async () => {
    const h = await sha256HexHash("hello");
    expect(h).toHaveLength(64);
    expect(h).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic", async () => {
    const a = await sha256HexHash("oauth-state-token");
    const b = await sha256HexHash("oauth-state-token");
    expect(a).toBe(b);
  });

  it("differs across inputs", async () => {
    const a = await sha256HexHash("a");
    const b = await sha256HexHash("b");
    expect(a).not.toBe(b);
  });
});

describe("safeWorkspaceDisplayName", () => {
  it("uses the raw name when present and non-empty", () => {
    expect(safeWorkspaceDisplayName("Acme Co", "slack_team_t1")).toBe(
      "Acme Co",
    );
  });

  it("falls back to a humanized slug when raw is null", () => {
    expect(safeWorkspaceDisplayName(null, "slack_team_t1")).toBe("Slack t1");
  });

  it("falls back to a humanized slug when raw is whitespace", () => {
    expect(safeWorkspaceDisplayName("  ", "slack_team_t1")).toBe("Slack t1");
  });
});
