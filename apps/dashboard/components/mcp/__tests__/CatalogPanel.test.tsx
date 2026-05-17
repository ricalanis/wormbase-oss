/**
 * CatalogPanel — empty state, three section render, populated rows.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { CatalogPanel } from "../CatalogPanel";
import type { McpCatalog, McpCatalogEntry } from "../../../lib/ledger-client.types";

function entry(over: Partial<McpCatalogEntry> = {}): McpCatalogEntry {
  return {
    kind: "tool",
    name: "query_kpis",
    description: "Read the KPI tree.",
    tags: ["read"],
    ...over,
  };
}

describe("CatalogPanel", () => {
  it("renders the not-yet-running empty state when the server is unavailable", () => {
    const catalog: McpCatalog = { available: false, entries: [] };
    render(<CatalogPanel catalog={catalog} />);
    expect(screen.getByTestId("mcp-catalog-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/The MCP server isn't reachable yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("mcp-catalog")).not.toBeInTheDocument();
  });

  it("renders all three sections when the server is available, even when empty", () => {
    const catalog: McpCatalog = { available: true, entries: [] };
    render(<CatalogPanel catalog={catalog} />);
    expect(screen.getByTestId("mcp-catalog")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-tool")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-resource")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-tool-empty")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-resource-empty")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-section-prompt-empty")).toBeInTheDocument();
  });

  it("groups entries by kind and renders rows for each", () => {
    const catalog: McpCatalog = {
      available: true,
      entries: [
        entry({ kind: "tool", name: "query_kpis" }),
        entry({ kind: "tool", name: "query_decisions" }),
        entry({ kind: "resource", name: "wormbase://kpis/{company_id}/tree", description: "KPI tree", tags: [] }),
        entry({ kind: "prompt", name: "audit_decision", description: "Walk a decision." }),
      ],
    };
    render(<CatalogPanel catalog={catalog} />);
    expect(screen.getAllByTestId("mcp-catalog-row-tool")).toHaveLength(2);
    expect(screen.getAllByTestId("mcp-catalog-row-resource")).toHaveLength(1);
    expect(screen.getAllByTestId("mcp-catalog-row-prompt")).toHaveLength(1);
    expect(screen.getByText("query_kpis")).toBeInTheDocument();
    expect(screen.getByText("audit_decision")).toBeInTheDocument();
  });

  it("renders entry tags as chips and survives missing tags", () => {
    const catalog: McpCatalog = {
      available: true,
      entries: [
        entry({ name: "query_kpis", tags: ["read", "tier-1"] }),
        entry({ name: "propose_data_product", tags: undefined }),
      ],
    };
    render(<CatalogPanel catalog={catalog} />);
    expect(screen.getByText("read")).toBeInTheDocument();
    expect(screen.getByText("tier-1")).toBeInTheDocument();
    expect(screen.getByText("propose_data_product")).toBeInTheDocument();
  });
});
