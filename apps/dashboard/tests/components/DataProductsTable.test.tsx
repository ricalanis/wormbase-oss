/**
 * DataProductsTable — renders rows, sorts on header click, status chip text.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { DataProductsTable } from "../../components/data-products/DataProductsTable";
import type { DataProductRow } from "../../lib/ledger-client.types";

function dp(over: Partial<DataProductRow> = {}): DataProductRow {
  return {
    dataProductId: "11111111-1111-1111-1111-111111111111",
    tenantId: "tenant",
    name: "Q3 Net Revenue",
    kind: "report",
    status: "generated",
    requestedByPersonId: "p1",
    domainId: null,
    generatedAt: "2026-04-25T10:00:00Z",
    contentHash: "abc",
    contentsUri: "file:///tmp/x.html",
    receipt: {
      hash: "abc",
      source: "ledger",
      owner: "p1",
      classification: "internal",
    },
    ...over,
  };
}

const dps: DataProductRow[] = [
  dp({
    dataProductId: "22222222-2222-2222-2222-222222222222",
    name: "Beta",
    kind: "chart",
    status: "proposed",
    generatedAt: null,
  }),
  dp({
    dataProductId: "11111111-1111-1111-1111-111111111111",
    name: "Alpha",
    kind: "report",
    status: "generated",
    generatedAt: "2026-04-25T10:00:00Z",
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("DataProductsTable", () => {
  it("renders one row per data product", () => {
    render(<DataProductsTable dataProducts={dps} />);
    const rows = screen.getAllByTestId("data-product-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("renders status chips", () => {
    render(<DataProductsTable dataProducts={dps} />);
    expect(screen.getByText("generated")).toBeInTheDocument();
    expect(screen.getByText("proposed")).toBeInTheDocument();
  });

  it("renders kind chips", () => {
    render(<DataProductsTable dataProducts={dps} />);
    expect(screen.getByText("report")).toBeInTheDocument();
    expect(screen.getByText("chart")).toBeInTheDocument();
  });

  it("name links to the drill-in page", () => {
    render(<DataProductsTable dataProducts={dps} />);
    const link = screen.getByText("Alpha").closest("a");
    expect(link).toHaveAttribute(
      "href",
      "/data-products/11111111-1111-1111-1111-111111111111",
    );
  });

  it("renders an empty-state when there are no products", () => {
    render(<DataProductsTable dataProducts={[]} />);
    expect(
      screen.getByText(/No data products yet/i),
    ).toBeInTheDocument();
  });

  it("sorts by name when the Name header is clicked", () => {
    render(<DataProductsTable dataProducts={dps} />);
    fireEvent.click(screen.getByText("Name"));
    const rows = screen.getAllByTestId("data-product-row");
    // After clicking Name once: ascending → Alpha first
    const firstName = rows[0].querySelector("a")?.textContent;
    expect(firstName).toBe("Alpha");
  });
});
