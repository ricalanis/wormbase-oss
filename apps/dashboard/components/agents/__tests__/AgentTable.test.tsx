/**
 * Tests for AgentTable (Wave 3 Task 2).
 *
 * Pure presentational; the /people/agents page handles the empty state.
 * These tests pin:
 *
 *   * One `<tr>` per agent plus the header row
 *   * The agent link points to the per-agent detail route
 *   * Sortable header — clicking a column header re-orders rows
 *   * Active / revoked status pill renders distinctly
 *   * Budget formats as USD; null budget renders an em dash
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { AgentTable } from "../AgentTable";
import type { Agent } from "../../../lib/agents";

function agent(partial: Partial<Agent> & Pick<Agent, "id">): Agent {
  return {
    id: partial.id,
    personId: partial.personId ?? partial.id,
    externalProvider: partial.externalProvider ?? "claude",
    displayName: partial.displayName ?? "Test Agent",
    registeredAt: partial.registeredAt ?? "2026-05-11T10:00:00.000Z",
    registeredByPersonId: partial.registeredByPersonId ?? "admin-1",
    status: partial.status ?? "active",
    activeGrantCount: partial.activeGrantCount ?? 0,
    budgetRemainingUsdSum: partial.budgetRemainingUsdSum ?? null,
  };
}

describe("AgentTable", () => {
  it("renders one row per agent", () => {
    const rows = [
      agent({ id: "00000000-0000-0000-0000-000000000001" }),
      agent({ id: "00000000-0000-0000-0000-000000000002" }),
    ];
    render(<AgentTable rows={rows} />);
    expect(
      screen.getByTestId("agents-row-00000000-0000-0000-0000-000000000001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("agents-row-00000000-0000-0000-0000-000000000002"),
    ).toBeInTheDocument();
  });

  it("emits a click-through link to the per-agent detail route", () => {
    const rows = [agent({ id: "abc12345-0000-0000-0000-000000000001" })];
    render(<AgentTable rows={rows} />);
    const link = screen.getByTestId(
      "agents-row-link-abc12345-0000-0000-0000-000000000001",
    );
    expect(link).toHaveAttribute(
      "href",
      "/people/agents/abc12345-0000-0000-0000-000000000001",
    );
  });

  it("renders activeGrantCount and formatted budget", () => {
    const rows = [
      agent({
        id: "agent-with-budget",
        activeGrantCount: 3,
        budgetRemainingUsdSum: "12.5000",
      }),
      agent({
        id: "agent-no-budget",
        activeGrantCount: 0,
        budgetRemainingUsdSum: null,
      }),
    ];
    render(<AgentTable rows={rows} />);
    expect(screen.getByText("$12.50")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("toggles sort direction on repeat header clicks", () => {
    const rows = [
      agent({
        id: "a-1",
        displayName: "Zebra",
        registeredAt: "2026-05-09T00:00:00.000Z",
      }),
      agent({
        id: "a-2",
        displayName: "Aardvark",
        registeredAt: "2026-05-10T00:00:00.000Z",
      }),
    ];
    const { container } = render(<AgentTable rows={rows} />);
    const header = screen.getByTestId("agents-th-displayName");
    fireEvent.click(header);
    // First click on displayName → ascending. Zebra > Aardvark, so
    // Aardvark must precede Zebra in DOM order.
    const bodyRows = container.querySelectorAll("tbody tr");
    expect(bodyRows[0].textContent).toContain("Aardvark");
    expect(bodyRows[1].textContent).toContain("Zebra");
    fireEvent.click(header);
    const bodyRowsDesc = container.querySelectorAll("tbody tr");
    expect(bodyRowsDesc[0].textContent).toContain("Zebra");
    expect(bodyRowsDesc[1].textContent).toContain("Aardvark");
  });

  it("renders status pill distinctly for active vs inactive", () => {
    const rows = [
      agent({ id: "active-1", status: "active" }),
      agent({ id: "inactive-1", status: "inactive" }),
    ];
    render(<AgentTable rows={rows} />);
    expect(screen.getByTestId("agents-status-active")).toBeInTheDocument();
    expect(screen.getByTestId("agents-status-inactive")).toBeInTheDocument();
  });
});
