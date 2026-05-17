/**
 * Phase D1 — WhatsApp display helpers.
 */
import { describe, it, expect } from "vitest";
import {
  formatWhatsAppChannelId,
  formatChannelDisplay,
} from "../../lib/whatsapp-display";

describe("formatWhatsAppChannelId", () => {
  it("formats a DM jid as +E.164", () => {
    const r = formatWhatsAppChannelId("5511999998888@s.whatsapp.net");
    expect(r.label).toBe("+5511999998888");
    expect(r.hint).toBe("DM");
    expect(r.kind).toBe("dm");
  });

  it("formats a group jid with truncated id and hint", () => {
    const r = formatWhatsAppChannelId("120363025246125486@g.us");
    expect(r.label).toMatch(/WhatsApp Group · 120363/);
    expect(r.label).toContain("…");
    expect(r.kind).toBe("group");
  });

  it("uses the friendly name when provided for a group", () => {
    const r = formatWhatsAppChannelId(
      "120363025246125486@g.us",
      "Engineering Team",
    );
    expect(r.label).toBe("Engineering Team");
    expect(r.hint).toMatch(/group · 120363/);
    expect(r.kind).toBe("group");
  });

  it("falls back to raw jid for unknown shapes", () => {
    const r = formatWhatsAppChannelId("xxx@lid");
    expect(r.label).toBe("xxx@lid");
    expect(r.kind).toBe("unknown");
  });

  it("falls back to raw label when DM phone segment isn't all digits", () => {
    const r = formatWhatsAppChannelId("notaphone@s.whatsapp.net");
    expect(r.label).toBe("notaphone@s.whatsapp.net");
    expect(r.kind).toBe("dm");
  });

  it("does not truncate short group ids", () => {
    const r = formatWhatsAppChannelId("12345@g.us");
    expect(r.label).toContain("12345");
    expect(r.label).not.toContain("…");
  });
});

describe("formatChannelDisplay", () => {
  it("uses the WhatsApp formatter when platform is whatsapp", () => {
    const r = formatChannelDisplay(
      "5511999998888@s.whatsapp.net",
      "whatsapp",
      null,
    );
    expect(r.label).toBe("+5511999998888");
  });

  it("returns the registered name for Slack channels when present", () => {
    const r = formatChannelDisplay("C0AVDAEEZ", "slack", "general");
    expect(r.label).toBe("general");
  });

  it("falls back to channel_id for Slack channels without a registered name", () => {
    const r = formatChannelDisplay("C0AVDAEEZ", "slack", null);
    expect(r.label).toBe("C0AVDAEEZ");
  });

  it("returns the channel_id literal when the platform is unknown", () => {
    const r = formatChannelDisplay("opaque-id", undefined, null);
    expect(r.label).toBe("opaque-id");
  });
});
