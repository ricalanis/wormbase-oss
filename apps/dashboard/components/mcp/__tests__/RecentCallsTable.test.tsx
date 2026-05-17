/**
 * RecentCallsTable — empty state, populated state, args-hash masked.
 *
 * Block J6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 * The audit log is privacy-sensitive (spec §8.3); these tests pin the
 * contract that ``args_hash`` is masked to the first 12 hex chars +
 * ellipsis + last 4, that ``caller_person_id`` is masked too, and that
 * the empty state renders the canonical "no MCP calls yet" copy.
 */
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { RecentCallsTable } from "../RecentCallsTable";
import type { McpCallRow } from "../../../lib/ledger-client.types";

function row(over: Partial<McpCallRow> = {}): McpCallRow {
  return {
    mcpCallId: "11111111-1111-1111-1111-111111111111",
    tenantId: "tenant-uuid",
    callerPersonId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    toolName: "query_kpis",
    argsHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    clientUa: "claude-desktop/1.2.3",
    startedAt: "2026-04-27T10:00:00.000Z",
    outcome: "ok",
    latencyMs: 142,
    receipt: {
      hash: "0123456789ab",
      source: "mcp",
      owner: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      classification: "internal",
    },
    ...over,
  };
}

describe("RecentCallsTable", () => {
  it("renders the honest empty state when there are no calls", () => {
    render(<RecentCallsTable rows={[]} />);
    expect(screen.getByTestId("mcp-recent-calls-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/No MCP clients have called this server/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("mcp-recent-calls")).not.toBeInTheDocument();
  });

  it("renders one row per call when populated", () => {
    const rows = [
      row({ mcpCallId: "11111111-1111-1111-1111-111111111111", toolName: "query_kpis" }),
      row({
        mcpCallId: "22222222-2222-2222-2222-222222222222",
        toolName: "propose_data_product",
        outcome: "denied",
      }),
    ];
    render(<RecentCallsTable rows={rows} />);
    expect(screen.getAllByTestId("mcp-call-row")).toHaveLength(2);
    expect(screen.getByText("query_kpis")).toBeInTheDocument();
    expect(screen.getByText("propose_data_product")).toBeInTheDocument();
  });

  it("masks args_hash to a privacy-safe prefix + suffix", () => {
    render(<RecentCallsTable rows={[row()]} />);
    const cell = screen.getByTestId("mcp-call-args-hash");
    expect(cell.textContent).toBe("0123456789ab…cdef");
    expect(cell.textContent).not.toContain(
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    );
    expect(cell.getAttribute("title")).toContain(
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    );
  });

  it("masks the caller person id and shows mcp-anonymous on null", () => {
    const rows = [
      row({ mcpCallId: "1", callerPersonId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" }),
      row({ mcpCallId: "2", callerPersonId: null }),
    ];
    render(<RecentCallsTable rows={rows} />);
    const cells = screen.getAllByTestId("mcp-call-caller");
    expect(cells[0].textContent).toBe("aaaaaaaa…");
    expect(cells[1].textContent).toBe("mcp-anonymous");
  });

  it("renders an outcome chip and reflects the outcome literal", () => {
    const rows = [
      row({ mcpCallId: "1", outcome: "ok" }),
      row({ mcpCallId: "2", outcome: "denied" }),
      row({ mcpCallId: "3", outcome: "error" }),
    ];
    render(<RecentCallsTable rows={rows} />);
    expect(screen.getByTestId("mcp-call-outcome-ok")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-call-outcome-denied")).toBeInTheDocument();
    expect(screen.getByTestId("mcp-call-outcome-error")).toBeInTheDocument();
  });

  it("sorts by tool name when the Tool header is clicked", () => {
    const rows = [
      row({ mcpCallId: "1", toolName: "z_tool" }),
      row({ mcpCallId: "2", toolName: "a_tool" }),
    ];
    render(<RecentCallsTable rows={rows} />);
    fireEvent.click(screen.getByText("Tool"));
    const cells = screen.getAllByTestId("mcp-call-row");
    expect(cells[0].textContent).toContain("a_tool");
    expect(cells[1].textContent).toContain("z_tool");
  });
});
