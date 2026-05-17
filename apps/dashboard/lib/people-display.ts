/**
 * Phase W4-D — Person-proposal provenance helpers.
 *
 * The /people surface renders pending proposals with a one-liner that
 * tells the admin where the proposal came from. The discovery source
 * lives on the original `emit_person_proposed.proposed_by` field on the
 * ledger, surfaced here as `PersonIdentityRow.proposedBy`. Free-form by
 * convention — known shapes:
 *
 *   - `worm:whatsapp_organic_discovery`  → B2's WhatsApp DM organic
 *     discovery loop. Surface "Proposed from WhatsApp DM with +E.164" by
 *     reading the platform user id (a jid) and routing through D1's
 *     `formatChannelDisplay`.
 *   - `worm:slack_roster`                 → workspace-membership scrape.
 *     Surface "Proposed from Slack workspace roster".
 *   - `admin_invite`                      → manual invite.
 *     Surface "Invited by an admin".
 *   - any UUID                            → real admin id; we render
 *     "Proposed by admin" (the dashboard doesn't have the admin's name
 *     resolvable here without a separate lookup; keeping it generic
 *     beats fabricating).
 *   - anything else / null                → fall back to the verbatim
 *     `proposedBy` string (or "Proposed by system" when null).
 *
 * Pure string-shape transformations; no side effects, no IO.
 */
import { formatChannelDisplay } from "./whatsapp-display";
import type { PersonIdentityRow } from "./ledger-client.types";

export interface PersonProposalProvenance {
  /**
   * Headline label, e.g. "Proposed from WhatsApp DM with +5215512345678".
   * The phone / handle is wrapped in a leading marker so the caller can
   * style it (bold, mono) — see `phoneMarker`. Never `null`; always
   * prose-shaped.
   */
  label: string;
  /**
   * The phone-number / handle / id portion, when extractable. Lets the
   * caller render it in a distinct style (bold E.164, mono jid). Empty
   * string when there's nothing to highlight (e.g. "Proposed by system").
   */
  highlight: string;
  /**
   * Source kind, used for testid suffixes / styling tone.
   *   - "whatsapp_dm"       — B2's organic discovery encoding
   *   - "slack_roster"      — workspace roster scrape
   *   - "admin_invite"      — manual invite (and by-admin-uuid case)
   *   - "system"            — null / unknown / fall-through
   */
  kind: "whatsapp_dm" | "slack_roster" | "admin_invite" | "system";
}

/**
 * UUID v4-ish predicate. Mirrors the looser "looks like a UUID" check in
 * `ledger-client.ts:looksLikeUuid` — we reuse the shape locally to keep
 * the helper free of cross-file imports beyond the public types.
 */
function looksLikeUuid(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    s,
  );
}

/**
 * Format a Person proposal's provenance line.
 *
 * Inputs are the proposal's `proposedBy` attribution + the first
 * identity (which carries the platform + platform_user_id we may want to
 * surface inline, e.g. the WhatsApp jid as `+E.164`).
 *
 * @param proposedBy — the verbatim attribution string from
 *   `emit_person_proposed.proposed_by`. May be `null` / `undefined` for
 *   pre-D2 entries.
 * @param identity — the first identity on the proposal, used to pull
 *   the platform user id when the source is platform-rooted.
 */
export function formatProposalProvenance(
  proposedBy: string | null | undefined,
  identity: PersonIdentityRow | undefined,
): PersonProposalProvenance {
  if (proposedBy === "worm:whatsapp_organic_discovery") {
    // B2 always pairs the proposal with a WhatsApp DM jid; if the
    // identity is missing or wasn't whatsapp-shaped, fall back to a
    // bare label so we don't fabricate a phone.
    if (identity && identity.platform === "whatsapp") {
      const display = formatChannelDisplay(
        identity.platformUserId,
        "whatsapp",
        null,
      );
      // DM jids surface as `+E.164`; non-DM jids (group, lid) shouldn't
      // hit this branch in practice (B2 only proposes from DMs), but if
      // they do, we still render the helper's label honestly.
      return {
        label: `Proposed from WhatsApp DM with ${display.label}`,
        highlight: display.label,
        kind: "whatsapp_dm",
      };
    }
    return {
      label: "Proposed from WhatsApp DM",
      highlight: "",
      kind: "whatsapp_dm",
    };
  }

  if (proposedBy === "worm:slack_roster") {
    return {
      label: "Proposed from Slack workspace roster",
      highlight: "",
      kind: "slack_roster",
    };
  }

  if (proposedBy === "admin_invite") {
    return {
      label: "Invited by an admin",
      highlight: "",
      kind: "admin_invite",
    };
  }

  if (proposedBy && looksLikeUuid(proposedBy)) {
    // A real admin Person id. We don't have a name resolver here;
    // surface a generic line rather than the bare UUID.
    return {
      label: "Proposed by admin",
      highlight: "",
      kind: "admin_invite",
    };
  }

  if (proposedBy && proposedBy.trim()) {
    // Unknown attribution string — surface verbatim so debug-shaped
    // callers (e.g. "worm" alone, or a future encoding we haven't
    // mapped yet) still render something honest.
    return {
      label: `Proposed by ${proposedBy}`,
      highlight: proposedBy,
      kind: "system",
    };
  }

  // Null / empty fall-through.
  return {
    label: "Proposed by system",
    highlight: "",
    kind: "system",
  };
}

/**
 * Coarse relative-time helper for the proposal-card timestamp ("2 minutes
 * ago"). Editorial register; mirrors the helper inside
 * `dashboard/SlackWelcomeMoment.tsx` so the surface reads consistently.
 *
 * Returns the verbatim ISO string when parsing fails — never throws.
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const now = Date.now();
  const deltaMs = now - d.valueOf();
  if (deltaMs < 0) return iso;
  const seconds = Math.floor(deltaMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
