/**
 * CrossAxisChainTable tests — Lake-Side Overview (2026-05-16).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { getLakeChains } from "../../../lib/lake-overview";
import { CrossAxisChainTable } from "../CrossAxisChainTable";

describe("CrossAxisChainTable", () => {
  it("renders one row per chain (7 chains from getLakeChains)", () => {
    const chains = getLakeChains();
    render(<CrossAxisChainTable rows={chains} />);
    const table = screen.getByTestId("lake-overview-chain-table");
    expect(table).toBeInTheDocument();
    // 7 chains
    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(7);
  });

  it("renders bidirectional marker only on the L4 ↔ L2 row", () => {
    const chains = getLakeChains();
    render(<CrossAxisChainTable rows={chains} />);
    const l4l2 = screen.getByTestId("lake-overview-chain-row-L4-L2");
    expect(l4l2.getAttribute("data-bidirectional")).toBe("true");
    expect(
      screen.getByTestId("lake-overview-chain-bidirectional-L4-L2"),
    ).toBeInTheDocument();
    // forward-only chain (L5 → L7) does NOT carry the bidirectional flag
    const l5l7 = screen.getByTestId("lake-overview-chain-row-L5-L7");
    expect(l5l7.getAttribute("data-bidirectional")).toBe("false");
  });

  it("renders producer + consumer links pointing at /lake/* pages", () => {
    const chains = getLakeChains();
    render(<CrossAxisChainTable rows={chains} />);
    const producer = screen.getByTestId(
      "lake-overview-chain-producer-L5-L7",
    );
    const consumer = screen.getByTestId(
      "lake-overview-chain-consumer-L5-L7",
    );
    expect(producer.getAttribute("href")).toBe("/lake/semantic-types");
    expect(consumer.getAttribute("href")).toBe("/lake/quality");
  });

  it("renders each chain description prose", () => {
    const chains = getLakeChains();
    render(<CrossAxisChainTable rows={chains} />);
    // L4 → L3 chain description
    const l4l3 = screen.getByTestId("lake-overview-chain-row-L4-L3");
    expect(l4l3.textContent).toContain("Lineage-edge");
  });
});
