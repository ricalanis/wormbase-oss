/**
 * ColumnClassificationRejectionModal component tests — L6 Sub-wave D.
 *
 * Pins the L6-distinct 5-value enum (false_positive / low_value /
 * wrong_level / out_of_scope / other). L6's enum differs from L3's
 * (wrong_direction + low_confidence), L4's (already_handled),
 * L5's (wrong_type), and L7's (wrong_threshold) by one value each.
 * The 5th L6-specific value is ``wrong_level``.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  ColumnClassificationRejectionModal,
  COLUMN_CLASSIFICATION_REJECT_REASONS,
} from "../ColumnClassificationRejectionModal";

describe("ColumnClassificationRejectionModal", () => {
  it("does not render when open=false", () => {
    const { container } = render(
      <ColumnClassificationRejectionModal
        classificationId="cls-001"
        open={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the strict 5-value L6 reason enum dropdown when open", () => {
    render(
      <ColumnClassificationRejectionModal
        classificationId="cls-001"
        open
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByTestId(
      "column-classification-reject-reason",
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(
      COLUMN_CLASSIFICATION_REJECT_REASONS.map((r) => r.value),
    );
    // L6 enum is distinct: ships ``wrong_level`` — the strategy picked
    // the wrong level from the 5-value enum.
    expect(optionValues).toEqual([
      "false_positive",
      "low_value",
      "wrong_level",
      "out_of_scope",
      "other",
    ]);
  });

  it("submits with the selected reason + trimmed notes", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    const onClose = vi.fn();
    render(
      <ColumnClassificationRejectionModal
        classificationId="cls-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("column-classification-reject-reason"), {
      target: { value: "wrong_level" },
    });
    fireEvent.change(screen.getByTestId("column-classification-reject-notes"), {
      target: { value: "  pii not regulated  " },
    });
    fireEvent.click(screen.getByTestId("column-classification-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "cls-001",
      "wrong_level",
      "pii not regulated",
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits with no notes when textarea is empty", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    render(
      <ColumnClassificationRejectionModal
        classificationId="cls-001"
        open
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("column-classification-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "cls-001",
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
      <ColumnClassificationRejectionModal
        classificationId="cls-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("column-classification-reject-submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("column-classification-reject-error"),
      ).toHaveTextContent("admin role required"),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
