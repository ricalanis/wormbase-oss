/**
 * QualityRejectionModal component tests — L7 Sub-wave D.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  QualityRejectionModal,
  QUALITY_REJECT_REASONS,
} from "../QualityRejectionModal";

describe("QualityRejectionModal", () => {
  it("does not render when open=false", () => {
    const { container } = render(
      <QualityRejectionModal
        checkId="check-001"
        open={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the strict 5-value reason enum dropdown when open", () => {
    render(
      <QualityRejectionModal
        checkId="check-001"
        open
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByTestId(
      "quality-reject-reason",
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(QUALITY_REJECT_REASONS.map((r) => r.value));
    // The L7 enum is distinct from L3 — false_positive / low_value /
    // wrong_threshold / out_of_scope / other.
    expect(optionValues).toEqual([
      "false_positive",
      "low_value",
      "wrong_threshold",
      "out_of_scope",
      "other",
    ]);
  });

  it("submits with the selected reason + trimmed notes", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    const onClose = vi.fn();
    render(
      <QualityRejectionModal
        checkId="check-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("quality-reject-reason"), {
      target: { value: "wrong_threshold" },
    });
    fireEvent.change(screen.getByTestId("quality-reject-notes"), {
      target: { value: "  threshold too tight  " },
    });
    fireEvent.click(screen.getByTestId("quality-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "check-001",
      "wrong_threshold",
      "threshold too tight",
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits with no notes when textarea is empty", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    render(
      <QualityRejectionModal
        checkId="check-001"
        open
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("quality-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "check-001",
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
      <QualityRejectionModal
        checkId="check-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("quality-reject-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("quality-reject-error")).toHaveTextContent(
        "admin role required",
      ),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
