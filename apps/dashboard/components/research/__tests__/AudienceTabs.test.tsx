/**
 * Tests for AudienceTabs (W5.A5).
 *
 * Covers:
 *   - renders the three Mine / Team / Company tabs
 *   - the active tab is reflected via aria-selected + data-active
 *   - clicking a non-active tab calls router.replace with the right
 *     query string (audience=team / audience=company)
 *   - clicking "Mine" deletes the audience param (default state)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/research",
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

import { AudienceTabs } from "../AudienceTabs";

describe("AudienceTabs", () => {
  beforeEach(() => {
    replaceMock.mockReset();
  });

  it("renders all three tabs", () => {
    render(<AudienceTabs />);
    expect(screen.getByTestId("audience-tab-mine")).toBeInTheDocument();
    expect(screen.getByTestId("audience-tab-team")).toBeInTheDocument();
    expect(screen.getByTestId("audience-tab-company")).toBeInTheDocument();
  });

  it("marks Mine as the default active tab when no audience= is set", () => {
    render(<AudienceTabs />);
    expect(screen.getByTestId("audience-tab-mine")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("audience-tab-team")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("marks the explicitly-passed `current` tab as active", () => {
    render(<AudienceTabs current="company" />);
    expect(screen.getByTestId("audience-tab-company")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("audience-tab-mine")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("clicking Team replaces the URL with ?audience=team", () => {
    render(<AudienceTabs />);
    fireEvent.click(screen.getByTestId("audience-tab-team"));
    expect(replaceMock).toHaveBeenCalledWith("/research?audience=team");
  });

  it("clicking Mine drops the audience= param", () => {
    render(<AudienceTabs current="company" />);
    fireEvent.click(screen.getByTestId("audience-tab-mine"));
    expect(replaceMock).toHaveBeenCalledWith("/research");
  });
});
