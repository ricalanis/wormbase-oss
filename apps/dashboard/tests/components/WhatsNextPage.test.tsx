/**
 * G4 — /onboarding/whats-next page.
 *
 * Server component test focused on the rendered component output.
 * Asserts three cards link to the right targets.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import WhatsNextPage from "../../app/onboarding/whats-next/page";

// Stub @wormbase/design Page so server-only deps don't break the render.
import type { ReactNode } from "react";

describe("WhatsNextPage", () => {
  it("renders three buttons: continue setup / add source / connect platform", async () => {
    const node = await WhatsNextPage();
    render(node as ReactNode);
    expect(screen.getByTestId("whats-next")).toBeInTheDocument();
    expect(
      screen.getByTestId("whats-next-continue-setup"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("whats-next-add-source")).toBeInTheDocument();
    expect(
      screen.getByTestId("whats-next-connect-platform"),
    ).toBeInTheDocument();
  });

  it("continue-setup card is the primary variant (T2 fork)", async () => {
    const node = await WhatsNextPage();
    render(node as ReactNode);
    expect(
      screen
        .getByTestId("whats-next-continue-setup")
        .getAttribute("data-variant"),
    ).toBe("primary");
  });

  it("links to the setup-mode chooser", async () => {
    const node = await WhatsNextPage();
    render(node as ReactNode);
    const link = screen.getByTestId("whats-next-continue-setup");
    expect(link.getAttribute("href")).toBe("/onboarding/setup-mode/choose");
  });

  it("add-source loops back to /onboarding", async () => {
    const node = await WhatsNextPage();
    render(node as ReactNode);
    expect(
      screen
        .getByTestId("whats-next-add-source")
        .getAttribute("href"),
    ).toBe("/onboarding");
  });

  it("connect-platform goes to the existing OAuth start", async () => {
    const node = await WhatsNextPage();
    render(node as ReactNode);
    expect(
      screen
        .getByTestId("whats-next-connect-platform")
        .getAttribute("href"),
    ).toBe("/onboarding/oauth/slack/start");
  });
});
