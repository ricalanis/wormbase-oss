import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TraceRow } from "../../components/trace/TraceRow";
import type { TraceEntryRow } from "../../lib/ledger-client.types";

const e: TraceEntryRow = {
  id: "e_0001",
  ts: "2026-04-30T08:14:02Z",
  kind: "source_proposed",
  quadrant: "propose",
  hash: "a3f9c2deadbe",
  prevHash: null,
  payload: { summary: "Proposed source: subscriptions.csv" },
  receipt: {
    hash: "a3f9c2deadbe",
    source: "subscriptions.csv",
    owner: "carla-bot",
    classification: "internal",
  },
};

describe("TraceRow", () => {
  it("renders the timestamp, kind, hash, and Receipt", () => {
    render(<TraceRow entry={e} />);
    expect(screen.getByText(e.ts)).toBeInTheDocument();
    expect(screen.getByText(/source_proposed/i)).toBeInTheDocument();
    expect(screen.getByText("#a3f9c2de")).toBeInTheDocument();
    expect(screen.getByText(/Proposed source: subscriptions.csv/)).toBeInTheDocument();
  });

  it("emits data-quadrant attribute", () => {
    const { container } = render(<TraceRow entry={e} />);
    const row = container.querySelector(`[data-testid='trace-row-${e.id}']`);
    expect(row?.getAttribute("data-quadrant")).toBe("propose");
  });

  it("toggles detail with [+]/[−] glyph", () => {
    render(<TraceRow entry={e} />);
    expect(screen.queryByTestId(`trace-detail-${e.id}`)).toBeNull();
    fireEvent.click(screen.getByTestId(`trace-toggle-${e.id}`));
    expect(screen.getByTestId(`trace-detail-${e.id}`)).toBeInTheDocument();
  });
});
