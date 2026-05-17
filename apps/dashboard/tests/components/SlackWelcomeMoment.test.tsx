/**
 * WS5 S2 — SlackWelcomeMoment.
 *
 * Renders the worm's first chat-sent message as an editorial pull-quote
 * card on /dashboard. The component itself doesn't query — the dashboard
 * server component passes ``message`` (a FirstWormMessage from
 * lib/ledger-client.getFirstWormMessage). When that helper returns null
 * the page hides the card; we don't render an empty-state card here.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SlackWelcomeMoment } from "../../components/dashboard/SlackWelcomeMoment";
import type { FirstWormMessage } from "../../lib/ledger-client";

const RECENT: FirstWormMessage = {
  channelId: "C-data-eng",
  channelName: "data-eng",
  text: "Hi! I'm WormBase. I'll be in #data-eng listening for the next few days.",
  ts: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
};

const OLDER: FirstWormMessage = {
  channelId: "C-finance",
  channelName: "#finance",
  text: "Hello team — I'm here to lurk and learn.",
  ts: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
};

describe("SlackWelcomeMoment (WS5 S2)", () => {
  it("renders the quote-card with the worm's message", () => {
    render(<SlackWelcomeMoment message={RECENT} />);
    const card = screen.getByTestId("slack-welcome-moment");
    expect(card).toBeTruthy();
    const quote = screen.getByTestId("slack-welcome-quote");
    expect(quote.textContent).toContain("WormBase");
    expect(quote.textContent).toContain("data-eng");
  });

  it("attributes the quote to @WormBase + the channel", () => {
    render(<SlackWelcomeMoment message={RECENT} />);
    const attribution = screen.getByTestId("slack-welcome-attribution");
    expect(attribution.textContent).toContain("@WormBase");
    expect(attribution.textContent).toContain("#data-eng");
  });

  it("renders an eyebrow that names the channel", () => {
    render(<SlackWelcomeMoment message={RECENT} />);
    const eyebrow = screen.getByTestId("slack-welcome-eyebrow");
    expect(eyebrow.textContent).toContain("said hello");
    expect(eyebrow.textContent).toContain("#data-eng");
  });

  it("formats a recent timestamp as 'X minutes ago'", () => {
    render(<SlackWelcomeMoment message={RECENT} />);
    const attribution = screen.getByTestId("slack-welcome-attribution");
    expect(attribution.textContent).toMatch(/minute(s)? ago/);
  });

  it("formats older timestamps as 'X hours ago'", () => {
    render(<SlackWelcomeMoment message={OLDER} />);
    const attribution = screen.getByTestId("slack-welcome-attribution");
    expect(attribution.textContent).toMatch(/3 hours ago/);
  });

  it("doesn't double up the # prefix on already-prefixed channel names", () => {
    render(<SlackWelcomeMoment message={OLDER} />);
    const attribution = screen.getByTestId("slack-welcome-attribution");
    // OLDER has channelName "#finance" already; should not become "##finance".
    expect(attribution.textContent).not.toContain("##");
    expect(attribution.textContent).toContain("#finance");
  });
});
