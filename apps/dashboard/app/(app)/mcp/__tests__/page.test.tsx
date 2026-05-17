/**
 * /mcp page — renders catalog panel + recent calls table together.
 *
 * Block J6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 * Server-component test: we mock the ledger-client accessors so we
 * can exercise the page's composition without standing up Postgres.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/ledger-client", () => ({
  getMcpCalls: vi.fn(async () => []),
  getMcpCatalog: vi.fn(async () => ({ available: false, entries: [] })),
}));

import McpPage from "../page";

describe("/mcp page", () => {
  it("renders the page header, catalog panel, and recent calls table", async () => {
    const ui = await McpPage();
    render(ui);
    expect(screen.getByText("MCP")).toBeInTheDocument();
    expect(screen.getByText("Server catalog")).toBeInTheDocument();
    expect(screen.getByText("Recent calls")).toBeInTheDocument();
  });

  it("renders the rate-limit summary row with three stats", async () => {
    const ui = await McpPage();
    render(ui);
    const block = screen.getByTestId("mcp-rate-limit");
    expect(block).toBeInTheDocument();
    expect(block.textContent).toContain("Total recorded");
    expect(block.textContent).toContain("Last 60 min");
    expect(block.textContent).toContain("Last call");
  });

  it("renders the honest empty state when no calls + no catalog", async () => {
    const ui = await McpPage();
    render(ui);
    expect(screen.getByTestId("mcp-recent-calls-empty")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-catalog-empty")).toBeInTheDocument();
  });

  it("renders catalog rows + recent calls when both accessors return data", async () => {
    const lc = await import("../../../../lib/ledger-client");
    vi.mocked(lc.getMcpCatalog).mockResolvedValueOnce({
      available: true,
      entries: [
        {
          kind: "tool",
          name: "query_kpis",
          description: "Read the KPI tree.",
          tags: ["read"],
        },
      ],
    });
    vi.mocked(lc.getMcpCalls).mockResolvedValueOnce([
      {
        mcpCallId: "11111111-1111-1111-1111-111111111111",
        tenantId: "tenant-uuid",
        callerPersonId: null,
        toolName: "query_kpis",
        argsHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        clientUa: "claude-desktop/1",
        startedAt: "2026-04-27T10:00:00.000Z",
        outcome: "ok",
        latencyMs: 200,
        receipt: {
          hash: "0123456789ab",
          source: "mcp",
          owner: "mcp-anonymous",
          classification: "internal",
        },
      },
    ]);
    const ui = await McpPage();
    render(ui);
    // query_kpis appears in BOTH the catalog (as a tool name) AND the
    // recent calls table (as the called tool) — getAllByText.
    expect(screen.getAllByText("query_kpis").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByTestId("mcp-call-row")).toHaveLength(1);
    expect(screen.getAllByTestId("mcp-catalog-row-tool")).toHaveLength(1);
  });
});
