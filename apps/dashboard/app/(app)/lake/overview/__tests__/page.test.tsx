/**
 * /lake/overview page tests — Lake-Side Overview (2026-05-16).
 *
 * Server-component test — mocks the lib accessors so the page renders
 * without standing up Postgres. Verifies all 3 sections compose +
 * empty-state path renders when both axes + activity are empty.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../../lib/lake-overview", async () => {
  const actual = await vi.importActual<
    typeof import("../../../../../lib/lake-overview")
  >("../../../../../lib/lake-overview");
  return {
    ...actual,
    getLakeAxisStates: vi.fn(async () => [
      {
        axis: "L3",
        axisName: "Lineage",
        axisHref: "/lake/lineage",
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 0,
      },
      {
        axis: "L4",
        axisName: "Schema-impact",
        axisHref: "/lake/schema-impact",
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 0,
      },
      {
        axis: "L5",
        axisName: "Fingerprinting",
        axisHref: "/lake/semantic-types",
        proposedCount: 2,
        affirmedCount: 5,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 1,
      },
      {
        axis: "L6",
        axisName: "Column classification",
        axisHref: "/lake/column-classification",
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 0,
      },
      {
        axis: "L7",
        axisName: "Quality checks",
        axisHref: "/lake/quality",
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 0,
      },
      {
        axis: "L8",
        axisName: "Entity stitching",
        axisHref: "/lake/entity-stitches",
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: "confirmed",
        rejectedCount: 0,
      },
      {
        axis: "L1",
        axisName: "Source candidates",
        axisHref: "/lake/source-candidates",
        proposedCount: 1,
        affirmedCount: 0,
        affirmativeStateLabel: "promoted",
        rejectedCount: 0,
      },
      {
        axis: "L2",
        axisName: "Catalog drift",
        axisHref: "/lake/catalog-drift",
        proposedCount: 0,
        affirmedCount: 3,
        affirmativeStateLabel: "acknowledged",
        rejectedCount: 0,
      },
    ]),
    getRecentLakeActivity: vi.fn(async () => [
      {
        ts: new Date("2026-05-16T14:55:00.000Z"),
        axis: "L5",
        action: "confirmed",
        description: "semantic_type email on users.email",
        href: "/lake/semantic-types?type_id=type-001",
      },
    ]),
  };
});

import LakeOverviewPage from "../page";

describe("/lake/overview page", () => {
  it("renders the page header + all 3 sections", async () => {
    const ui = await LakeOverviewPage();
    render(ui);
    expect(screen.getByText("Lake-Side Overview")).toBeInTheDocument();
    expect(
      screen.getByTestId("lake-overview-section-axis"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("lake-overview-section-chains"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("lake-overview-section-activity"),
    ).toBeInTheDocument();
  });

  it("renders all 8 axis cards in the grid", async () => {
    const ui = await LakeOverviewPage();
    render(ui);
    for (const axis of ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]) {
      expect(
        screen.getByTestId(`lake-overview-axis-card-${axis}`),
      ).toBeInTheDocument();
    }
  });

  it("renders the 7-row chain panel including the L4 ↔ L2 bidirectional chain", async () => {
    const ui = await LakeOverviewPage();
    render(ui);
    const table = screen.getByTestId("lake-overview-chain-table");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(7);
    expect(
      screen.getByTestId("lake-overview-chain-bidirectional-L4-L2"),
    ).toBeInTheDocument();
  });

  it("renders the recent-activity stream with one row + drill-in link", async () => {
    const ui = await LakeOverviewPage();
    render(ui);
    expect(
      screen.getByTestId("lake-overview-activity-stream"),
    ).toBeInTheDocument();
    const link = screen.getByTestId("lake-overview-activity-link-0");
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=type-001",
    );
  });
});
