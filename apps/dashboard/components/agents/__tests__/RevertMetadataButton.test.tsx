/**
 * RevertMetadataButton component tests (post-rest path #4, 2026-05-13).
 *
 * Pins:
 *   * Does NOT render when hasPriorUpdate is false (no revert target).
 *   * Renders a "Revert (admin)" chip when hasPriorUpdate is true.
 *   * Click opens the modal showing the agent's current display name.
 *   * Confirm calls the action with the agent_id and an optional reason.
 *   * Failure surfaces the error inline; modal stays open for retry.
 *   * Cancel closes the modal.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { RevertMetadataButton } from "../RevertMetadataButton";

beforeEach(() => {
  Object.defineProperty(window, "location", {
    writable: true,
    value: { href: "" } as Location,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RevertMetadataButton", () => {
  it("does not render when hasPriorUpdate is false", () => {
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        hasPriorUpdate={false}
        revertAction={vi.fn()}
      />,
    );
    expect(
      screen.queryByTestId("agent-detail-revert-button"),
    ).not.toBeInTheDocument();
  });

  it("renders the revert chip when hasPriorUpdate is true", () => {
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        hasPriorUpdate={true}
        revertAction={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("agent-detail-revert-button"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-detail-revert-modal"),
    ).not.toBeInTheDocument();
  });

  it("opens a confirm modal showing the agent's display name", () => {
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip the Worm"
        hasPriorUpdate={true}
        revertAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revert-button"));
    expect(
      screen.getByTestId("agent-detail-revert-modal"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("agent-detail-revert-target-name").textContent,
    ).toBe("Pip the Worm");
  });

  it("calls the action with agent_id + optional reason on confirm", async () => {
    const action = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip"
        hasPriorUpdate={true}
        revertAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revert-button"));
    fireEvent.change(screen.getByTestId("agent-detail-revert-reason"), {
      target: { value: "accidental rename" },
    });
    fireEvent.click(screen.getByTestId("agent-detail-revert-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalledWith({
        agentId: "agent-123",
        reason: "accidental rename",
      });
    });
    await waitFor(() => {
      expect(window.location.href).toContain(
        "/people/agents/agent-123?reverted=1",
      );
    });
  });

  it("posts reason=null when the audit note is empty", async () => {
    const action = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RevertMetadataButton
        agentId="agent-456"
        currentDisplayName="Pip"
        hasPriorUpdate={true}
        revertAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revert-button"));
    fireEvent.click(screen.getByTestId("agent-detail-revert-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalledWith({
        agentId: "agent-456",
        reason: null,
      });
    });
  });

  it("surfaces the error inline when the action fails", async () => {
    const action = vi
      .fn()
      .mockResolvedValue({ ok: false, error: "worm-core API 400: no prior" });
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip"
        hasPriorUpdate={true}
        revertAction={action}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revert-button"));
    fireEvent.click(screen.getByTestId("agent-detail-revert-confirm"));

    await waitFor(() => {
      expect(action).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("agent-detail-revert-error").textContent,
      ).toContain("worm-core API 400");
    });
    // Modal still open for retry.
    expect(
      screen.getByTestId("agent-detail-revert-modal"),
    ).toBeInTheDocument();
  });

  it("closes the modal on cancel", () => {
    render(
      <RevertMetadataButton
        agentId="agent-123"
        currentDisplayName="Pip"
        hasPriorUpdate={true}
        revertAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("agent-detail-revert-button"));
    fireEvent.click(screen.getByTestId("agent-detail-revert-cancel"));
    expect(
      screen.queryByTestId("agent-detail-revert-modal"),
    ).not.toBeInTheDocument();
  });
});
