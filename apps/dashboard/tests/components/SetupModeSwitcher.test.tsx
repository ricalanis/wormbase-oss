/**
 * G6 — SetupModeSwitcher (settings setup-mode switcher).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { SetupModeSwitcher } from "../../components/settings/SetupModeSwitcher";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("SetupModeSwitcher", () => {
  it("renders the completed-state hint when setup is done", () => {
    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt="2026-04-26T15:00:00Z"
        connectedPlatform="slack"
        isAdmin
      />,
    );
    expect(
      screen.getByTestId("setup-mode-completed-state"),
    ).toBeInTheDocument();
  });

  it("renders the uninitialized hint when no mode picked yet", () => {
    render(
      <SetupModeSwitcher
        currentMode={null}
        completedAt={null}
        connectedPlatform="slack"
        isAdmin
      />,
    );
    expect(
      screen.getByTestId("setup-mode-uninitialized-state"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("setup-mode-go-to-choose"),
    ).toBeInTheDocument();
  });

  it("renders both radio buttons when admin + mode in flight", () => {
    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform="slack"
        isAdmin
      />,
    );
    expect(
      screen.getByTestId("setup-mode-radio-wizard"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("setup-mode-radio-bot"),
    ).toBeInTheDocument();
  });

  it("hides switcher for non-admin users", () => {
    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform="slack"
        isAdmin={false}
      />,
    );
    expect(
      screen.getByTestId("setup-mode-not-admin"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("setup-mode-radio-bot")).toBeNull();
  });

  it("disables bot radio when no chat platform connected", () => {
    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform={null}
        isAdmin
      />,
    );
    expect(
      screen
        .getByTestId("setup-mode-radio-bot")
        .getAttribute("aria-disabled"),
    ).toBe("true");
  });

  it("clicking a different radio opens the confirm modal", () => {
    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform="slack"
        isAdmin
      />,
    );
    fireEvent.click(screen.getByTestId("setup-mode-radio-bot"));
    expect(
      screen.getByTestId("setup-mode-confirm-modal"),
    ).toBeInTheDocument();
  });

  it("confirm POSTs to /api/onboarding/setup-mode and refreshes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ redirect: "/", mode: "bot" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform="slack"
        isAdmin
      />,
    );
    fireEvent.click(screen.getByTestId("setup-mode-radio-bot"));
    fireEvent.click(screen.getByTestId("setup-mode-confirm"));

    await Promise.resolve();
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/onboarding/setup-mode",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "bot" }),
      }),
    );
    expect(refreshMock).toHaveBeenCalled();
  });

  it("cancel dismisses the modal without calling fetch", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <SetupModeSwitcher
        currentMode="wizard"
        completedAt={null}
        connectedPlatform="slack"
        isAdmin
      />,
    );
    fireEvent.click(screen.getByTestId("setup-mode-radio-bot"));
    fireEvent.click(screen.getByTestId("setup-mode-cancel"));
    expect(screen.queryByTestId("setup-mode-confirm-modal")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
