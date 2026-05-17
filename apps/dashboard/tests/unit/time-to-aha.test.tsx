/**
 * TimeToAhaPanel — Step 2 (proactivity hook) component tests.
 *
 * Verifies:
 *   - Lit nodes (with timestamps) render with duration + absolute time.
 *   - Pending nodes render gray with the hint text.
 *   - All six milestones are present in canonical order.
 */

import { describe, it, expect } from "vitest";
import { render, within } from "@testing-library/react";
import { TimeToAhaPanel } from "../../components/onboarding/TimeToAhaPanel";
import type { OnboardingMilestones } from "../../lib/ledger-client.types";

const ALL_LIT: OnboardingMilestones = {
  installAt: "2026-04-26T12:00:00Z",
  firstSourceAt: "2026-04-26T12:04:30Z",
  firstConceptAt: "2026-04-26T12:11:00Z",
  firstGoldAt: "2026-04-26T12:24:00Z",
  firstProcessMapAt: "2026-04-27T08:00:00Z",
  firstExperimentAt: "2026-04-27T11:30:00Z",
};

const ALL_PENDING: OnboardingMilestones = {
  installAt: null,
  firstSourceAt: null,
  firstConceptAt: null,
  firstGoldAt: null,
  firstProcessMapAt: null,
  firstExperimentAt: null,
};

const PARTIAL: OnboardingMilestones = {
  installAt: "2026-04-26T12:00:00Z",
  firstSourceAt: "2026-04-26T12:04:30Z",
  firstConceptAt: null,
  firstGoldAt: null,
  firstProcessMapAt: null,
  firstExperimentAt: null,
};

describe("TimeToAhaPanel", () => {
  it("renders all six milestones in canonical order", () => {
    const { container } = render(<TimeToAhaPanel milestones={ALL_PENDING} pollIntervalMs={0} />);
    const stepper = container.querySelector("[data-testid='time-to-aha-stepper']");
    expect(stepper).not.toBeNull();
    // Get the direct child <li> elements (filter manually since happy-dom
    // doesn't support :scope selectors well).
    const milestoneList = Array.from(stepper!.children).filter(
      (el) => el.tagName === "LI",
    ) as HTMLElement[];
    expect(milestoneList.length).toBe(6);
    expect(milestoneList[0].dataset.testid).toBe("milestone-installAt");
    expect(milestoneList[1].dataset.testid).toBe("milestone-firstSourceAt");
    expect(milestoneList[2].dataset.testid).toBe("milestone-firstConceptAt");
    expect(milestoneList[3].dataset.testid).toBe("milestone-firstGoldAt");
    expect(milestoneList[4].dataset.testid).toBe("milestone-firstProcessMapAt");
    expect(milestoneList[5].dataset.testid).toBe("milestone-firstExperimentAt");
  });

  it("marks every milestone as pending when all timestamps are null", () => {
    const { container } = render(<TimeToAhaPanel milestones={ALL_PENDING} pollIntervalMs={0} />);
    const items = container.querySelectorAll("[data-testid^='milestone-']");
    for (const item of Array.from(items) as HTMLElement[]) {
      // Skip nested testids (bar/duration/absolute).
      if (
        item.dataset.testid?.includes("-bar") ||
        item.dataset.testid?.includes("-duration") ||
        item.dataset.testid?.includes("-absolute")
      ) {
        continue;
      }
      expect(item.dataset.state).toBe("pending");
    }
  });

  it("shows duration + absolute timestamp on lit nodes", () => {
    const { container } = render(<TimeToAhaPanel milestones={ALL_LIT} pollIntervalMs={0} />);
    const installItem = container.querySelector(
      "[data-testid='milestone-installAt']"
    ) as HTMLElement;
    expect(installItem.dataset.state).toBe("lit");

    const sourceItem = container.querySelector(
      "[data-testid='milestone-firstSourceAt']"
    ) as HTMLElement;
    expect(sourceItem.dataset.state).toBe("lit");
    const sourceDuration = within(sourceItem).getByTestId(
      "milestone-firstSourceAt-duration"
    );
    // 12:04:30 − 12:00:00 = 4m30s → rounded to 5m by minute formatter.
    expect(sourceDuration.textContent).toMatch(/^\+(?:4m|5m)$/);
    const sourceAbs = within(sourceItem).getByTestId(
      "milestone-firstSourceAt-absolute"
    );
    expect(sourceAbs.textContent).toBe("12:04:30Z");
  });

  it("renders the install node with +0s when duration computes to zero", () => {
    const { container } = render(<TimeToAhaPanel milestones={ALL_LIT} pollIntervalMs={0} />);
    const installDuration = container.querySelector(
      "[data-testid='milestone-installAt-duration']"
    );
    // install is its own anchor: 0s relative to itself.
    expect(installDuration?.textContent).toBe("+0s");
  });

  it("shows day-scale durations for far-future milestones", () => {
    const { container } = render(<TimeToAhaPanel milestones={ALL_LIT} pollIntervalMs={0} />);
    const procDuration = container.querySelector(
      "[data-testid='milestone-firstProcessMapAt-duration']"
    );
    // 24h - 4h gap (12:00 → next day 08:00) = 20h.
    expect(procDuration?.textContent).toBe("+20h");
  });

  it("renders mixed lit/pending in a partial state", () => {
    const { container } = render(<TimeToAhaPanel milestones={PARTIAL} pollIntervalMs={0} />);
    expect(
      container.querySelector("[data-testid='milestone-installAt']")?.getAttribute("data-state")
    ).toBe("lit");
    expect(
      container.querySelector("[data-testid='milestone-firstSourceAt']")?.getAttribute("data-state")
    ).toBe("lit");
    expect(
      container.querySelector("[data-testid='milestone-firstConceptAt']")?.getAttribute("data-state")
    ).toBe("pending");
    expect(
      container.querySelector("[data-testid='milestone-firstExperimentAt']")?.getAttribute("data-state")
    ).toBe("pending");
  });
});
