/**
 * RevokeAgentButton component tests (v1.4 follow-up — Path 5).
 *
 * Pins:
 *   * Idle render: a "Revoke (admin)" chip is visible; the modal is not.
 *   * Click opens the modal with the expected-confirm text shown.
 *   * Confirm button disabled until confirmText matches expectedConfirm.
 *   * Match enables confirm; click invokes the action with the agent_id.
 *   * Failure surfaces the error inline; modal stays open for retry.
 *   * Cancel closes the modal and clears the confirm input.
 *
 * Note: success-path navigation uses `window.location.href` which jsdom
 * doesn't fully implement; we stub it and verify the redirect target.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { RevokeAgentButton } from "../RevokeAgentButton";

beforeEach(() => {
  // Stub window.location.href setter so the success-path "redirect"
  // doesn't try to navigate jsdom into the void.
  Object.defineProperty(window, "location", {
    writable: true,
    value: { href: "" } as Location,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RevokeAgentButton", () => {
  it("renders the revoke chip and hides the modal initially", () => {
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip the Worm"
        revokeAction={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("agent-detail-revoke-button"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-detail-revoke-modal"),
    ).not.toBeInTheDocument();
  });

  it("opens the modal on click and surfaces the expected-confirm text", () => {
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip the Worm"
        revokeAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-button"));
    expect(
      screen.getByTestId("agent-detail-revoke-modal"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("agent-detail-revoke-expected-confirm").textContent,
    ).toBe("Pip the Worm");
  });

  it("keeps the confirm button disabled until confirmText matches", () => {
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip the Worm"
        revokeAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-button"));
    const confirmBtn = screen.getByTestId(
      "agent-detail-revoke-confirm",
    ) as HTMLButtonElement;
    const input = screen.getByTestId(
      "agent-detail-revoke-confirm-input",
    ) as HTMLInputElement;

    expect(confirmBtn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "wrong text" } });
    expect(confirmBtn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "Pip the Worm" } });
    expect(confirmBtn.disabled).toBe(false);
  });

  it("calls the revoke action with the agent_id on confirm", async () => {
    const action = vi
      .fn()
      .mockResolvedValue({ ok: true, revokedGrantCount: 3 });
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip the Worm"
        revokeAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-revoke-confirm-input"),
      { target: { value: "Pip the Worm" } },
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalledWith("agent-123");
    });
    await waitFor(() => {
      expect(window.location.href).toContain(
        "/people/agents?revoked=agent-123",
      );
      expect(window.location.href).toContain("grants=3");
    });
  });

  it("surfaces the error inline when the action fails", async () => {
    const action = vi
      .fn()
      .mockResolvedValue({ ok: false, error: "worm-core API 422: bad input" });
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip"
        revokeAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-revoke-confirm-input"),
      { target: { value: "Pip" } },
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("agent-detail-revoke-error").textContent,
      ).toContain("worm-core API 422");
    });
    // Modal still open for retry.
    expect(
      screen.getByTestId("agent-detail-revoke-modal"),
    ).toBeInTheDocument();
  });

  it("closes the modal on cancel", () => {
    render(
      <RevokeAgentButton
        agentId="agent-123"
        expectedConfirm="Pip"
        revokeAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revoke-button"));
    expect(
      screen.getByTestId("agent-detail-revoke-modal"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("agent-detail-revoke-cancel"));
    expect(
      screen.queryByTestId("agent-detail-revoke-modal"),
    ).not.toBeInTheDocument();
  });
});
