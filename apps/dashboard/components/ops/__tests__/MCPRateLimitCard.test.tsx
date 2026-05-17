/**
 * MCPRateLimitCard — disabled / populated / saturated render (W2.A10).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { MCPRateLimitCard } from "../MCPRateLimitCard";

describe("MCPRateLimitCard", () => {
  it("renders the disabled message when MCP is off", () => {
    render(
      <MCPRateLimitCard
        rateLimits={{
          enabled: false,
          disabledReason: "MCP server disabled.",
          tenants: [],
        }}
      />,
    );
    expect(
      screen.getByTestId("ops-mcp-rate-limit-disabled"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("ops-mcp-rate-limit-table"),
    ).not.toBeInTheDocument();
  });

  it("renders one row per tenant and flags saturation", () => {
    render(
      <MCPRateLimitCard
        rateLimits={{
          enabled: true,
          tenants: [
            {
              tenantSlug: "baseworm",
              tenantDisplayName: "Baseworm",
              companyId: "11111111-1111-1111-1111-111111111111",
              callsInWindow: 12,
              ceilingPerMin: 100,
              windowSeconds: 60,
              saturated: false,
            },
            {
              tenantSlug: "democorp",
              tenantDisplayName: "Democorp",
              companyId: "22222222-2222-2222-2222-222222222222",
              callsInWindow: 100,
              ceilingPerMin: 100,
              windowSeconds: 60,
              saturated: true,
            },
          ],
        }}
      />,
    );
    expect(
      screen.getByTestId("ops-mcp-rate-limit-row-baseworm"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ops-mcp-rate-limit-row-democorp"),
    ).toBeInTheDocument();
    expect(
      screen
        .getByTestId("ops-mcp-rate-limit-status-democorp")
        .getAttribute("data-saturated"),
    ).toBe("true");
    expect(
      screen
        .getByTestId("ops-mcp-rate-limit-status-baseworm")
        .getAttribute("data-saturated"),
    ).toBe("false");
  });
});
