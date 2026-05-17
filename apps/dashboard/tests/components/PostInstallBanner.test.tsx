/**
 * Block I5 — PostInstallBanner.
 *
 * The wizard-vs-bot fork is no longer a forced redirect from the (app)/
 * layout. Fresh tenants land on the dashboard immediately and this
 * banner offers the tour / wizard / chat affordances inline. Renders
 * nothing once setup_completed is non-null.
 *
 * Four banner states tested:
 *   1. setup_mode=null + setup_completed=null  → "want a tour" CTAs
 *   2. setup_mode="wizard" + setup_completed=null → "continue wizard"
 *   3. setup_mode="bot" + setup_completed=null    → "setup in chat"
 *   4. setup_completed != null                    → renders nothing
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PostInstallBanner } from "../../components/onboarding/PostInstallBanner";

describe("PostInstallBanner (Block I5)", () => {
  it("renders the want-a-tour banner when setup_mode is null and setup is not complete", () => {
    render(<PostInstallBanner setupMode={null} setupCompletedAt={null} />);
    const banner = screen.getByTestId("post-install-banner");
    expect(banner.getAttribute("data-banner-state")).toBe("want-a-tour");
    expect(
      screen.getByTestId("post-install-banner-cta-tour").getAttribute("href"),
    ).toBe("/onboarding/whats-next");
    expect(
      screen.getByTestId("post-install-banner-cta-chat").getAttribute("href"),
    ).toBe("/onboarding/setup-mode/choose");
  });

  it("renders the continue-wizard banner when setup_mode='wizard' and setup is incomplete", () => {
    render(
      <PostInstallBanner setupMode="wizard" setupCompletedAt={null} />,
    );
    expect(
      screen.getByTestId("post-install-banner").getAttribute("data-banner-state"),
    ).toBe("wizard-pending");
    expect(
      screen.getByTestId("post-install-banner-cta-wizard").getAttribute("href"),
    ).toBe("/onboarding/tier2");
  });

  it("renders the bot-pending banner (no link) when setup_mode='bot' and setup is incomplete", () => {
    render(<PostInstallBanner setupMode="bot" setupCompletedAt={null} />);
    expect(
      screen.getByTestId("post-install-banner").getAttribute("data-banner-state"),
    ).toBe("bot-pending");
    // No CTA — the worm drives the bot path in chat.
    expect(screen.queryByTestId("post-install-banner-cta-wizard")).toBeNull();
    expect(screen.queryByTestId("post-install-banner-cta-tour")).toBeNull();
    expect(screen.queryByTestId("post-install-banner-cta-chat")).toBeNull();
  });

  it("renders nothing once setup is completed", () => {
    const { container } = render(
      <PostInstallBanner
        setupMode="wizard"
        setupCompletedAt="2026-04-26T12:00:00Z"
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("post-install-banner")).toBeNull();
  });

  it("renders nothing once bot-path setup is completed", () => {
    const { container } = render(
      <PostInstallBanner
        setupMode="bot"
        setupCompletedAt="2026-04-26T12:00:00Z"
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
