/**
 * Phase D1 — WhatsApp display helpers.
 *
 * Channel-id formatting utilities for the /channels surface. WhatsApp jids
 * are not human-friendly (`120363025246125486@g.us`), so the dashboard
 * derives display names client-side. Three jid shapes:
 *
 *   - DM:    `<phone>@s.whatsapp.net`              → `+<E.164>`
 *   - Group: `<id>@g.us`                          → `WhatsApp Group · <id…>`
 *   - LID:   `<id>@lid` or `<id>@broadcast`       → fall back to raw id
 *
 * Group display intentionally truncates the id (`120363…`) — full ids are
 * 18+ digits and not useful for orientation. When a future projection
 * surfaces a real subject (via `groups info` from the Baileys adapter), the
 * caller passes it through `friendlyName` and the helper short-circuits.
 *
 * Reads only ledger projections (the caller's responsibility); these
 * functions are pure string-shape transformations with no side effects.
 */

export interface WhatsAppDisplay {
  /** Friendly label for the row (`+5511999999999`, `WhatsApp Group · 1203…`). */
  label: string;
  /** Sub-label / hint (`DM`, `group`, raw jid for unknown shapes). */
  hint: string;
  /**
   * Whether this channel is a DM, a group, or unknown. Drives icon /
   * affordance choice in the renderer (group lurker policy is surfaced
   * with extra emphasis vs. a DM).
   */
  kind: "dm" | "group" | "unknown";
}

/**
 * Format a WhatsApp jid for display.
 *
 * @param channelId — the raw jid as stored on the ledger.
 * @param friendlyName — optional projection-supplied subject. When the
 *   caller has folded a `groups info` write into a per-channel name, pass
 *   it here and the helper preserves it. Empty / null falls back to the
 *   default truncation.
 */
export function formatWhatsAppChannelId(
  channelId: string,
  friendlyName?: string | null,
): WhatsAppDisplay {
  // DM jid: `<digits>@s.whatsapp.net`
  if (channelId.endsWith("@s.whatsapp.net")) {
    const phone = channelId.slice(0, -"@s.whatsapp.net".length);
    if (/^\d+$/.test(phone)) {
      return { label: `+${phone}`, hint: "DM", kind: "dm" };
    }
    return { label: channelId, hint: "DM", kind: "dm" };
  }
  // Group jid: `<digits>@g.us`
  if (channelId.endsWith("@g.us")) {
    const groupId = channelId.slice(0, -"@g.us".length);
    if (friendlyName && friendlyName.trim()) {
      return {
        label: friendlyName.trim(),
        hint: `group · ${truncateGroupId(groupId)}`,
        kind: "group",
      };
    }
    return {
      label: `WhatsApp Group · ${truncateGroupId(groupId)}`,
      hint: "group",
      kind: "group",
    };
  }
  // Unknown shape — fall back to raw.
  return { label: channelId, hint: "channel", kind: "unknown" };
}

function truncateGroupId(groupId: string): string {
  if (groupId.length <= 9) return groupId;
  return `${groupId.slice(0, 6)}…`;
}

/**
 * Return a human-readable label for a Slack/Discord/Teams/WhatsApp channel,
 * regardless of platform. Slack falls through to the registered channel
 * name (already rendered upstream); WhatsApp routes through the helper
 * above. Other platforms return the raw id.
 */
export function formatChannelDisplay(
  channelId: string,
  platform: string | undefined,
  registeredName: string | null | undefined,
): WhatsAppDisplay {
  if (platform === "whatsapp") {
    return formatWhatsAppChannelId(channelId, registeredName);
  }
  // Slack/Discord/Teams/etc. — registered name when present, else the id.
  return {
    label: (registeredName && registeredName.trim()) || channelId,
    hint: platform ?? "channel",
    kind: "unknown",
  };
}
