/**
 * PlatformBadge tests (W4-B, 2026-05-07).
 *
 * Pins the contract:
 *   - explicit platform field wins
 *   - channel-id-shape inference is the back-compat fallback
 *   - unknown / missing platform → renders nothing (honest empty state)
 *   - tone is keyed off the canonical PlatformDescriptor.status
 *   - design tokens reused (no new colors introduced)
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  PlatformBadge,
  inferPlatformFromChannelId,
} from "../PlatformBadge";

describe("PlatformBadge · explicit platform field", () => {
  it("renders Slack as production / green tone", () => {
    render(<PlatformBadge platform="slack" />);
    const chip = screen.getByTestId("platform-badge-slack");
    expect(chip).toBeInTheDocument();
    expect(chip.getAttribute("data-platform")).toBe("slack");
    expect(chip.getAttribute("data-platform-status")).toBe("production");
    expect(chip.textContent).toBe("Slack");
    // Sanity: green tone uses --wb-color-botanical-green-deep for foreground.
    expect((chip as HTMLElement).style.color).toContain("botanical-green-deep");
  });

  it("renders WhatsApp as preview / sepia tone", () => {
    render(<PlatformBadge platform="whatsapp" />);
    const chip = screen.getByTestId("platform-badge-whatsapp");
    expect(chip).toBeInTheDocument();
    expect(chip.getAttribute("data-platform")).toBe("whatsapp");
    expect(chip.getAttribute("data-platform-status")).toBe("preview");
    expect(chip.textContent).toBe("WhatsApp");
    expect((chip as HTMLElement).style.color).toContain("sepia-warning-deep");
  });

  it("renders Signal as coming_soon / muted tone", () => {
    render(<PlatformBadge platform="signal" />);
    const chip = screen.getByTestId("platform-badge-signal");
    expect(chip.getAttribute("data-platform-status")).toBe("coming_soon");
    expect((chip as HTMLElement).style.color).toContain("hash-gray");
  });

  it("surfaces statusNote in the title attribute", () => {
    render(<PlatformBadge platform="whatsapp" />);
    const chip = screen.getByTestId("platform-badge-whatsapp");
    expect(chip.getAttribute("title")).toMatch(/preview/i);
    expect(chip.getAttribute("title")).toMatch(/Baileys|test-numbers|ToS/i);
  });

  it("omits the title when showTooltip is false", () => {
    render(<PlatformBadge platform="slack" showTooltip={false} />);
    const chip = screen.getByTestId("platform-badge-slack");
    expect(chip.getAttribute("title")).toBeNull();
  });
});

describe("PlatformBadge · channel-id fallback", () => {
  it("infers slack from a C-prefixed channel id", () => {
    render(<PlatformBadge channelId="C0FINANCE123" />);
    const chip = screen.getByTestId("platform-badge-slack");
    expect(chip.getAttribute("data-platform")).toBe("slack");
  });

  it("infers whatsapp from a @s.whatsapp.net jid", () => {
    render(<PlatformBadge channelId="5215555550000@s.whatsapp.net" />);
    const chip = screen.getByTestId("platform-badge-whatsapp");
    expect(chip.getAttribute("data-platform")).toBe("whatsapp");
  });

  it("infers whatsapp from a group @g.us jid", () => {
    render(<PlatformBadge channelId="120363021@g.us" />);
    const chip = screen.getByTestId("platform-badge-whatsapp");
    expect(chip).toBeInTheDocument();
  });

  it("prefers explicit platform over channel-id inference", () => {
    // Explicit "whatsapp" must win even if the channel id looks Slack-shaped.
    render(
      <PlatformBadge platform="whatsapp" channelId="C0SLACKCHANNEL" />,
    );
    expect(screen.queryByTestId("platform-badge-slack")).toBeNull();
    expect(screen.getByTestId("platform-badge-whatsapp")).toBeInTheDocument();
  });
});

describe("PlatformBadge · honest empty state", () => {
  it("renders nothing for null / undefined platform AND no channel id", () => {
    const { container } = render(<PlatformBadge />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for empty string platform", () => {
    const { container } = render(<PlatformBadge platform="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for an unrecognized channel-id shape", () => {
    const { container } = render(<PlatformBadge channelId="123456" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders an unknown platform slug literally with neutral tone", () => {
    // Forward-compat: a brand-new platform slug from upstream Python
    // adapter that the TS mirror hasn't picked up yet should still
    // render something, not crash. Tone falls back to neutral.
    render(<PlatformBadge platform="zulip" showTooltip={false} />);
    const chip = screen.getByTestId("platform-badge-zulip");
    expect(chip.getAttribute("data-platform-status")).toBe("unknown");
    expect(chip.textContent).toBe("zulip");
  });
});

describe("inferPlatformFromChannelId", () => {
  it("returns null for empty / undefined / null inputs", () => {
    expect(inferPlatformFromChannelId(null)).toBeNull();
    expect(inferPlatformFromChannelId(undefined)).toBeNull();
    expect(inferPlatformFromChannelId("")).toBeNull();
  });

  it("returns slack for C-prefix and D-prefix ids", () => {
    expect(inferPlatformFromChannelId("C12345678")).toBe("slack");
    expect(inferPlatformFromChannelId("D12345678")).toBe("slack");
  });

  it("returns whatsapp for the two known jid suffixes", () => {
    expect(inferPlatformFromChannelId("521@s.whatsapp.net")).toBe(
      "whatsapp",
    );
    expect(inferPlatformFromChannelId("12@g.us")).toBe("whatsapp");
  });

  it("returns null for anything else", () => {
    expect(inferPlatformFromChannelId("random-channel-123")).toBeNull();
    expect(inferPlatformFromChannelId("987654321")).toBeNull();
  });
});
