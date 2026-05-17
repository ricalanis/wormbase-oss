/**
 * D3 — ConnectPlatformButtons capability-honesty.
 *
 * Tests every variant the platform-status module surfaces:
 *   - production + env set → enabled connect button, no badge
 *   - production + env unset → "Configure $envHint" disabled-style button + modal
 *   - preview + env set → enabled connect button + "preview" badge
 *   - preview + env unset → "Configure" + modal
 *   - coming_soon → greyed out + "coming soon" badge + modal
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ConnectPlatformButtons } from "../../components/channels/ConnectPlatformButtons";

// Stub window.location.assign so we can assert routing without
// triggering jsdom navigation errors.
const originalLocation = window.location;
beforeEach(() => {
  vi.clearAllMocks();
  // jsdom doesn't allow direct assignment; use defineProperty.
  Object.defineProperty(window, "location", {
    writable: true,
    value: {
      ...originalLocation,
      href: "",
      assign: vi.fn(),
    },
  });
});

afterEach(() => {
  Object.defineProperty(window, "location", {
    writable: true,
    value: originalLocation,
  });
});

describe("ConnectPlatformButtons", () => {
  it("renders one button per platform descriptor", () => {
    render(<ConnectPlatformButtons />);
    expect(screen.getByTestId("connect-slack")).toBeInTheDocument();
    expect(screen.getByTestId("connect-discord")).toBeInTheDocument();
    expect(screen.getByTestId("connect-teams")).toBeInTheDocument();
    expect(screen.getByTestId("connect-signal")).toBeInTheDocument();
    expect(screen.getByTestId("connect-whatsapp")).toBeInTheDocument();
  });

  it("flags status via data-status on each button", () => {
    render(<ConnectPlatformButtons />);
    expect(
      screen.getByTestId("connect-slack").getAttribute("data-status"),
    ).toBe("production");
    expect(
      screen.getByTestId("connect-discord").getAttribute("data-status"),
    ).toBe("preview");
    expect(
      screen.getByTestId("connect-signal").getAttribute("data-status"),
    ).toBe("coming_soon");
  });

  it("preview platforms render a 'preview' badge", () => {
    render(<ConnectPlatformButtons />);
    expect(screen.getByTestId("connect-discord-badge").textContent).toBe(
      "preview",
    );
    expect(screen.getByTestId("connect-teams-badge").textContent).toBe(
      "preview",
    );
  });

  it("coming_soon platforms render a 'coming soon' badge and aria-disabled", () => {
    render(<ConnectPlatformButtons />);
    const signal = screen.getByTestId("connect-signal");
    expect(signal.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByTestId("connect-signal-badge").textContent).toBe(
      "coming soon",
    );
  });

  it("clicking a coming_soon button opens the explanatory modal", () => {
    render(<ConnectPlatformButtons />);
    fireEvent.click(screen.getByTestId("connect-signal"));
    const modal = screen.getByTestId("connect-modal-signal");
    expect(modal).toBeInTheDocument();
    // The modal text should mention v1.5 (the canonical landing version).
    expect(modal.textContent).toMatch(/v1\.5/i);
  });

  it("clicking a production button with env configured navigates to the OAuth start", () => {
    render(
      <ConnectPlatformButtons
        envState={{
          SLACK_CLIENT_ID: true,
          SLACK_CLIENT_SECRET: true,
        }}
      />,
    );
    fireEvent.click(screen.getByTestId("connect-slack"));
    expect(window.location.href).toBe("/onboarding/oauth/slack/start");
  });

  it("clicking a preview button with env configured navigates to OAuth start (worm will lurk)", () => {
    render(
      <ConnectPlatformButtons
        envState={{
          DISCORD_CLIENT_ID: true,
          DISCORD_CLIENT_SECRET: true,
        }}
      />,
    );
    fireEvent.click(screen.getByTestId("connect-discord"));
    expect(window.location.href).toBe("/onboarding/oauth/discord/start");
  });

  it("env-unset production buttons render 'configure' instead of 'connect' and open modal", () => {
    render(<ConnectPlatformButtons envState={{}} />);
    const slack = screen.getByTestId("connect-slack");
    expect(slack.getAttribute("data-configured")).toBe("false");
    expect(slack.textContent?.toLowerCase()).toContain("configure");
    fireEvent.click(slack);
    // Modal opens with the env hint, not a synthesized OAuth grant.
    const modal = screen.getByTestId("connect-modal-slack");
    expect(modal).toBeInTheDocument();
    expect(modal.textContent).toMatch(/SLACK_CLIENT_ID/i);
    // Critical: the location did NOT change to a synthesized flow.
    expect(window.location.href).toBe("");
  });

  it("env-unset preview buttons render 'configure' and open modal (no synth)", () => {
    render(<ConnectPlatformButtons envState={{}} />);
    const discord = screen.getByTestId("connect-discord");
    expect(discord.getAttribute("data-configured")).toBe("false");
    fireEvent.click(discord);
    expect(screen.getByTestId("connect-modal-discord")).toBeInTheDocument();
    expect(window.location.href).toBe("");
  });

  it("undefined envState (test default) lets production buttons route normally", () => {
    render(<ConnectPlatformButtons />);
    fireEvent.click(screen.getByTestId("connect-slack"));
    expect(window.location.href).toBe("/onboarding/oauth/slack/start");
  });

  it("modal close dismisses the dialog", () => {
    render(<ConnectPlatformButtons />);
    fireEvent.click(screen.getByTestId("connect-signal"));
    expect(screen.getByTestId("connect-modal-signal")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("connect-modal-close"));
    expect(screen.queryByTestId("connect-modal-signal")).toBeNull();
  });
});
