/**
 * SemanticGapQueue component tests (Wave 3 Task 5).
 *
 * Pure-presentational; the page handles the empty state. These tests
 * pin:
 *
 *   * One row per ``SemanticGapRow``, with the question + reason + agent
 *     visible in the DOM.
 *   * Clicking "Promote" opens the inline form with the gap's
 *     ``proposedMetricName`` pre-filled.
 *   * Submitting the form invokes the injected ``promoteAction`` with
 *     the entry id + form values.
 *   * Error path from the action surfaces an inline error and does
 *     NOT close the modal.
 *
 * Component uses ``"use client"``; jsdom + RTL is sufficient (no
 * server-only deps).
 */
import { describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { SemanticGapQueue } from "../SemanticGapQueue";
import type { SemanticGapRow } from "../../../lib/metrics-proposed";

function row(partial: Partial<SemanticGapRow> & Pick<SemanticGapRow, "id">): SemanticGapRow {
  return {
    id: partial.id,
    agentId: partial.agentId ?? "agent:acme",
    nlQuestion:
      partial.nlQuestion ?? "did our churn rate drop last week?",
    reason: partial.reason ?? "no_match",
    proposedMetricName:
      partial.proposedMetricName === undefined
        ? "weekly_churn_rate"
        : partial.proposedMetricName,
    proposedAt: partial.proposedAt ?? "2026-05-11T10:00:00.000Z",
    status: partial.status ?? "unresolved",
  };
}

describe("SemanticGapQueue", () => {
  it("renders one row per gap with question + reason + agent", () => {
    const rows = [
      row({ id: "gap-1", proposedMetricName: "weekly_churn_rate" }),
      row({
        id: "gap-2",
        reason: "ambiguous",
        proposedMetricName: null,
        nlQuestion: "is q3 ok?",
      }),
    ];
    render(<SemanticGapQueue rows={rows} promoteAction={vi.fn()} />);
    expect(screen.getByTestId("gap-row-gap-1")).toBeInTheDocument();
    expect(screen.getByTestId("gap-row-gap-2")).toBeInTheDocument();
    expect(screen.getByTestId("gap-question-gap-2").textContent).toContain(
      "is q3 ok?",
    );
    // Reason label is rendered human-friendly.
    expect(screen.getByTestId("gap-reason-gap-2").textContent).toContain(
      "ambiguous",
    );
  });

  it("opens the modal pre-filled with the proposed metric name", () => {
    const rows = [row({ id: "gap-1", proposedMetricName: "weekly_churn_rate" })];
    render(<SemanticGapQueue rows={rows} promoteAction={vi.fn()} />);
    fireEvent.click(screen.getByTestId("gap-promote-gap-1"));
    expect(screen.getByTestId("promote-modal-gap-1")).toBeInTheDocument();
    const nameInput = screen.getByTestId(
      "promote-metric-name",
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("weekly_churn_rate");
  });

  it("calls promoteAction with the form values on submit", async () => {
    const promote = vi.fn(async () => ({ ok: true }));
    const rows = [row({ id: "gap-1" })];
    render(<SemanticGapQueue rows={rows} promoteAction={promote} />);
    fireEvent.click(screen.getByTestId("gap-promote-gap-1"));

    const exprInput = screen.getByTestId(
      "promote-metric-expression",
    ) as HTMLTextAreaElement;
    fireEvent.change(exprInput, {
      target: { value: "SUM(churned) / COUNT(*)" },
    });

    const domainInput = screen.getByTestId(
      "promote-domain-id",
    ) as HTMLInputElement;
    fireEvent.change(domainInput, {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("promote-submit"));
    });

    await waitFor(() => {
      expect(promote).toHaveBeenCalledWith(
        "gap-1",
        "weekly_churn_rate",
        "SUM(churned) / COUNT(*)",
        "11111111-1111-1111-1111-111111111111",
      );
    });
  });

  it("shows an inline error and keeps the modal open when the action fails", async () => {
    const promote = vi.fn(async () => ({
      ok: false,
      error: "promote_semantic_gap endpoint v1.1",
    }));
    const rows = [row({ id: "gap-1" })];
    render(<SemanticGapQueue rows={rows} promoteAction={promote} />);
    fireEvent.click(screen.getByTestId("gap-promote-gap-1"));

    // Provide the rest of the form
    const exprInput = screen.getByTestId(
      "promote-metric-expression",
    ) as HTMLTextAreaElement;
    fireEvent.change(exprInput, { target: { value: "1" } });
    const domainInput = screen.getByTestId(
      "promote-domain-id",
    ) as HTMLInputElement;
    fireEvent.change(domainInput, {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("promote-submit"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("promote-error").textContent).toContain(
        "endpoint v1.1",
      );
    });
    // Modal stays open so the admin can retry.
    expect(screen.queryByTestId("promote-modal-gap-1")).toBeInTheDocument();
  });

  it("closes the modal on cancel without calling the action", () => {
    const promote = vi.fn();
    const rows = [row({ id: "gap-1" })];
    render(<SemanticGapQueue rows={rows} promoteAction={promote} />);
    fireEvent.click(screen.getByTestId("gap-promote-gap-1"));
    expect(screen.getByTestId("promote-modal-gap-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("promote-cancel"));
    expect(screen.queryByTestId("promote-modal-gap-1")).not.toBeInTheDocument();
    expect(promote).not.toHaveBeenCalled();
  });

  it("renders an em-dash when proposed_metric_name is null", () => {
    const rows = [row({ id: "gap-1", proposedMetricName: null })];
    render(<SemanticGapQueue rows={rows} promoteAction={vi.fn()} />);
    const cell = screen.getByTestId("gap-metric-gap-1");
    expect(cell.textContent).toBe("—");
  });
});
