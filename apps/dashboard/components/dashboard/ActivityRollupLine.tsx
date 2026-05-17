/**
 * W4-C — /dashboard activity rollup per-platform line.
 *
 * Renders a one-line editorial digest of the last-24h ledger activity
 * with per-platform message counts, e.g.:
 *
 *   Last 24h · 12 Slack messages · 4 WhatsApp DMs · 1 process map proposed · 0 KPI proposals
 *
 * Design choices:
 *
 *   * Per-platform counts come from ``inferPlatformFromChannelId`` (W4-A
 *     export) and are visually labelled with the shared
 *     ``<PlatformBadge>`` chip (W4-B) so the visual language matches the
 *     /trace decision-chain badges.
 *   * Counts sort DESC (most-active platform first); zero-count platforms
 *     are OMITTED rather than rendered as "0 X" so a Slack-only deployment
 *     looks byte-identical to pre-W4-C. Capability-honest: missing platform
 *     means "no activity in this window," not "zero events worth noting."
 *   * Process-map and KPI counts are platform-agnostic and always render —
 *     they ground the line for tenants whose chatter platforms haven't
 *     moved in 24h but whose worm has been productive elsewhere.
 *   * When every counter is zero we surface a single honest line per
 *     CLAUDE.md §9 — "No activity in the last 24 hours." — instead of
 *     fabricating "0 Slack messages · 0 WhatsApp DMs · …".
 *
 * The component is presentational. The accessor lives in
 * ``lib/ledger-client.getActivityRollup`` and is read server-side from
 * ``app/(app)/dashboard/page.tsx``; the rollup is plumbed in as a prop.
 *
 * Editorial chrome — square corners, wb-mono eyebrow + counters, serif
 * tail. No Tailwind, no emojis. Matches the WormActivityTile's tile
 * styling.
 */
import type { CSSProperties } from "react";
import type { ActivityRollup } from "../../lib/ledger-client";
import { PlatformBadge } from "../shared/PlatformBadge";

export interface ActivityRollupLineProps {
  rollup: ActivityRollup;
}

/**
 * Pretty-print the lookback window. 24h is rendered as "Last 24h"; other
 * common windows fall back to "Last <n> hours" / "Last <n> minutes" /
 * "Last <n> days" — the renderer picks the coarsest unit that doesn't
 * round to zero.
 */
function formatWindowLabel(seconds: number): string {
  if (seconds >= 24 * 60 * 60) {
    const days = Math.round(seconds / (24 * 60 * 60));
    if (days === 1) return "Last 24h";
    return `Last ${days}d`;
  }
  if (seconds >= 60 * 60) {
    const hours = Math.round(seconds / (60 * 60));
    return `Last ${hours}h`;
  }
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `Last ${minutes}m`;
}

export function ActivityRollupLine({ rollup }: ActivityRollupLineProps) {
  const windowLabel = formatWindowLabel(rollup.windowSeconds);

  if (rollup.isSilent) {
    return (
      <section
        data-testid="activity-rollup-line"
        data-state="empty"
        style={tileStyle}
      >
        <span style={eyebrowStyle} className="wb-mono">
          {windowLabel.toLowerCase()} · digest
        </span>
        <p style={emptyBodyStyle} data-testid="activity-rollup-empty">
          No activity in the last {windowLabel.replace("Last ", "")}.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="activity-rollup-line"
      data-state="populated"
      style={tileStyle}
    >
      <span style={eyebrowStyle} className="wb-mono">
        {windowLabel.toLowerCase()} · digest
      </span>
      <p style={lineStyle} data-testid="activity-rollup-content">
        <strong style={windowStrongStyle}>{windowLabel}</strong>
        {rollup.perPlatform.map((line) => (
          <span
            key={line.platform}
            data-testid={`activity-rollup-platform-${line.platform}`}
            style={segmentStyle}
          >
            <span style={separatorStyle}>·</span>
            <span style={countStyle}>{line.count}</span>
            <PlatformBadge
              platform={line.platform}
              showTooltip={true}
              testId={`activity-rollup-badge-${line.platform}`}
            />
            <span style={unitStyle}>{line.unitLabel}</span>
          </span>
        ))}
        <span
          data-testid="activity-rollup-process-maps"
          style={segmentStyle}
        >
          <span style={separatorStyle}>·</span>
          <span style={countStyle}>{rollup.processMaps}</span>
          <span style={unitStyle}>
            process map{rollup.processMaps === 1 ? "" : "s"} proposed
          </span>
        </span>
        <span
          data-testid="activity-rollup-kpi-proposals"
          style={segmentStyle}
        >
          <span style={separatorStyle}>·</span>
          <span style={countStyle}>{rollup.kpiProposals}</span>
          <span style={unitStyle}>
            KPI proposal{rollup.kpiProposals === 1 ? "" : "s"}
          </span>
        </span>
      </p>
    </section>
  );
}

const tileStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "14px 18px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
};

const eyebrowStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const lineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 15,
  lineHeight: 1.55,
  color: "var(--wb-color-aged-ink)",
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 4,
};

const windowStrongStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontWeight: 600,
};

const segmentStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const separatorStyle: CSSProperties = {
  color: "var(--wb-color-hash-gray)",
  margin: "0 4px",
};

const countStyle: CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 500,
  color: "var(--wb-color-aged-ink)",
};

const unitStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  color: "var(--wb-color-hash-gray)",
};

const emptyBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-hash-gray)",
};
