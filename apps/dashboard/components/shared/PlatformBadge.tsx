/**
 * PlatformBadge — small chip surfacing the channel platform of a ledger
 * entry (Slack / WhatsApp / Discord / Teams / Signal / …).
 *
 * Tone is keyed off the canonical ``PlatformDescriptor.status`` from
 * ``lib/platform-status.ts`` so the badge stays in lockstep with the
 * Python adapter declarations:
 *
 *   * production (Slack)            → green chip
 *   * preview (WhatsApp/Discord/Teams) → sepia chip (matches the
 *     "preview" pill in InstalledPlatforms — visually warns operators
 *     this transport is not yet production-graded)
 *   * coming_soon (Signal)          → muted chip
 *   * unknown / null                → renders nothing (honest empty
 *     state for legacy entries that pre-date the platform field)
 *
 * Reuses ``chipStyle`` + the chip tones already in use across the
 * /people surface so no new design tokens are introduced. Set
 * ``inferFromChannelId`` true to fall back to id-shape inference (Slack
 * ``C…`` / ``D…`` ids; WhatsApp ``@s.whatsapp.net`` / ``@g.us`` jids)
 * when the entry's payload doesn't carry an explicit ``platform``.
 *
 * Added 2026-05-07 (W4-B of the WhatsApp dashboard surfacing plan) so
 * the /trace/decision/[id] chain visualisation can label which channel
 * platform a chat-derived entry originated from. Kept platform-agnostic
 * — every dashboard surface that wants to badge a platform should
 * import from here rather than duplicate the tone mapping.
 */
import type { CSSProperties } from "react";
import { chipStyle, type ChipTone } from "../people/_styles";
import { platformBySlug } from "../../lib/platform-status";

export interface PlatformBadgeProps {
  /**
   * Platform slug from the ledger entry's payload args (e.g.
   * ``chat_received.platform``, ``chat_reply_executed.platform``,
   * ``conversation_sync.platform``). Undefined / null / empty string
   * → renders nothing.
   */
  platform?: string | null;
  /**
   * Optional channel id used as a fallback when ``platform`` is
   * absent. Matches Slack/WhatsApp id shapes; Discord/Teams/Signal
   * fall through to no badge.
   */
  channelId?: string | null;
  /** Surface a tooltip explaining the platform's capability status. */
  showTooltip?: boolean;
  /** Optional data-testid override for callers that need a stable hook. */
  testId?: string;
  /** Optional inline-style override (margins, etc.); merges over the chip base. */
  style?: CSSProperties;
}

const STATUS_TONE: Record<string, ChipTone> = {
  production: "green",
  preview: "sepia",
  coming_soon: "muted",
};

/**
 * Best-effort platform inference from a channel id when the entry's
 * payload doesn't carry an explicit ``platform`` field. Mirrors the
 * private ``inferPlatformFromChannelId`` helper in
 * ``lib/ledger-client.ts``; kept tiny here to avoid promoting a new
 * cross-module export.
 */
export function inferPlatformFromChannelId(
  channelId: string | null | undefined,
): string | null {
  if (!channelId) return null;
  if (channelId.endsWith("@s.whatsapp.net") || channelId.endsWith("@g.us")) {
    return "whatsapp";
  }
  if (/^[CD][A-Z0-9]{8,}$/.test(channelId)) {
    return "slack";
  }
  return null;
}

export function PlatformBadge({
  platform,
  channelId,
  showTooltip = true,
  testId,
  style,
}: PlatformBadgeProps) {
  // Resolve the platform: explicit field wins; fall back to channel-id
  // shape when the caller asked for inference. Empty / unknown → no
  // badge (honest empty state for legacy entries).
  const resolved =
    (platform && platform.length > 0 ? platform : null) ??
    inferPlatformFromChannelId(channelId);

  if (!resolved) return null;

  const descriptor = platformBySlug(resolved);
  const tone: ChipTone = descriptor
    ? STATUS_TONE[descriptor.status] ?? "neutral"
    : "neutral";
  const label = descriptor?.label ?? resolved;

  const chip = chipStyle(tone);
  // Trim the standard chip padding down — these badges land inline
  // with already-dense ledger metadata rows on /trace/decision and
  // shouldn't overpower the seq/kind/timestamp text.
  const merged: CSSProperties = {
    ...chip,
    fontSize: 9,
    padding: "1px 6px",
    letterSpacing: "0.1em",
    cursor: showTooltip && descriptor ? "help" : "default",
    ...style,
  };

  const title =
    showTooltip && descriptor
      ? `${descriptor.label} · ${descriptor.status}\n${descriptor.statusNote}`
      : undefined;

  return (
    <span
      className="wb-mono"
      data-testid={testId ?? `platform-badge-${resolved}`}
      data-platform={resolved}
      data-platform-status={descriptor?.status ?? "unknown"}
      title={title}
      style={merged}
    >
      {label}
    </span>
  );
}
