/**
 * LedgerThroughputCard — sparkline + total render contract (W2.A10).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { LedgerThroughputCard } from "../LedgerThroughputCard";

describe("LedgerThroughputCard", () => {
  it("renders the empty state when no buckets are reported", () => {
    render(
      <LedgerThroughputCard
        throughput={{
          totalLastWindow: 0,
          windowMinutes: 10,
          buckets: [],
        }}
      />,
    );
    expect(
      screen.getByTestId("ops-ledger-throughput-empty"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("ops-ledger-throughput-spark"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("ops-ledger-throughput-total")).toHaveTextContent(
      "0",
    );
  });

  it("renders one bar per bucket with the supplied counts", () => {
    const buckets = [
      { bucketStart: "2026-04-28T08:00:00Z", count: 5 },
      { bucketStart: "2026-04-28T08:01:00Z", count: 12 },
      { bucketStart: "2026-04-28T08:02:00Z", count: 0 },
      { bucketStart: "2026-04-28T08:03:00Z", count: 7 },
    ];
    render(
      <LedgerThroughputCard
        throughput={{
          totalLastWindow: 24,
          windowMinutes: 4,
          buckets,
        }}
      />,
    );
    expect(screen.getByTestId("ops-ledger-throughput-total")).toHaveTextContent(
      "24",
    );
    for (let i = 0; i < buckets.length; i += 1) {
      const bar = screen.getByTestId(`ops-ledger-throughput-bar-${i}`);
      expect(bar.getAttribute("data-count")).toBe(String(buckets[i].count));
    }
    expect(screen.getByText(/peak 12 \/ min/i)).toBeInTheDocument();
  });
});
