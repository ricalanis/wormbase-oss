/**
 * AgentLoopStatusCard — per-loop row render contract (W2.A10).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { AgentLoopStatusCard } from "../AgentLoopStatusCard";

describe("AgentLoopStatusCard", () => {
  it("renders one row per loop carrying status + last-seen", () => {
    render(
      <AgentLoopStatusCard
        loops={[
          {
            id: "worm-core",
            label: "Worm core",
            status: "ok",
            lastSeenAt: new Date(Date.now() - 1_000).toISOString(),
            message: "HTTP API responding.",
          },
          {
            id: "channel-adapter",
            label: "Channel adapter",
            status: "degraded",
            lastSeenAt: new Date(Date.now() - 30 * 60_000).toISOString(),
            message: "No fresh wire events.",
          },
          {
            id: "projection-runner",
            label: "Projection runner",
            status: "down",
            lastSeenAt: null,
            message: null,
          },
        ]}
      />,
    );
    const wormCore = screen.getByTestId("ops-agent-loops-row-worm-core");
    expect(wormCore.getAttribute("data-status")).toBe("ok");
    expect(wormCore).toHaveTextContent(/HTTP API responding/i);

    const adapter = screen.getByTestId(
      "ops-agent-loops-row-channel-adapter",
    );
    expect(adapter.getAttribute("data-status")).toBe("degraded");
    expect(adapter).toHaveTextContent(/No fresh wire events/i);

    const runner = screen.getByTestId(
      "ops-agent-loops-row-projection-runner",
    );
    expect(runner.getAttribute("data-status")).toBe("down");
    expect(runner).toHaveTextContent(/never/);
  });

  it("renders the empty state when no loops are reported", () => {
    render(<AgentLoopStatusCard loops={[]} />);
    expect(screen.getByTestId("ops-agent-loops-empty")).toBeInTheDocument();
  });
});
