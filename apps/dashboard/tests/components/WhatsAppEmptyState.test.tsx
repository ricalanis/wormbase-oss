/**
 * Phase D1 (2026-05-06) — WhatsApp empty state.
 *
 * Per CLAUDE.md §9: every panel must carry a visible empty-state when
 * its read accessor returns []. The /channels surface uses this when no
 * WhatsApp install row has landed yet — it must show the QR-pairing
 * affordance, not silently render nothing.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { WhatsAppEmptyState } from "../../components/channels/WhatsAppEmptyState";

describe("WhatsAppEmptyState", () => {
  it("renders a visible 'not paired' empty state", () => {
    render(<WhatsAppEmptyState />);
    const node = screen.getByTestId("whatsapp-install-empty");
    expect(node).toBeInTheDocument();
    expect(node.getAttribute("data-platform")).toBe("whatsapp");
    expect(node.textContent?.toLowerCase()).toContain("not paired");
  });

  it("points at the QR pairing runbook and the dedicated connect page", () => {
    render(<WhatsAppEmptyState />);
    const node = screen.getByTestId("whatsapp-install-empty");
    expect(node.textContent).toMatch(/QR pairing/i);
    expect(node.textContent).toContain("infra/openclaw/WHATSAPP_PAIRING.md");
  });

  it("renders a CTA link to the dedicated pairing-instructions page (W2-C)", () => {
    render(<WhatsAppEmptyState />);
    const cta = screen.getByTestId("whatsapp-connect-cta");
    expect(cta).toBeInTheDocument();
    expect(cta).toHaveAttribute("href", "/channels/connect/whatsapp");
    expect(cta.textContent).toMatch(/pairing/i);
  });

  it("surfaces the Baileys ToS caveat in the empty state", () => {
    render(<WhatsAppEmptyState />);
    const node = screen.getByTestId("whatsapp-install-empty");
    expect(node.textContent).toMatch(/Baileys/i);
    expect(node.textContent).toMatch(/ToS|test number/i);
  });
});
