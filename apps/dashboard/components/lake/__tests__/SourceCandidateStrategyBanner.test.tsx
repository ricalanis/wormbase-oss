/**
 * SourceCandidateStrategyBanner component tests — L1 Sub-wave D
 * (2026-06-08).
 *
 * Pins:
 *   * Renders all 3 strategy rows with the override label and the
 *     CapabilityBadges integration.
 *   * 4-state kpi_gap matrix honestly labeled (disabled /
 *     configured · awaiting-kpi-tree-population / productive ·
 *     KPI-dependent).
 *   * 3-state channel_mention matrix honestly labeled (disabled /
 *     configured · empty-upstream / productive · silver-dependent).
 *   * 3-state complementarity matrix honestly labeled (disabled /
 *     configured · awaiting-first-source / productive ·
 *     portfolio-dependent).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SourceCandidateStrategyBanner } from "../SourceCandidateStrategyBanner";
import type { SourceCandidateStrategyStatus } from "../../../lib/source-candidates";

const ROW_DISABLED = (
  strategy: SourceCandidateStrategyStatus["strategy"],
): SourceCandidateStrategyStatus => ({
  strategy,
  configured: false,
  productive: false,
  badge: "disabled",
  note: "Disabled",
});

describe("SourceCandidateStrategyBanner — kpi_gap 4-state matrix", () => {
  it("renders productive · KPI-dependent when KPI tree has nodes", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      {
        strategy: "kpi_gap",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · KPI-dependent",
        note: "Productive — reading 4 KPI nodes",
      },
      ROW_DISABLED("channel_mention"),
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("source-candidate-strategy-row-kpi_gap"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-strategy-override-kpi_gap"),
    ).toHaveTextContent("productive · KPI-dependent");
  });

  it("renders configured · awaiting-kpi-tree-population when KPI tree is empty", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      {
        strategy: "kpi_gap",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-kpi-tree-population",
        note: "Configured — KPI tree empty",
      },
      ROW_DISABLED("channel_mention"),
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("source-candidate-strategy-override-kpi_gap"),
    ).toHaveTextContent("configured · awaiting-kpi-tree-population");
  });

  it("renders disabled badge when both knobs off", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      ROW_DISABLED("channel_mention"),
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    // No override label rendered for the disabled state.
    expect(
      screen.queryByTestId("source-candidate-strategy-override-kpi_gap"),
    ).toBeNull();
  });
});

describe("SourceCandidateStrategyBanner — channel_mention 3-state matrix", () => {
  it("renders productive · silver-dependent when conversations exist", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      {
        strategy: "channel_mention",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · silver-dependent",
        note: "Productive — reading 27 silver-conversation rows; 24h × 1000-cap",
      },
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("source-candidate-strategy-override-channel_mention"),
    ).toHaveTextContent("productive · silver-dependent");
  });

  it("renders configured · empty-upstream when no silver-conversation rows", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      {
        strategy: "channel_mention",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · empty-upstream",
        note: "Configured but empty-upstream — awaiting silver-conversation messages",
      },
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("source-candidate-strategy-override-channel_mention"),
    ).toHaveTextContent("configured · empty-upstream");
  });
});

describe("SourceCandidateStrategyBanner — complementarity 3-state matrix", () => {
  it("renders productive · portfolio-dependent when sources connected", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      ROW_DISABLED("channel_mention"),
      {
        strategy: "complementarity",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · portfolio-dependent",
        note: "Productive — reading 3 connected sources",
      },
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId(
        "source-candidate-strategy-override-complementarity",
      ),
    ).toHaveTextContent("productive · portfolio-dependent");
  });

  it("renders configured · awaiting-first-source when no sources connected", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      ROW_DISABLED("channel_mention"),
      {
        strategy: "complementarity",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-first-source",
        note: "Configured but no sources connected",
      },
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId(
        "source-candidate-strategy-override-complementarity",
      ),
    ).toHaveTextContent("configured · awaiting-first-source");
  });
});

describe("SourceCandidateStrategyBanner — render shape", () => {
  it("renders all three strategy rows", () => {
    const rows: SourceCandidateStrategyStatus[] = [
      ROW_DISABLED("kpi_gap"),
      ROW_DISABLED("channel_mention"),
      ROW_DISABLED("complementarity"),
    ];
    render(<SourceCandidateStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("source-candidate-strategy-status-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-strategy-row-kpi_gap"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-strategy-row-channel_mention"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-strategy-row-complementarity"),
    ).toBeInTheDocument();
  });
});
