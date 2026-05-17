/**
 * RecentActivityStream tests — Lake-Side Overview (2026-05-16).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { RecentActivityRow } from "../../../lib/lake-overview";
import {
  RecentActivityStream,
  _formatRelative,
} from "../RecentActivityStream";

const NOW = new Date("2026-05-16T15:00:00.000Z");

function makeRow(overrides: Partial<RecentActivityRow> = {}): RecentActivityRow {
  return {
    ts: new Date("2026-05-16T14:57:00.000Z"),
    axis: "L5",
    action: "confirmed",
    description: "semantic_type email on users.email",
    href: "/lake/semantic-types?type_id=type-001",
    ...overrides,
  };
}

describe("RecentActivityStream", () => {
  it("renders the honest empty state when rows is empty", () => {
    render(<RecentActivityStream rows={[]} now={NOW} />);
    expect(
      screen.getByTestId("lake-overview-activity-empty"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("lake-overview-activity-stream")).toBeNull();
  });

  it("renders one row per activity entry with axis + action + description", () => {
    const rows = [
      makeRow({ axis: "L5", action: "confirmed", description: "sem 1" }),
      makeRow({
        ts: new Date("2026-05-16T14:30:00.000Z"),
        axis: "L2",
        action: "acknowledged",
        description: "drift 2",
      }),
    ];
    render(<RecentActivityStream rows={rows} now={NOW} />);
    expect(
      screen.getByTestId("lake-overview-activity-stream"),
    ).toBeInTheDocument();
    const r0 = screen.getByTestId("lake-overview-activity-row-0");
    expect(r0.getAttribute("data-axis")).toBe("L5");
    expect(r0.getAttribute("data-action")).toBe("confirmed");
    expect(r0.textContent).toContain("sem 1");
    const r1 = screen.getByTestId("lake-overview-activity-row-1");
    expect(r1.getAttribute("data-axis")).toBe("L2");
    expect(r1.getAttribute("data-action")).toBe("acknowledged");
  });

  it("renders drill-in link with the producer-side deep-link href", () => {
    render(<RecentActivityStream rows={[makeRow()]} now={NOW} />);
    const link = screen.getByTestId("lake-overview-activity-link-0");
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=type-001",
    );
  });

  it("formats relative timestamps within the last 5 minutes as Nm ago", () => {
    expect(
      _formatRelative(new Date("2026-05-16T14:57:00.000Z"), NOW),
    ).toBe("3m ago");
    expect(
      _formatRelative(new Date("2026-05-16T14:00:00.000Z"), NOW),
    ).toBe("1h ago");
    expect(
      _formatRelative(new Date("2026-05-15T15:00:00.000Z"), NOW),
    ).toBe("1d ago");
  });
});
