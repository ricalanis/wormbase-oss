/**
 * G4 — SetupModeChooser (the wizard-vs-bot fork UI).
 *
 * Tests the bot-card gating logic: enabled when a chat platform is
 * connected, disabled with a hint otherwise.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { SetupModeChooser } from "../../components/onboarding/SetupModeChooser";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("SetupModeChooser", () => {
  it("renders both cards", () => {
    render(<SetupModeChooser connectedPlatform={null} />);
    expect(screen.getByTestId("setup-mode-chooser")).toBeInTheDocument();
    expect(screen.getByTestId("setup-mode-wizard")).toBeInTheDocument();
    expect(screen.getByTestId("setup-mode-bot")).toBeInTheDocument();
  });

  it("wizard card is enabled when no chat platform is connected", () => {
    render(<SetupModeChooser connectedPlatform={null} />);
    expect(
      screen
        .getByTestId("setup-mode-wizard")
        .getAttribute("data-disabled"),
    ).toBe("false");
  });

  it("bot card is disabled when no chat platform is connected", () => {
    render(<SetupModeChooser connectedPlatform={null} />);
    expect(
      screen.getByTestId("setup-mode-bot").getAttribute("data-disabled"),
    ).toBe("true");
    expect(
      screen.getByTestId("setup-mode-bot-blocker"),
    ).toBeInTheDocument();
  });

  it("bot card is enabled when a chat platform is connected", () => {
    render(<SetupModeChooser connectedPlatform="slack" />);
    expect(
      screen.getByTestId("setup-mode-bot").getAttribute("data-disabled"),
    ).toBe("false");
    expect(screen.queryByTestId("setup-mode-bot-blocker")).toBeNull();
  });

  it("wizard click POSTs to /api/onboarding/setup-mode and redirects", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ redirect: "/onboarding/tier2", mode: "wizard" }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<SetupModeChooser connectedPlatform={null} />);
    fireEvent.click(screen.getByTestId("setup-mode-wizard"));

    // flush microtasks
    await Promise.resolve();
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/onboarding/setup-mode",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "wizard" }),
      }),
    );
  });

  it("bot click POSTs with mode=bot when platform is connected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ redirect: "/", mode: "bot" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<SetupModeChooser connectedPlatform="slack" />);
    fireEvent.click(screen.getByTestId("setup-mode-bot"));

    await Promise.resolve();
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/onboarding/setup-mode",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "bot" }),
      }),
    );
  });

  it("bot click is a no-op when no platform connected (button is disabled)", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<SetupModeChooser connectedPlatform={null} />);
    fireEvent.click(screen.getByTestId("setup-mode-bot"));

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
