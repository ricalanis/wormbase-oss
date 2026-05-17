/**
 * LineageRejectionModal component tests — L3 Sub-wave D.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  LineageRejectionModal,
  REJECT_REASONS,
} from "../LineageRejectionModal";

describe("LineageRejectionModal", () => {
  it("does not render when open=false", () => {
    const { container } = render(
      <LineageRejectionModal
        edgeId="edge-001"
        open={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the strict 5-value reason enum dropdown when open", () => {
    render(
      <LineageRejectionModal
        edgeId="edge-001"
        open
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByTestId(
      "lineage-reject-reason",
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(REJECT_REASONS.map((r) => r.value));
    expect(optionValues).toEqual([
      "false_positive",
      "wrong_direction",
      "low_confidence",
      "out_of_scope",
      "other",
    ]);
  });

  it("submits with the selected reason + trimmed notes", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    const onClose = vi.fn();
    render(
      <LineageRejectionModal
        edgeId="edge-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("lineage-reject-reason"), {
      target: { value: "wrong_direction" },
    });
    fireEvent.change(screen.getByTestId("lineage-reject-notes"), {
      target: { value: "  src and tgt are flipped  " },
    });
    fireEvent.click(screen.getByTestId("lineage-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "edge-001",
      "wrong_direction",
      "src and tgt are flipped",
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits with no notes when textarea is empty", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    render(
      <LineageRejectionModal
        edgeId="edge-001"
        open
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("lineage-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "edge-001",
      "false_positive",
      undefined,
    );
  });

  it("surfaces an error banner when the action returns ok=false", async () => {
    const onSubmit = vi.fn(async () => ({
      ok: false,
      error: "admin role required",
    }));
    const onClose = vi.fn();
    render(
      <LineageRejectionModal
        edgeId="edge-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("lineage-reject-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("lineage-reject-error")).toHaveTextContent(
        "admin role required",
      ),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
