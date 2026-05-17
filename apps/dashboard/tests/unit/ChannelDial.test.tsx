import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChannelDial } from "../../components/settings/ChannelDial";
import type { ChannelRow } from "../../lib/ledger-client.types";

const row: ChannelRow = {
  channelId: "ch_data",
  name: "#data",
  talkativeness: "responsive",
  lastPolicyHash: "abcd1234",
  receipt: {
    hash: "abcd1234",
    source: "channel-policy-v1",
    owner: "ricardo",
    classification: "internal",
  },
};

describe("ChannelDial", () => {
  it("renders three rectangular segments (no rounded pills)", () => {
    const { container } = render(<ChannelDial row={row} />);
    for (const seg of ["lurker", "responsive", "proactive"]) {
      const btn = container.querySelector(
        `[data-testid="channel-${row.channelId}-${seg}"]`
      ) as HTMLButtonElement;
      expect(btn).toBeTruthy();
      expect(btn.style.borderRadius).toBe("0px");
    }
  });

  it("marks the active segment with data-active=true", () => {
    render(<ChannelDial row={row} />);
    const active = screen.getByTestId("channel-ch_data-responsive");
    expect(active.getAttribute("data-active")).toBe("true");
  });

  it("calls onChange when a different segment is picked", async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    render(<ChannelDial row={row} onChange={fn} />);
    fireEvent.click(screen.getByTestId("channel-ch_data-proactive"));
    expect(fn).toHaveBeenCalledWith("ch_data", "proactive");
  });

  it("does NOT call onChange when picking the current value", async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    render(<ChannelDial row={row} onChange={fn} />);
    fireEvent.click(screen.getByTestId("channel-ch_data-responsive"));
    expect(fn).not.toHaveBeenCalled();
  });

  // ------------------------------------------------------------------
  // Phase D1 — WhatsApp render branch: jid-derived display, platform
  // pill, last-seen timestamp.
  // ------------------------------------------------------------------

  it("renders a WhatsApp DM jid as +E.164", () => {
    const dmRow: ChannelRow = {
      channelId: "5511999998888@s.whatsapp.net",
      name: "5511999998888@s.whatsapp.net",
      talkativeness: "lurker",
      lastPolicyHash: "abcd1234",
      platform: "whatsapp",
      lastSeenAt: "2026-05-06T12:34:56Z",
      receipt: {
        hash: "abcd1234",
        source: "channel-policy-v1",
        owner: "system",
        classification: "internal",
      },
    };
    render(<ChannelDial row={dmRow} />);
    const article = screen.getByTestId(
      "channel-dial-5511999998888@s.whatsapp.net",
    );
    expect(article.getAttribute("data-platform")).toBe("whatsapp");
    expect(article.textContent).toContain("+5511999998888");
    expect(
      screen.getByTestId(
        "channel-platform-5511999998888@s.whatsapp.net",
      ).textContent,
    ).toBe("DM");
  });

  it("renders a WhatsApp group jid with truncated id and group hint", () => {
    const groupRow: ChannelRow = {
      channelId: "120363025246125486@g.us",
      name: "120363025246125486@g.us",
      talkativeness: "lurker",
      lastPolicyHash: "deadbeef0000",
      platform: "whatsapp",
      lastSeenAt: null,
      receipt: {
        hash: "deadbeef0000",
        source: "channel-policy-v1",
        owner: "system",
        classification: "internal",
      },
    };
    render(<ChannelDial row={groupRow} />);
    const article = screen.getByTestId(
      "channel-dial-120363025246125486@g.us",
    );
    expect(article.textContent).toContain("WhatsApp Group");
    expect(article.textContent).toContain("120363");
    expect(
      screen.getByTestId("channel-platform-120363025246125486@g.us")
        .textContent,
    ).toBe("group");
  });

  it("surfaces last-seen timestamp when provided", () => {
    const r: ChannelRow = {
      channelId: "5511999998888@s.whatsapp.net",
      name: "5511999998888@s.whatsapp.net",
      talkativeness: "lurker",
      lastPolicyHash: "abcd1234",
      platform: "whatsapp",
      lastSeenAt: "2026-05-06T12:34:56Z",
      receipt: {
        hash: "abcd1234",
        source: "channel-policy-v1",
        owner: "system",
        classification: "internal",
      },
    };
    render(<ChannelDial row={r} />);
    expect(
      screen.getByTestId(
        "channel-last-seen-5511999998888@s.whatsapp.net",
      ).textContent,
    ).toMatch(/2026-05-06/);
  });

  it("does NOT render the platform pill for Slack rows (byte-identical to pre-D1)", () => {
    render(<ChannelDial row={row} />);
    expect(
      screen.queryByTestId(`channel-platform-${row.channelId}`),
    ).toBeNull();
  });
});
