/**
 * Tests for TopicPlatformFilter (W4-A).
 *
 * Covers:
 *   - renders All / Slack / WhatsApp chips reading from canonical PLATFORMS
 *   - default active chip is "all" (no ?platform= param)
 *   - explicitly-passed `current` overrides the URL value
 *   - clicking a chip writes the right URL replace
 *   - clicking All drops the ?platform= param
 *   - chips carry data-status mirroring the descriptor's PlatformStatus
 *   - WhatsApp chip's tooltip surfaces the canonical statusNote
 *   - resolveTopicPlatformFilter normalizes raw search-param values
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/topics",
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

import {
  TopicPlatformFilter,
  resolveTopicPlatformFilter,
} from "../TopicPlatformFilter";
import { platformBySlug } from "../../../lib/platform-status";

describe("TopicPlatformFilter", () => {
  beforeEach(() => {
    replaceMock.mockReset();
  });

  it("renders all three chips", () => {
    render(<TopicPlatformFilter />);
    expect(screen.getByTestId("topic-platform-chip-all")).toBeInTheDocument();
    expect(screen.getByTestId("topic-platform-chip-slack")).toBeInTheDocument();
    expect(
      screen.getByTestId("topic-platform-chip-whatsapp"),
    ).toBeInTheDocument();
  });

  it("marks 'all' as the default active chip when no platform= is set", () => {
    render(<TopicPlatformFilter />);
    expect(screen.getByTestId("topic-platform-chip-all")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("topic-platform-chip-slack")).toHaveAttribute(
      "data-active",
      "false",
    );
    expect(screen.getByTestId("topic-platform-chip-whatsapp")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("marks the explicitly-passed `current` chip as active", () => {
    render(<TopicPlatformFilter current="whatsapp" />);
    expect(screen.getByTestId("topic-platform-chip-whatsapp")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("topic-platform-chip-all")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("clicking WhatsApp replaces the URL with ?platform=whatsapp", () => {
    render(<TopicPlatformFilter />);
    fireEvent.click(screen.getByTestId("topic-platform-chip-whatsapp"));
    expect(replaceMock).toHaveBeenCalledWith("/topics?platform=whatsapp");
  });

  it("clicking Slack replaces the URL with ?platform=slack", () => {
    render(<TopicPlatformFilter />);
    fireEvent.click(screen.getByTestId("topic-platform-chip-slack"));
    expect(replaceMock).toHaveBeenCalledWith("/topics?platform=slack");
  });

  it("clicking All drops the platform= param", () => {
    render(<TopicPlatformFilter current="whatsapp" />);
    fireEvent.click(screen.getByTestId("topic-platform-chip-all"));
    expect(replaceMock).toHaveBeenCalledWith("/topics");
  });

  it("chips carry data-status reflecting canonical PlatformStatus", () => {
    render(<TopicPlatformFilter />);
    // Slack is production today
    expect(screen.getByTestId("topic-platform-chip-slack")).toHaveAttribute(
      "data-status",
      "production",
    );
    // WhatsApp is preview today
    expect(screen.getByTestId("topic-platform-chip-whatsapp")).toHaveAttribute(
      "data-status",
      "preview",
    );
    // "All" carries no descriptor → data-status="all"
    expect(screen.getByTestId("topic-platform-chip-all")).toHaveAttribute(
      "data-status",
      "all",
    );
  });

  it("WhatsApp chip surfaces the canonical statusNote as tooltip", () => {
    render(<TopicPlatformFilter />);
    const chip = screen.getByTestId("topic-platform-chip-whatsapp");
    const expected = platformBySlug("whatsapp")?.statusNote;
    expect(expected).toBeTruthy();
    expect(chip).toHaveAttribute("title", expected as string);
  });
});

describe("resolveTopicPlatformFilter", () => {
  it("returns 'all' for missing values", () => {
    expect(resolveTopicPlatformFilter(undefined)).toBe("all");
    expect(resolveTopicPlatformFilter("")).toBe("all");
  });

  it("returns 'all' for unknown values (forward-compat)", () => {
    expect(resolveTopicPlatformFilter("discord")).toBe("all");
    expect(resolveTopicPlatformFilter("teams")).toBe("all");
  });

  it("returns 'whatsapp' / 'slack' / 'all' for known values", () => {
    expect(resolveTopicPlatformFilter("whatsapp")).toBe("whatsapp");
    expect(resolveTopicPlatformFilter("slack")).toBe("slack");
    expect(resolveTopicPlatformFilter("all")).toBe("all");
  });

  it("uses the first element of an array search-param value", () => {
    expect(resolveTopicPlatformFilter(["whatsapp", "slack"])).toBe("whatsapp");
  });
});
