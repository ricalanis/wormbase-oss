/**
 * Phase W2-C (2026-05-07) — WhatsApp pairing-instructions flow.
 *
 * The dedicated `/channels/connect/whatsapp` page composes this client
 * component. Tests verify capability honesty: the page is documentation-
 * as-UI, the operator runs the docker commands themselves, and the
 * status block surfaces an honest "waiting for install entry" affordance
 * driven by `router.refresh()` rather than fake interactivity.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { WhatsAppPairingFlow } from "../../components/channels/WhatsAppPairingFlow";

// next/navigation's `useRouter` is a no-op in vitest's jsdom; mock it so
// the refresh button has a stable spy to assert against.
const refreshSpy = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: refreshSpy,
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

describe("WhatsAppPairingFlow", () => {
  it("renders all three steps when no install exists", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    expect(screen.getByTestId("pairing-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-step-3")).toBeInTheDocument();
  });

  it("step 2 + 3 render disabled until ToS is acked", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    expect(screen.getByTestId("pairing-step-2").getAttribute("data-enabled")).toBe(
      "false",
    );
    expect(screen.getByTestId("pairing-step-3").getAttribute("data-enabled")).toBe(
      "false",
    );
    fireEvent.click(screen.getByTestId("pairing-tos-ack"));
    expect(screen.getByTestId("pairing-step-2").getAttribute("data-enabled")).toBe(
      "true",
    );
    expect(screen.getByTestId("pairing-step-3").getAttribute("data-enabled")).toBe(
      "true",
    );
  });

  it("step 1 surfaces the Baileys ToS posture in the body copy", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    const step = screen.getByTestId("pairing-step-1");
    expect(step.textContent).toMatch(/Baileys/);
    expect(step.textContent).toMatch(/Terms of Service/i);
    expect(step.textContent).toMatch(/test SIM/i);
  });

  it("step 2 surfaces both copy-able operator commands", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    const cfg = screen.getByTestId("pairing-cmd-configure");
    expect(cfg.textContent).toContain(
      "docker exec -it wormbase-openclaw openclaw configure --section channels",
    );
    const login = screen.getByTestId("pairing-cmd-login");
    expect(login.textContent).toContain(
      "docker exec -it wormbase-openclaw openclaw channels login --channel whatsapp --account baseworm",
    );
  });

  it("step 2 surfaces the bot-phone env-var snippet only after a phone is entered", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    expect(screen.queryByTestId("pairing-env-snippet")).toBeNull();
    fireEvent.change(screen.getByTestId("pairing-bot-phone"), {
      target: { value: "5511999999999" },
    });
    const env = screen.getByTestId("pairing-env-snippet");
    expect(env.textContent).toContain(
      "WORMBASE_WHATSAPP_BOT_PHONE_BASEWORM=5511999999999",
    );
  });

  it("strips non-digit input from the bot-phone field", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    const input = screen.getByTestId("pairing-bot-phone") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "+55-11-9999-9999" } });
    expect(input.value).toBe("551199999999");
  });

  it("step 3 surfaces the honest waiting-for-install status + refresh", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    const status = screen.getByTestId("pairing-waiting-status");
    expect(status.textContent?.toLowerCase()).toContain(
      "waiting for install entry",
    );
    const button = screen.getByTestId("pairing-refresh");
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("step 3 refresh button calls router.refresh once enabled", () => {
    refreshSpy.mockClear();
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    fireEvent.click(screen.getByTestId("pairing-tos-ack"));
    fireEvent.click(screen.getByTestId("pairing-refresh"));
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });

  it("step 3 cross-links back to /channels", () => {
    render(<WhatsAppPairingFlow hasInstall={false} tenantSlugUpper="BASEWORM" />);
    const link = screen.getByTestId("pairing-channels-link");
    expect(link).toHaveAttribute("href", "/channels");
  });

  it("renders a paired-success state when an install row exists", () => {
    render(<WhatsAppPairingFlow hasInstall={true} tenantSlugUpper="BASEWORM" />);
    expect(screen.getByTestId("whatsapp-pairing-success")).toBeInTheDocument();
    // The pairing steps are NOT rendered when paired.
    expect(screen.queryByTestId("pairing-step-1")).toBeNull();
    expect(screen.queryByTestId("pairing-step-2")).toBeNull();
    expect(screen.queryByTestId("pairing-step-3")).toBeNull();
  });

  it("paired-success links back to /channels", () => {
    render(<WhatsAppPairingFlow hasInstall={true} tenantSlugUpper="BASEWORM" />);
    const link = screen.getByTestId("whatsapp-pairing-success-channels");
    expect(link).toHaveAttribute("href", "/channels");
  });
});
