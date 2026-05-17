/**
 * SemanticTypeRejectionModal component tests — L5 Sub-wave D (2026-06-05).
 *
 * Pins the L5-distinct 5-value enum (false_positive / low_value /
 * wrong_type / out_of_scope / other). L5's enum differs from L3's
 * (wrong_direction + low_confidence), L4's (already_handled +
 * low_value), and L7's (wrong_threshold + low_value) by one value
 * each. The L5-specific 5th value is ``wrong_type``.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  SemanticTypeRejectionModal,
  SEMANTIC_TYPE_REJECT_REASONS,
} from "../SemanticTypeRejectionModal";

describe("SemanticTypeRejectionModal", () => {
  it("does not render when open=false", () => {
    const { container } = render(
      <SemanticTypeRejectionModal
        typeId="type-001"
        open={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the strict 5-value L5 reason enum dropdown when open", () => {
    render(
      <SemanticTypeRejectionModal
        typeId="type-001"
        open
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByTestId(
      "semantic-type-reject-reason",
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(
      SEMANTIC_TYPE_REJECT_REASONS.map((r) => r.value),
    );
    // L5 enum is distinct: ships ``wrong_type`` — the column IS
    // semantically typed but the strategy picked the wrong type from
    // the 19-value enum. Pin exact ordering here.
    expect(optionValues).toEqual([
      "false_positive",
      "low_value",
      "wrong_type",
      "out_of_scope",
      "other",
    ]);
  });

  it("submits with the selected reason + trimmed notes", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    const onClose = vi.fn();
    render(
      <SemanticTypeRejectionModal
        typeId="type-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("semantic-type-reject-reason"), {
      target: { value: "wrong_type" },
    });
    fireEvent.change(screen.getByTestId("semantic-type-reject-notes"), {
      target: { value: "  this is phone_e164, not email  " },
    });
    fireEvent.click(screen.getByTestId("semantic-type-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "type-001",
      "wrong_type",
      "this is phone_e164, not email",
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits with no notes when textarea is empty", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    render(
      <SemanticTypeRejectionModal
        typeId="type-001"
        open
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("semantic-type-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "type-001",
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
      <SemanticTypeRejectionModal
        typeId="type-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("semantic-type-reject-submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("semantic-type-reject-error"),
      ).toHaveTextContent("admin role required"),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
