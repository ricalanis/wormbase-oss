/**
 * W4-D — Person-proposal provenance helpers.
 *
 * Pure-string-shape unit tests. The function maps the canonical
 * `proposed_by` strings (B2 / D2 encodings) onto editorial provenance
 * lines for the /people surface. Slack-rooted proposals must continue
 * to render their existing default line so the byte-shape contract
 * pre-/post-W4-D stays clean.
 */
import { describe, it, expect } from "vitest";

import {
  formatProposalProvenance,
  relativeTime,
} from "../../lib/people-display";
import type { PersonIdentityRow } from "../../lib/ledger-client.types";

function whatsappIdentity(jid: string): PersonIdentityRow {
  return {
    platform: "whatsapp",
    platformUserId: jid,
    proposedBy: "worm:whatsapp_organic_discovery",
    addedAt: null,
  };
}

function slackIdentity(uid = "U01XXXX"): PersonIdentityRow {
  return {
    platform: "slack",
    platformUserId: uid,
    proposedBy: "worm",
    addedAt: null,
  };
}

describe("formatProposalProvenance", () => {
  it("renders WhatsApp organic discovery as +E.164 with whatsapp_dm kind", () => {
    const id = whatsappIdentity("5215512345678@s.whatsapp.net");
    const r = formatProposalProvenance(
      "worm:whatsapp_organic_discovery",
      id,
    );
    expect(r.kind).toBe("whatsapp_dm");
    expect(r.highlight).toBe("+5215512345678");
    expect(r.label).toBe(
      "Proposed from WhatsApp DM with +5215512345678",
    );
  });

  it("falls back to bare WhatsApp DM label when no identity is present", () => {
    const r = formatProposalProvenance(
      "worm:whatsapp_organic_discovery",
      undefined,
    );
    expect(r.kind).toBe("whatsapp_dm");
    expect(r.highlight).toBe("");
    expect(r.label).toBe("Proposed from WhatsApp DM");
  });

  it("ignores WhatsApp formatting when the identity is not whatsapp-shaped", () => {
    // Defensive: B2 always pairs whatsapp_organic_discovery with a
    // whatsapp identity, but if the identity is something else we
    // shouldn't fabricate a phone number.
    const r = formatProposalProvenance(
      "worm:whatsapp_organic_discovery",
      slackIdentity(),
    );
    expect(r.kind).toBe("whatsapp_dm");
    expect(r.highlight).toBe("");
    expect(r.label).toBe("Proposed from WhatsApp DM");
  });

  it("renders Slack roster proposals with their canonical line", () => {
    const r = formatProposalProvenance(
      "worm:slack_roster",
      slackIdentity(),
    );
    expect(r.kind).toBe("slack_roster");
    expect(r.label).toBe("Proposed from Slack workspace roster");
    expect(r.highlight).toBe("");
  });

  it("renders admin_invite as 'Invited by an admin'", () => {
    const r = formatProposalProvenance("admin_invite", slackIdentity());
    expect(r.kind).toBe("admin_invite");
    expect(r.label).toBe("Invited by an admin");
  });

  it("renders a real admin UUID as a generic 'Proposed by admin'", () => {
    const r = formatProposalProvenance(
      "11111111-2222-3333-4444-555566667777",
      slackIdentity(),
    );
    expect(r.kind).toBe("admin_invite");
    expect(r.label).toBe("Proposed by admin");
  });

  it("falls back to 'Proposed by system' for null attribution", () => {
    const r = formatProposalProvenance(null, slackIdentity());
    expect(r.kind).toBe("system");
    expect(r.label).toBe("Proposed by system");
  });

  it("falls back to verbatim attribution for unknown strings", () => {
    // Surfaces honestly — better than burying an unmapped encoding.
    const r = formatProposalProvenance("worm", slackIdentity());
    expect(r.kind).toBe("system");
    expect(r.label).toBe("Proposed by worm");
    expect(r.highlight).toBe("worm");
  });

  it("does not render '+' when WhatsApp jid is malformed", () => {
    // formatChannelDisplay returns the raw jid for unknown shapes;
    // the helper just passes it through (no +E.164 fabrication).
    const id: PersonIdentityRow = {
      platform: "whatsapp",
      platformUserId: "not-a-real-jid",
      proposedBy: "worm:whatsapp_organic_discovery",
    };
    const r = formatProposalProvenance(
      "worm:whatsapp_organic_discovery",
      id,
    );
    expect(r.kind).toBe("whatsapp_dm");
    // The display helper falls back to the raw id, so the label
    // contains the verbatim jid string, not a fake phone.
    expect(r.label).toContain("not-a-real-jid");
  });
});

describe("relativeTime", () => {
  it("returns empty for null / undefined", () => {
    expect(relativeTime(null)).toBe("");
    expect(relativeTime(undefined)).toBe("");
  });

  it("returns 'just now' for sub-minute deltas", () => {
    const iso = new Date(Date.now() - 5_000).toISOString();
    expect(relativeTime(iso)).toBe("just now");
  });

  it("returns N minutes ago for sub-hour deltas", () => {
    const iso = new Date(Date.now() - 2 * 60_000).toISOString();
    expect(relativeTime(iso)).toBe("2 minutes ago");
  });

  it("singularizes '1 minute ago'", () => {
    const iso = new Date(Date.now() - 60_000).toISOString();
    expect(relativeTime(iso)).toBe("1 minute ago");
  });

  it("returns N hours ago for sub-day deltas", () => {
    const iso = new Date(Date.now() - 3 * 3_600_000).toISOString();
    expect(relativeTime(iso)).toBe("3 hours ago");
  });

  it("returns 'yesterday' for ~24h-48h ago", () => {
    const iso = new Date(Date.now() - 26 * 3_600_000).toISOString();
    expect(relativeTime(iso)).toBe("yesterday");
  });

  it("falls back to a UTC date for >30d", () => {
    const iso = "2024-01-15T10:00:00Z";
    expect(relativeTime(iso)).toBe("2024-01-15");
  });

  it("returns the raw ISO when parsing fails", () => {
    expect(relativeTime("not-a-date")).toBe("not-a-date");
  });
});
