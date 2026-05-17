/**
 * AxisStateCard tests — Lake-Side Overview (2026-05-16).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { AxisStateRow } from "../../../lib/lake-overview";
import { AxisStateCard } from "../AxisStateCard";

function makeRow(overrides: Partial<AxisStateRow> = {}): AxisStateRow {
  return {
    axis: "L5",
    axisName: "Fingerprinting",
    axisHref: "/lake/semantic-types",
    proposedCount: 1,
    affirmedCount: 2,
    affirmativeStateLabel: "confirmed",
    rejectedCount: 0,
    ...overrides,
  };
}

describe("AxisStateCard", () => {
  it("renders axis label, descriptive name, counts, and detail link", () => {
    render(<AxisStateCard row={makeRow()} />);
    const card = screen.getByTestId("lake-overview-axis-card-L5");
    expect(card.textContent).toContain("L5");
    expect(card.textContent).toContain("Fingerprinting");
    expect(
      screen.getByTestId("lake-overview-axis-count-L5-proposed").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("lake-overview-axis-count-L5-affirmed").textContent,
    ).toBe("2");
    expect(
      screen.getByTestId("lake-overview-axis-count-L5-rejected").textContent,
    ).toBe("0");
    const link = screen.getByTestId("lake-overview-axis-link-L5");
    expect(link.getAttribute("href")).toBe("/lake/semantic-types");
  });

  it("renders the per-axis affirmative state label verbatim (confirmed/promoted/acknowledged)", () => {
    const { rerender } = render(
      <AxisStateCard
        row={makeRow({ axis: "L1", affirmativeStateLabel: "promoted" })}
      />,
    );
    expect(
      screen.getByTestId("lake-overview-axis-affirmative-label-L1").textContent,
    ).toBe("promoted");

    rerender(
      <AxisStateCard
        row={makeRow({ axis: "L2", affirmativeStateLabel: "acknowledged" })}
      />,
    );
    expect(
      screen.getByTestId("lake-overview-axis-affirmative-label-L2").textContent,
    ).toBe("acknowledged");

    rerender(
      <AxisStateCard
        row={makeRow({ axis: "L5", affirmativeStateLabel: "confirmed" })}
      />,
    );
    expect(
      screen.getByTestId("lake-overview-axis-affirmative-label-L5").textContent,
    ).toBe("confirmed");
  });

  it("renders 'no activity' chip when all counts are zero", () => {
    render(
      <AxisStateCard
        row={makeRow({
          proposedCount: 0,
          affirmedCount: 0,
          rejectedCount: 0,
        })}
      />,
    );
    const chip = screen.getByTestId("lake-overview-axis-chip-L5");
    expect(chip.getAttribute("data-health")).toBe("gray");
    expect(chip.textContent).toContain("no activity");
  });

  it("renders the 'healthy' green chip when affirmed >= proposed (and proposed > 0)", () => {
    render(
      <AxisStateCard
        row={makeRow({ proposedCount: 1, affirmedCount: 5, rejectedCount: 0 })}
      />,
    );
    const chip = screen.getByTestId("lake-overview-axis-chip-L5");
    expect(chip.getAttribute("data-health")).toBe("green");
  });

  it("renders the 'review pending' amber chip when proposed > affirmed", () => {
    render(
      <AxisStateCard
        row={makeRow({ proposedCount: 10, affirmedCount: 1, rejectedCount: 0 })}
      />,
    );
    const chip = screen.getByTestId("lake-overview-axis-chip-L5");
    expect(chip.getAttribute("data-health")).toBe("amber");
    expect(chip.textContent).toContain("review pending");
  });
});
