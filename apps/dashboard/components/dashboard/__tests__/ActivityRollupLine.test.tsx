/**
 * W4-C — ActivityRollupLine.
 *
 * Three render modes:
 *
 *   - silent  (isSilent=true)  → "No activity in the last 24 hours."
 *   - populated (single platform)   → "Last 24h · 12 Slack messages · 1 process map proposed · 0 KPI proposals"
 *   - populated (multi-platform)    → Slack + WhatsApp segments rendered, ordered by count DESC
 *
 * Pins:
 *   1. Slack-only rendering byte-identical to single-platform when WhatsApp count is 0.
 *   2. Per-platform segment uses <PlatformBadge> for visual consistency with /trace.
 *   3. Process-map / KPI counts always render (platform-agnostic).
 *   4. Honest empty state (no fabricated zeros) when ledger is silent.
 *   5. Counts ordered DESC by activity; ties broken by canonical PLATFORMS order.
 *   6. Singular "1 process map proposed" / "1 KPI proposal" when count is 1.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ActivityRollupLine } from "../ActivityRollupLine";
import type { ActivityRollup } from "../../../lib/ledger-client";

const SILENT: ActivityRollup = {
  windowSeconds: 24 * 60 * 60,
  totalMessages: 0,
  perPlatform: [],
  processMaps: 0,
  kpiProposals: 0,
  isSilent: true,
};

const SLACK_ONLY: ActivityRollup = {
  windowSeconds: 24 * 60 * 60,
  totalMessages: 12,
  perPlatform: [{ platform: "slack", count: 12, unitLabel: "messages" }],
  processMaps: 1,
  kpiProposals: 0,
  isSilent: false,
};

const MULTI_PLATFORM: ActivityRollup = {
  windowSeconds: 24 * 60 * 60,
  totalMessages: 16,
  perPlatform: [
    { platform: "slack", count: 12, unitLabel: "messages" },
    { platform: "whatsapp", count: 4, unitLabel: "DMs" },
  ],
  processMaps: 1,
  kpiProposals: 0,
  isSilent: false,
};

const WHATSAPP_FIRST: ActivityRollup = {
  // WhatsApp outpaced Slack today — count DESC ordering must surface
  // WhatsApp's segment first.
  windowSeconds: 24 * 60 * 60,
  totalMessages: 11,
  perPlatform: [
    { platform: "whatsapp", count: 7, unitLabel: "DMs" },
    { platform: "slack", count: 4, unitLabel: "messages" },
  ],
  processMaps: 2,
  kpiProposals: 3,
  isSilent: false,
};

describe("ActivityRollupLine (W4-C)", () => {
  it("renders the honest empty line when isSilent=true", () => {
    render(<ActivityRollupLine rollup={SILENT} />);
    const tile = screen.getByTestId("activity-rollup-line");
    expect(tile.getAttribute("data-state")).toBe("empty");
    const empty = screen.getByTestId("activity-rollup-empty");
    expect(empty.textContent?.toLowerCase()).toContain("no activity");
    // Should NOT render fabricated zero rows.
    expect(screen.queryByTestId("activity-rollup-platform-slack")).toBeNull();
    expect(screen.queryByTestId("activity-rollup-platform-whatsapp")).toBeNull();
    expect(screen.queryByTestId("activity-rollup-process-maps")).toBeNull();
    expect(screen.queryByTestId("activity-rollup-kpi-proposals")).toBeNull();
  });

  it("renders the 'Last 24h' window label by default", () => {
    render(<ActivityRollupLine rollup={SLACK_ONLY} />);
    const content = screen.getByTestId("activity-rollup-content");
    expect(content.textContent).toContain("Last 24h");
  });

  it("renders Slack-only rendering with one platform segment + process-map + KPI tail", () => {
    render(<ActivityRollupLine rollup={SLACK_ONLY} />);
    const tile = screen.getByTestId("activity-rollup-line");
    expect(tile.getAttribute("data-state")).toBe("populated");

    // Slack segment present.
    const slack = screen.getByTestId("activity-rollup-platform-slack");
    expect(slack.textContent).toContain("12");
    expect(slack.textContent?.toLowerCase()).toContain("message");

    // WhatsApp segment NOT rendered (zero count → omitted).
    expect(screen.queryByTestId("activity-rollup-platform-whatsapp")).toBeNull();

    // Process-map + KPI tail always render (platform-agnostic).
    const procs = screen.getByTestId("activity-rollup-process-maps");
    expect(procs.textContent).toContain("1");
    // Singular form for count=1.
    expect(procs.textContent).toContain("process map");
    expect(procs.textContent).not.toContain("process maps");

    const kpis = screen.getByTestId("activity-rollup-kpi-proposals");
    expect(kpis.textContent).toContain("0");
    // Plural form for count=0.
    expect(kpis.textContent).toContain("KPI proposals");
  });

  it("renders multi-platform with both segments, ordered by count DESC", () => {
    render(<ActivityRollupLine rollup={MULTI_PLATFORM} />);
    const slack = screen.getByTestId("activity-rollup-platform-slack");
    const whatsapp = screen.getByTestId("activity-rollup-platform-whatsapp");
    expect(slack).toBeTruthy();
    expect(whatsapp).toBeTruthy();
    // Slack (12) first; WhatsApp (4) second. Compare DOM position via
    // compareDocumentPosition rather than fragile string-index lookups
    // (numbers like "4" can appear inside "Last 24h").
    const slackBefore = slack.compareDocumentPosition(whatsapp);
    expect(slackBefore & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Right unit labels.
    expect(slack.textContent).toContain("messages");
    expect(whatsapp.textContent).toContain("DMs");
  });

  it("re-orders segments when WhatsApp outpaces Slack", () => {
    render(<ActivityRollupLine rollup={WHATSAPP_FIRST} />);
    const slack = screen.getByTestId("activity-rollup-platform-slack");
    const whatsapp = screen.getByTestId("activity-rollup-platform-whatsapp");
    // WhatsApp (7) first; Slack (4) second.
    const waBefore = whatsapp.compareDocumentPosition(slack);
    expect(waBefore & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("uses singular phrasing for KPI proposals when count = 1", () => {
    render(
      <ActivityRollupLine
        rollup={{
          ...SLACK_ONLY,
          kpiProposals: 1,
        }}
      />,
    );
    const kpis = screen.getByTestId("activity-rollup-kpi-proposals");
    // "1 KPI proposal" — no trailing 's'.
    expect(kpis.textContent).toContain("1");
    expect(kpis.textContent).toMatch(/KPI proposal(?!s)/);
  });

  it("uses plural phrasing for process maps when count > 1", () => {
    render(
      <ActivityRollupLine
        rollup={{
          ...SLACK_ONLY,
          processMaps: 3,
        }}
      />,
    );
    const procs = screen.getByTestId("activity-rollup-process-maps");
    expect(procs.textContent).toContain("3");
    expect(procs.textContent).toContain("process maps");
  });

  it("renders the platform badge inside each platform segment", () => {
    render(<ActivityRollupLine rollup={MULTI_PLATFORM} />);
    // The shared <PlatformBadge> renders with testId
    // 'activity-rollup-badge-<platform>' (we passed the override).
    const slackBadge = screen.getByTestId("activity-rollup-badge-slack");
    expect(slackBadge.getAttribute("data-platform")).toBe("slack");
    const waBadge = screen.getByTestId("activity-rollup-badge-whatsapp");
    expect(waBadge.getAttribute("data-platform")).toBe("whatsapp");
  });

  it("renders honest empty state for the 24h window with the right copy", () => {
    render(<ActivityRollupLine rollup={SILENT} />);
    const empty = screen.getByTestId("activity-rollup-empty");
    expect(empty.textContent).toContain("24h");
    expect(empty.textContent?.toLowerCase()).toContain("no activity");
  });

  it("includes the count as text content within each platform segment", () => {
    render(<ActivityRollupLine rollup={MULTI_PLATFORM} />);
    const slack = screen.getByTestId("activity-rollup-platform-slack");
    // Use within() so we can check the count number lands inside the
    // segment, not just somewhere on the page.
    const slackContent = within(slack);
    expect(slackContent.getByText("12")).toBeTruthy();
  });

  it("formats other windows as 'Last <n>h' or 'Last <n>d'", () => {
    const oneHour: ActivityRollup = { ...SLACK_ONLY, windowSeconds: 60 * 60 };
    const { unmount } = render(<ActivityRollupLine rollup={oneHour} />);
    expect(screen.getByTestId("activity-rollup-content").textContent).toContain(
      "Last 1h",
    );
    unmount();

    const week: ActivityRollup = { ...SLACK_ONLY, windowSeconds: 7 * 24 * 60 * 60 };
    render(<ActivityRollupLine rollup={week} />);
    expect(screen.getByTestId("activity-rollup-content").textContent).toContain(
      "Last 7d",
    );
  });
});
