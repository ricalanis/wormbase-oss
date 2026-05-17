/**
 * Tests for WhatsAppGraduationBanner (Wave 3.2 Hole #5).
 *
 * Asserts the capability-honesty banner pinned to /channels/connect/whatsapp:
 *   - renders the "Preview" label + production-ready capability list
 *   - lists the 3 graduation steps under the <details> summary
 *   - links to the graduation runbook with the correct href
 *   - renders identically (banner visible, steps + link present) for both
 *     paired=true and paired=false — the message is about send-capability
 *     graduation, not pairing-state
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { WhatsAppGraduationBanner } from "../WhatsAppGraduationBanner";

const RUNBOOK_URL = "https://github.com/wormbase/docs/whatsapp-graduation";

describe("WhatsAppGraduationBanner", () => {
  it("renders the preview label and headline", () => {
    render(<WhatsAppGraduationBanner paired={false} />);

    const banner = screen.getByTestId("whatsapp-graduation-banner");
    expect(banner).toHaveAttribute(
      "aria-label",
      "WhatsApp capability status",
    );
    // Title includes "WhatsApp" and the inline "Preview" emphasis.
    expect(within(banner).getByRole("heading", { level: 3 })).toHaveTextContent(
      /WhatsApp/i,
    );
    expect(within(banner).getByRole("heading", { level: 3 })).toHaveTextContent(
      /Preview/i,
    );
  });

  it("lists the five production-ready capabilities", () => {
    render(<WhatsAppGraduationBanner paired={false} />);

    const banner = screen.getByTestId("whatsapp-graduation-banner");
    // Listening, identity-discovery, conversation-sync, history-replay, DMs.
    expect(banner).toHaveTextContent(/Listening/);
    expect(banner).toHaveTextContent(/identity-discovery/);
    expect(banner).toHaveTextContent(/conversation-sync/);
    expect(banner).toHaveTextContent(/history-replay/);
    expect(banner).toHaveTextContent(/DMs/);
    expect(banner).toHaveTextContent(/production-ready/);
    // Sending is preview, not production.
    expect(banner).toHaveTextContent(/Sending.*preview/i);
  });

  it("renders the 3 graduation steps inside <details>", () => {
    render(<WhatsAppGraduationBanner paired={false} />);

    const details = screen.getByTestId("whatsapp-graduation-steps");
    // The summary acts as the toggle label.
    expect(details).toHaveTextContent(/How to graduate Send to production/i);

    const list = screen.getByTestId("whatsapp-graduation-steps-list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);

    expect(items[0]).toHaveTextContent(/Operator approves write scopes/i);
    expect(items[0]).toHaveTextContent(/OpenClaw Control UI/i);
    expect(items[0]).toHaveTextContent(/operator\.read/);

    expect(items[1]).toHaveTextContent(/docker-host access/i);
    expect(items[1]).toHaveTextContent(/upstream HTTP route/i);
    expect(items[1]).toHaveTextContent(/#73016/);

    expect(items[2]).toHaveTextContent(/WORMBASE_WHATSAPP_SEND_DISABLE=false/);
    expect(items[2]).toHaveTextContent(/tenant config/i);
  });

  it("renders the graduation runbook link with the correct href", () => {
    render(<WhatsAppGraduationBanner paired={false} />);

    const link = screen.getByTestId("whatsapp-graduation-runbook-link");
    expect(link).toHaveAttribute("href", RUNBOOK_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveTextContent(/Full graduation runbook/i);
  });

  it("renders the banner in both paired states (the message is about send-capability, not pairing)", () => {
    const { unmount } = render(<WhatsAppGraduationBanner paired={true} />);
    let banner = screen.getByTestId("whatsapp-graduation-banner");
    expect(banner).toHaveAttribute("data-paired", "true");
    // Steps + link are present in the paired state.
    expect(
      within(banner).getByTestId("whatsapp-graduation-steps-list"),
    ).toBeInTheDocument();
    expect(
      within(banner).getByTestId("whatsapp-graduation-runbook-link"),
    ).toHaveAttribute("href", RUNBOOK_URL);
    unmount();

    render(<WhatsAppGraduationBanner paired={false} />);
    banner = screen.getByTestId("whatsapp-graduation-banner");
    expect(banner).toHaveAttribute("data-paired", "false");
    expect(
      within(banner).getByTestId("whatsapp-graduation-steps-list"),
    ).toBeInTheDocument();
    expect(
      within(banner).getByTestId("whatsapp-graduation-runbook-link"),
    ).toHaveAttribute("href", RUNBOOK_URL);
  });
});
