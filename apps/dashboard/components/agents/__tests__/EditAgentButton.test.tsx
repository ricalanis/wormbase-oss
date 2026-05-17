/**
 * EditAgentButton component tests (final wave item #5, 2026-05-13).
 *
 * Pins:
 *   * Idle render: an "Edit (admin)" chip is visible; the modal is not.
 *   * Click opens the modal pre-filled with the agent's current values.
 *   * Submit disabled when fields match current values (no-op guard).
 *   * Changing display_name enables Submit and calls the action with
 *     the trimmed new value + description=null (unchanged sentinel).
 *   * Description-only change posts displayName=null + the new description.
 *   * Failure surfaces the error inline; modal stays open for retry.
 *   * Cancel closes the modal and resets the form back to current values.
 *
 * Note: success-path navigation uses `window.location.href` which jsdom
 * doesn't fully implement; we stub it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { EditAgentButton } from "../EditAgentButton";

beforeEach(() => {
  Object.defineProperty(window, "location", {
    writable: true,
    value: { href: "" } as Location,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EditAgentButton", () => {
  it("renders the edit chip and hides the modal initially", () => {
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        currentDescription="Daily DS agent."
        updateAction={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("agent-detail-edit-button"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-detail-edit-modal"),
    ).not.toBeInTheDocument();
  });

  it("opens the modal pre-filled with the agent's current values", () => {
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        currentDescription="Daily DS agent."
        updateAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    expect(
      screen.getByTestId("agent-detail-edit-modal"),
    ).toBeInTheDocument();
    const nameInput = screen.getByTestId(
      "agent-detail-edit-display-name",
    ) as HTMLInputElement;
    const descInput = screen.getByTestId(
      "agent-detail-edit-description",
    ) as HTMLTextAreaElement;
    expect(nameInput.value).toBe("Pip the Worm");
    expect(descInput.value).toBe("Daily DS agent.");
  });

  it("keeps Submit disabled until at least one field changes", () => {
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        currentDescription="Daily DS agent."
        updateAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    const confirm = screen.getByTestId(
      "agent-detail-edit-confirm",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    // Touching but not changing the value should keep Submit disabled.
    const nameInput = screen.getByTestId(
      "agent-detail-edit-display-name",
    );
    fireEvent.change(nameInput, { target: { value: "Pip the Worm" } });
    expect(confirm.disabled).toBe(true);

    // Real change enables Submit.
    fireEvent.change(nameInput, { target: { value: "Pip the DS Worm" } });
    expect(confirm.disabled).toBe(false);
  });

  it("posts displayName + description=null on a name-only change", async () => {
    const action = vi.fn().mockResolvedValue({ ok: true });
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        currentDescription="Daily DS agent."
        updateAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-edit-display-name"),
      { target: { value: "Pip the DS Worm" } },
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalledWith({
        agentId: "agent-123",
        displayName: "Pip the DS Worm",
        description: null,
        reason: null,
      });
    });
    await waitFor(() => {
      expect(window.location.href).toContain(
        "/people/agents/agent-123?edited=1",
      );
    });
  });

  it("posts displayName=null + new description on a description-only change", async () => {
    const action = vi.fn().mockResolvedValue({ ok: true });
    render(
      <EditAgentButton
        agentId="agent-456"
        currentDisplayName="Pip"
        currentDescription="Daily DS agent."
        updateAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-edit-description"),
      {
        target: { value: "Now also covers compliance." },
      },
    );
    fireEvent.change(screen.getByTestId("agent-detail-edit-reason"), {
      target: { value: "quarterly scope refresh" },
    });
    fireEvent.click(screen.getByTestId("agent-detail-edit-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalledWith({
        agentId: "agent-456",
        displayName: null,
        description: "Now also covers compliance.",
        reason: "quarterly scope refresh",
      });
    });
  });

  it("surfaces the error inline when the action fails", async () => {
    const action = vi
      .fn()
      .mockResolvedValue({ ok: false, error: "worm-core API 422: bad input" });
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip"
        currentDescription={null}
        updateAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-edit-display-name"),
      { target: { value: "Pip the New" } },
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("agent-detail-edit-error").textContent,
      ).toContain("worm-core API 422");
    });
    // Modal still open for retry.
    expect(
      screen.getByTestId("agent-detail-edit-modal"),
    ).toBeInTheDocument();
  });

  it("closes the modal on cancel and resets the form", () => {
    render(
      <EditAgentButton
        agentId="agent-123"
        currentDisplayName="Pip"
        currentDescription="orig"
        updateAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    fireEvent.change(
      screen.getByTestId("agent-detail-edit-display-name"),
      { target: { value: "Edited Locally" } },
    );
    fireEvent.click(screen.getByTestId("agent-detail-edit-cancel"));
    expect(
      screen.queryByTestId("agent-detail-edit-modal"),
    ).not.toBeInTheDocument();

    // Reopen — fields should be reset to current values, not last edit.
    fireEvent.click(screen.getByTestId("agent-detail-edit-button"));
    const nameInput = screen.getByTestId(
      "agent-detail-edit-display-name",
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("Pip");
  });
});
