import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { WizardProgress } from "../../components/onboarding/WizardProgress";

describe("WizardProgress", () => {
  it("marks completed tiers as done, current as current, others as pending", () => {
    const { container } = render(<WizardProgress currentTier={2} completed={[1]} />);
    expect(
      container.querySelector("[data-testid='tier-1']")?.getAttribute("data-state")
    ).toBe("done");
    expect(
      container.querySelector("[data-testid='tier-2']")?.getAttribute("data-state")
    ).toBe("current");
    expect(
      container.querySelector("[data-testid='tier-3']")?.getAttribute("data-state")
    ).toBe("pending");
  });

  it("uses three rectangular bars (NOT a rounded progress bar)", () => {
    const { container } = render(<WizardProgress currentTier={1} />);
    const bars = container.querySelectorAll("nav > div > span[aria-hidden='true']");
    expect(bars.length).toBe(3);
    for (const bar of Array.from(bars) as HTMLElement[]) {
      expect(bar.style.borderRadius).toBe("");
    }
  });
});
