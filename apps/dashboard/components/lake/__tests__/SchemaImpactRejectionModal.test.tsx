/**
 * SchemaImpactRejectionModal component tests — L4 Sub-wave D.
 *
 * Pins the L4-distinct 5-value enum (false_positive / already_handled /
 * low_value / out_of_scope / other). L4's enum differs from L3's
 * (wrong_direction + low_confidence) and L7's (wrong_threshold +
 * low_value) by one value each — concern #4.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  SchemaImpactRejectionModal,
  SCHEMA_IMPACT_REJECT_REASONS,
} from "../SchemaImpactRejectionModal";

describe("SchemaImpactRejectionModal", () => {
  it("does not render when open=false", () => {
    const { container } = render(
      <SchemaImpactRejectionModal
        impactId="impact-001"
        open={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the strict 5-value L4 reason enum dropdown when open", () => {
    render(
      <SchemaImpactRejectionModal
        impactId="impact-001"
        open
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByTestId(
      "schema-impact-reject-reason",
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(
      SCHEMA_IMPACT_REJECT_REASONS.map((r) => r.value),
    );
    // L4 enum is distinct from L3 + L7: ships ``already_handled`` —
    // impact may be real but downstream already mitigated.
    expect(optionValues).toEqual([
      "false_positive",
      "already_handled",
      "low_value",
      "out_of_scope",
      "other",
    ]);
  });

  it("submits with the selected reason + trimmed notes", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    const onClose = vi.fn();
    render(
      <SchemaImpactRejectionModal
        impactId="impact-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("schema-impact-reject-reason"), {
      target: { value: "already_handled" },
    });
    fireEvent.change(screen.getByTestId("schema-impact-reject-notes"), {
      target: { value: "  downstream migrated last sprint  " },
    });
    fireEvent.click(screen.getByTestId("schema-impact-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "impact-001",
      "already_handled",
      "downstream migrated last sprint",
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits with no notes when textarea is empty", async () => {
    const onSubmit = vi.fn(async () => ({ ok: true }));
    render(
      <SchemaImpactRejectionModal
        impactId="impact-001"
        open
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("schema-impact-reject-submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(
      "impact-001",
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
      <SchemaImpactRejectionModal
        impactId="impact-001"
        open
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByTestId("schema-impact-reject-submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("schema-impact-reject-error"),
      ).toHaveTextContent("admin role required"),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
