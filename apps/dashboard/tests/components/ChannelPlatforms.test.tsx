/**
 * W2-A — landing-page channel-platforms tile section.
 *
 * Pins the data-driven contract:
 *   - Tiles are rendered from the canonical PLATFORMS list in
 *     `lib/platform-status.ts` — a WhatsApp tile MUST appear at preview
 *     status with the post-C-wave capabilities `["ingest", "dm", "send"]`.
 *   - Status badges read the descriptor's `status`; preview platforms
 *     carry a sepia-toned chip; production platforms green; coming_soon
 *     muted.
 *   - The `statusNote` is surfaced both as a tooltip (`title` attribute)
 *     and inside a click-to-open modal so visitors can read the long
 *     prose without leaving the page.
 *   - Slack / Discord / Teams / Signal continue to render — additive
 *     change only, no descriptor was retired.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";

import { ChannelPlatforms } from "../../components/landing/ChannelPlatforms";
import {
  PLATFORMS,
  platformBySlug,
} from "../../lib/platform-status";

describe("ChannelPlatforms (W2-A landing-page tiles)", () => {
  it("renders one tile per canonical PLATFORMS entry, including WhatsApp", () => {
    render(<ChannelPlatforms />);
    for (const p of PLATFORMS) {
      expect(
        screen.getByTestId(`channel-platform-tile-${p.platform}`),
      ).toBeInTheDocument();
    }
    // WhatsApp specifically — the post-C-wave addition this surface targets.
    expect(
      screen.getByTestId("channel-platform-tile-whatsapp"),
    ).toBeInTheDocument();
  });

  it("Slack / Discord / Teams / Signal continue to render (additive add only)", () => {
    render(<ChannelPlatforms />);
    expect(
      screen.getByTestId("channel-platform-tile-slack"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("channel-platform-tile-discord"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("channel-platform-tile-teams"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("channel-platform-tile-signal"),
    ).toBeInTheDocument();
  });

  it("renders the WhatsApp tile at preview status with a preview badge", () => {
    render(<ChannelPlatforms />);
    const tile = screen.getByTestId("channel-platform-tile-whatsapp");
    expect(tile.getAttribute("data-platform-status")).toBe("preview");
    const badge = screen.getByTestId("channel-platform-badge-whatsapp");
    expect(badge).toBeInTheDocument();
    // Badge text mirrors the PlatformStatus literal.
    expect(badge.textContent).toMatch(/preview/i);
  });

  it("WhatsApp tile surfaces the capability chips from the canonical descriptor", () => {
    render(<ChannelPlatforms />);
    const caps = screen.getByTestId("channel-platform-capabilities-whatsapp");
    const items = caps.querySelectorAll("li");
    const text = Array.from(items).map((li) => li.textContent?.trim());
    // Capability set is the post-C-wave canonical set on the WhatsApp
    // descriptor — `ingest`, `dm`, `send`. Order follows descriptor.
    expect(text).toEqual(["ingest", "dm", "send"]);
  });

  it("tooltip surfaces the canonical statusNote (title attribute reads from descriptor)", () => {
    render(<ChannelPlatforms />);
    const wa = platformBySlug("whatsapp");
    expect(wa).not.toBeNull();
    const tile = screen.getByTestId("channel-platform-tile-whatsapp");
    // `title` is the data-driven hover surface — value is identical to
    // the descriptor's statusNote.
    expect(tile.getAttribute("title")).toBe(wa!.statusNote);
  });

  it("click on a tile opens a modal exposing the canonical statusNote", () => {
    render(<ChannelPlatforms />);
    const tile = screen.getByTestId("channel-platform-tile-whatsapp");
    fireEvent.click(tile);
    const modal = screen.getByTestId("channel-platform-modal");
    expect(modal).toBeInTheDocument();
    const statusNote = within(modal).getByTestId(
      "channel-platform-modal-status-note",
    );
    const wa = platformBySlug("whatsapp");
    expect(statusNote.textContent).toBe(wa!.statusNote);
    // Modal close returns the surface to its resting state.
    fireEvent.click(within(modal).getByTestId("channel-platform-modal-close"));
    expect(
      screen.queryByTestId("channel-platform-modal"),
    ).not.toBeInTheDocument();
  });

  it("status tone differs by descriptor.status (production / preview / coming_soon)", () => {
    render(<ChannelPlatforms />);
    expect(
      screen.getByTestId("channel-platform-tile-slack").getAttribute(
        "data-platform-status",
      ),
    ).toBe("production");
    expect(
      screen.getByTestId("channel-platform-tile-discord").getAttribute(
        "data-platform-status",
      ),
    ).toBe("preview");
    expect(
      screen.getByTestId("channel-platform-tile-signal").getAttribute(
        "data-platform-status",
      ),
    ).toBe("coming_soon");
  });

  it("modal click-outside closes the panel without firing the tile button", () => {
    render(<ChannelPlatforms />);
    fireEvent.click(screen.getByTestId("channel-platform-tile-whatsapp"));
    const modal = screen.getByTestId("channel-platform-modal");
    // Clicking the scrim (the modal root) closes; clicking the card
    // body propagates stopPropagation. We exercise the scrim path here.
    fireEvent.click(modal);
    expect(
      screen.queryByTestId("channel-platform-modal"),
    ).not.toBeInTheDocument();
  });
});
