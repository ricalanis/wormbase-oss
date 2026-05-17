/**
 * CellByCellView — markdown + code cells side-by-side with run outputs (W2.A8).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { CellByCellView } from "../../components/notebooks/CellByCellView";
import type {
  NotebookCell,
  NotebookRunRow,
} from "../../lib/ledger-client.types";

const cells: NotebookCell[] = [
  {
    kind: "markdown",
    source: "# Hypothesis\n\nQ3 net revenue grew QoQ.",
  },
  {
    kind: "code",
    source: "x = 5\nx * 2",
    language: "python",
  },
  {
    kind: "sql",
    source: "select count(*) from net_revenue;",
    language: "sql",
  },
];

const run: NotebookRunRow = {
  runId: "r1",
  notebookId: "nb1",
  tenantId: "t1",
  status: "ok",
  ts: "2026-04-28T00:00:00Z",
  runBy: "worm",
  kernelStateHash: "k".repeat(64),
  durationMs: 12,
  cellOutputs: [
    {},
    { status: "ok", value: 10 },
    { status: "ok", stdout: "1234" },
  ],
  cellHashes: ["h1", "h2", "h3"],
};

describe("CellByCellView", () => {
  it("renders one article per cell with the cell kind in a data attribute", () => {
    render(<CellByCellView cells={cells} latestRun={run} />);
    const articles = screen.getAllByTestId(/^cell-by-cell-cell-/);
    expect(articles).toHaveLength(3);
    expect(articles[0].getAttribute("data-cell-kind")).toBe("markdown");
    expect(articles[1].getAttribute("data-cell-kind")).toBe("code");
    expect(articles[2].getAttribute("data-cell-kind")).toBe("sql");
  });

  it("renders code cells in monospace and includes the source text", () => {
    render(<CellByCellView cells={cells} latestRun={run} />);
    const code = screen.getByTestId("cell-source-1");
    expect(code.textContent).toContain("x = 5");
    expect(code.textContent).toContain("x * 2");
  });

  it("renders markdown cells with heading text, but not the leading '#'", () => {
    render(<CellByCellView cells={cells} latestRun={run} />);
    expect(screen.getByText("Hypothesis")).toBeInTheDocument();
    expect(screen.queryByText("# Hypothesis")).toBeNull();
  });

  it("aligns each output with its cell index", () => {
    render(<CellByCellView cells={cells} latestRun={run} />);
    const out1 = screen.getByTestId("cell-output-1");
    expect(out1.textContent).toContain("=> 10");
    const out2 = screen.getByTestId("cell-output-2");
    expect(out2.textContent).toContain("1234");
    // First markdown cell has no output → "ok · no output" placeholder.
    const out0 = screen.getByTestId("cell-output-0");
    expect(out0.textContent).toMatch(/no output|no run yet/);
  });

  it("renders an honest empty-state when no cells exist", () => {
    render(<CellByCellView cells={[]} />);
    expect(screen.getByTestId("cell-by-cell-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/no cells yet/i),
    ).toBeInTheDocument();
  });
});
