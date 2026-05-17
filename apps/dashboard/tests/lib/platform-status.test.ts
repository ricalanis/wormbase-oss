/**
 * Capability-honesty: every platform descriptor in PLATFORMS declares
 * ``status`` + ``statusNote``. Mirrors test_adapter_status.py.
 */
import { describe, it, expect } from "vitest";
import {
  PLATFORMS,
  platformBySlug,
  platformsByStatus,
  isPlatformConfigured,
  type PlatformStatus,
} from "../../lib/platform-status";

const ALLOWED: ReadonlyArray<PlatformStatus> = [
  "production",
  "preview",
  "coming_soon",
];

const EXPECTED: Record<string, PlatformStatus> = {
  slack: "production",
  discord: "preview",
  teams: "preview",
  signal: "coming_soon",
  // WhatsApp graduated to preview on 2026-05-06 (Phase D1 of the
  // first-class WhatsApp plan): ingest + DM live via OpenClaw Baileys.
  // Send remains gated pending OpenClaw issue #73016, so status_note
  // carries the Baileys ToS caveat.
  whatsapp: "preview",
};

describe("platform-status", () => {
  it("every descriptor has a status from the allowed set", () => {
    for (const p of PLATFORMS) {
      expect(ALLOWED).toContain(p.status);
    }
  });

  it("every descriptor has a non-empty statusNote ≤ 200 chars", () => {
    for (const p of PLATFORMS) {
      expect(typeof p.statusNote).toBe("string");
      expect(p.statusNote.length).toBeGreaterThan(0);
      expect(p.statusNote.length).toBeLessThanOrEqual(200);
    }
  });

  it("status matches the python ChannelAdapter expectations", () => {
    for (const [slug, expected] of Object.entries(EXPECTED)) {
      const desc = platformBySlug(slug);
      expect(desc, `${slug} should be in PLATFORMS`).toBeTruthy();
      expect(desc?.status).toBe(expected);
    }
  });

  it("non-coming-soon platforms have an envHint pointing at OAuth env vars", () => {
    for (const p of PLATFORMS) {
      if (p.status === "coming_soon") continue;
      expect(p.envHint, `${p.platform} needs an envHint`).toBeTruthy();
      expect(p.envHint!.length).toBeGreaterThan(0);
    }
  });

  it("platformBySlug returns null for unknown slugs", () => {
    expect(platformBySlug("not-a-platform")).toBeNull();
  });

  it("platformsByStatus filters correctly", () => {
    expect(platformsByStatus("production").map((p) => p.platform)).toEqual([
      "slack",
    ]);
    expect(platformsByStatus("preview").map((p) => p.platform).sort()).toEqual([
      "discord",
      "teams",
      "whatsapp",
    ]);
    expect(
      platformsByStatus("coming_soon").map((p) => p.platform).sort(),
    ).toEqual(["signal"]);
  });
});

describe("isPlatformConfigured", () => {
  it("returns false for coming_soon platforms regardless of env", () => {
    const signal = platformBySlug("signal")!;
    expect(isPlatformConfigured(signal, {})).toBe(false);
    expect(isPlatformConfigured(signal, undefined)).toBe(false);
  });

  it("returns false for preview/production when required env is missing", () => {
    const slack = platformBySlug("slack")!;
    expect(isPlatformConfigured(slack, {})).toBe(false);
    expect(
      isPlatformConfigured(slack, { SLACK_CLIENT_ID: true }),
    ).toBe(false);
  });

  it("returns true for preview/production when all required env is set", () => {
    const slack = platformBySlug("slack")!;
    expect(
      isPlatformConfigured(slack, {
        SLACK_CLIENT_ID: true,
        SLACK_CLIENT_SECRET: true,
      }),
    ).toBe(true);
    const discord = platformBySlug("discord")!;
    expect(
      isPlatformConfigured(discord, {
        DISCORD_CLIENT_ID: true,
        DISCORD_CLIENT_SECRET: true,
      }),
    ).toBe(true);
  });

  it("returns false when envState is undefined (unknown server config)", () => {
    const slack = platformBySlug("slack")!;
    // Note: the platform-status helper is conservative — undefined means
    // "we don't know if env is set," and the safe answer is false. The
    // ConnectPlatformButtons component has a separate convention for
    // tests where undefined means "assume configured."
    expect(isPlatformConfigured(slack, undefined)).toBe(false);
  });
});
