/**
 * NotebooksTable — renders rows, sorts on header click.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { NotebooksTable } from "../../components/notebooks/NotebooksTable";
import type { NotebookRow } from "../../lib/ledger-client.types";

function nb(over: Partial<NotebookRow> = {}): NotebookRow {
  return {
    notebookId: "11111111-1111-1111-1111-111111111111",
    tenantId: "tenant",
    name: "CFO autoresearch",
    kernel: "python_local",
    status: "published",
    ownerPersonId: "p1",
    domainId: null,
    latestRunId: "r1",
    latestPublishedRunId: "r1",
    version: "1",
    cells: [],
    receipt: {
      hash: "abc",
      source: "ledger",
      owner: "p1",
      classification: "internal",
    },
    ...over,
  };
}

const notebooks: NotebookRow[] = [
  nb({
    notebookId: "22222222-2222-2222-2222-222222222222",
    name: "Beta",
    status: "proposed",
    version: null,
  }),
  nb({
    notebookId: "11111111-1111-1111-1111-111111111111",
    name: "Alpha",
    status: "published",
    version: "1",
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NotebooksTable", () => {
  it("renders one row per notebook", () => {
    render(<NotebooksTable notebooks={notebooks} />);
    const rows = screen.getAllByTestId("notebook-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("renders status chips", () => {
    render(<NotebooksTable notebooks={notebooks} />);
    expect(screen.getByText("published")).toBeInTheDocument();
    expect(screen.getByText("proposed")).toBeInTheDocument();
  });

  it("links the name to the drill-in page", () => {
    render(<NotebooksTable notebooks={notebooks} />);
    const link = screen.getByText("Alpha").closest("a");
    expect(link).toHaveAttribute(
      "href",
      "/notebooks/11111111-1111-1111-1111-111111111111",
    );
  });

  it("renders empty-state when no notebooks", () => {
    render(<NotebooksTable notebooks={[]} />);
    expect(screen.getByText(/No notebooks yet/i)).toBeInTheDocument();
  });

  it("toggles sort direction when the same header is clicked twice", () => {
    render(<NotebooksTable notebooks={notebooks} />);
    // Default is name asc → Alpha first.
    let firstName = screen
      .getAllByTestId("notebook-row")[0]
      .querySelector("a")?.textContent;
    expect(firstName).toBe("Alpha");
    // Click Name → toggles to desc → Beta first.
    fireEvent.click(screen.getByText("Name"));
    firstName = screen
      .getAllByTestId("notebook-row")[0]
      .querySelector("a")?.textContent;
    expect(firstName).toBe("Beta");
  });
});
