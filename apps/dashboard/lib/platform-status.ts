/**
 * Channel-platform capability honesty.
 *
 * The single source of truth for which channel platforms the dashboard
 * surfaces, what their production-readiness status is, and what env
 * variables admins must set to enable them.
 *
 * Mirrors the Python ``ChannelAdapter.status`` / ``status_note``
 * declarations at packages/channel-adapters/src/wormbase_channel_adapters/.
 * Cross-language schema sync is manual — when promoting an adapter
 * past skeleton, update both this module and the Python adapter class
 * in the same change.
 *
 * Status grading:
 *   - production: every method (authenticate, install, listen, send,
 *     file_upload, list_workspace_members) is wired against the real
 *     platform.
 *   - preview: install + listen are real; send / file_upload may be
 *     stubbed. Admins CAN connect; the worm will lurk and ingest, just
 *     not yet reply. Buttons render with a "Preview" badge.
 *   - coming_soon: skeleton only. Buttons render greyed out with
 *     "Coming soon" text; no OAuth flow.
 *
 * The onboarding agent (parallel workstream) consumes ``envHint`` to
 * render "Configure ENV_X + ENV_Y" disabled-state buttons when
 * required env tokens aren't set on the server. If both edits land in
 * conflict, harmonize on this module — it is the canonical source.
 */

export type PlatformStatus = "production" | "preview" | "coming_soon";

/**
 * Channel-adapter capability literal — TS mirror of Python ``ChannelCap``
 * (packages/channel-adapters/src/wormbase_channel_adapters/types.py:32).
 * Keep in lockstep with the Python alias's documented values; add new
 * literals here when a new capability surfaces upstream.
 */
export type Capability =
  | "ingest"
  | "send"
  | "file_upload"
  | "dm"
  | "voice";

export type PlatformSlug =
  | "slack"
  | "discord"
  | "teams"
  | "signal"
  | "whatsapp";

export interface PlatformDescriptor {
  /** Stable short slug used as id in routes, ledger entries, and CSS hooks. */
  platform: PlatformSlug;
  /** User-facing label for cards and buttons. */
  label: string;
  /** Capability-honesty grade. */
  status: PlatformStatus;
  /** Short user-facing note explaining what works / doesn't. ≤ 200 chars. */
  statusNote: string;
  /**
   * Env-var hint shown when the OAuth flow is not configured server-side.
   * Onboarding agent renders this in a "Configure: $envHint" disabled
   * state. Undefined for coming_soon platforms (no env to set yet).
   */
  envHint?: string;
  /**
   * Optional capability set mirror of the Python adapter's ``capability``
   * attribute. Opt-in per platform: when present, the pinned-mirror
   * contract test asserts it matches the Python adapter declaration.
   * When absent (default), the contract test only verifies (platform,
   * status). Added 2026-05-07 to surface post-C-wave WhatsApp capability
   * honesty without forcing every existing descriptor to migrate at once.
   */
  capabilities?: Capability[];
}

/**
 * Day-one platform descriptor list. ORDER MATTERS — buttons render in
 * this sequence; production platforms first, previews next, coming_soon
 * last (or filtered out by the renderer).
 */
export const PLATFORMS: PlatformDescriptor[] = [
  {
    platform: "slack",
    label: "Slack",
    status: "production",
    statusNote:
      "Real OAuth, ingest, send, file_upload, DM. Production-grade.",
    envHint: "SLACK_CLIENT_ID + SLACK_CLIENT_SECRET",
  },
  {
    platform: "discord",
    label: "Discord",
    status: "preview",
    statusNote:
      "Install + listen are real (the worm will lurk). Send + file_upload are skeletal — full bot wiring lands in v1.5.",
    envHint: "DISCORD_CLIENT_ID + DISCORD_CLIENT_SECRET",
  },
  {
    platform: "teams",
    label: "Microsoft Teams",
    status: "preview",
    statusNote:
      "Install + listen are real (the worm will lurk). Send + file_upload are skeletal — Bot Framework wiring lands in v1.5.",
    envHint: "TEAMS_CLIENT_ID + TEAMS_CLIENT_SECRET + TEAMS_TENANT_ID",
  },
  {
    platform: "signal",
    label: "Signal",
    status: "coming_soon",
    statusNote:
      "Coming soon — Signal adapter design lands in v1.5 (signal-cli bridge).",
  },
  {
    platform: "whatsapp",
    label: "WhatsApp",
    status: "preview",
    statusNote:
      "Preview. Ingest+DM+send via OpenClaw Baileys (unofficial WA Web; ToS test-numbers-only). Send via CLI subprocess; needs operator scopes. HTTP route pending #73016; log grammar unverified.",
    envHint: "WHATSAPP_ACCOUNT_ID",
    capabilities: ["ingest", "dm", "send"],
  },
];

export function platformBySlug(slug: string): PlatformDescriptor | null {
  return PLATFORMS.find((p) => p.platform === slug) ?? null;
}

export function platformsByStatus(
  status: PlatformStatus,
): PlatformDescriptor[] {
  return PLATFORMS.filter((p) => p.status === status);
}

/**
 * Whether the running server has env tokens for a given platform's
 * OAuth flow. Component code calls this with values resolved server-side
 * (via env or config); this module knows the SHAPE, not the values.
 *
 * The onboarding agent's server endpoints surface configured/unconfigured
 * status; this helper is for dashboard-side rendering of the disabled
 * "Configure: $envHint" button state.
 */
export function isPlatformConfigured(
  descriptor: PlatformDescriptor,
  envState: { [key: string]: boolean } | undefined,
): boolean {
  if (descriptor.status === "coming_soon") {
    return false;
  }
  if (!descriptor.envHint || !envState) {
    return false;
  }
  // envHint is human-readable like "X + Y"; the caller provides envState
  // keyed by the same env-var names. We split on "+" and trim.
  const required = descriptor.envHint
    .split("+")
    .map((s) => s.trim())
    .filter(Boolean);
  return required.every((key) => envState[key] === true);
}
