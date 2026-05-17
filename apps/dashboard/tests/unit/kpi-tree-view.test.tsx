/**
 * KpiTreeView — renders a small graph and opens the side panel on node
 * click. We bypass the React Flow renderer's internal layout (which needs
 * a real DOM measurement) by stubbing it with a passthrough that exposes
 * the nodes directly. That keeps the test deterministic in happy-dom while
 * still exercising the layout + click handlers we own.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";

// Stub @xyflow/react before the component imports it. Using the module
// factory form so the mock is hoisted.
vi.mock("@xyflow/react", () => {
  type StubNode = {
    id: string;
    data: { row: { id: string; label: string }; depth: number };
    type?: string;
  };
  return {
    __esModule: true,
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    Position: { Left: "left", Right: "right" },
    ReactFlow: ({
      nodes,
      nodeTypes,
      onNodeClick,
    }: {
      nodes: StubNode[];
      nodeTypes: Record<string, (props: { data: unknown }) => ReactNode>;
      onNodeClick?: (e: unknown, n: StubNode) => void;
    }) => {
      const NodeRenderer = nodeTypes.kpi;
      return (
        <div data-testid="rf-stub">
          {nodes.map((n) => (
            <button
              key={n.id}
              data-testid={`rf-stub-node-${n.id}`}
              onClick={() => onNodeClick?.({}, n)}
              style={{ display: "block" }}
              type="button"
            >
              <NodeRenderer data={n.data} />
            </button>
          ))}
        </div>
      );
    },
  };
});

import { KpiTreeView } from "../../components/kpi/KpiTreeView";
import type { KpiNodeRow } from "../../lib/ledger-client.types";

function leaf(id: string, label: string, conf = 0.7): KpiNodeRow {
  return {
    id,
    label,
    owner: "ricardo-bot",
    classification: "internal",
    confidence: conf,
    hasChildren: false,
    children: [],
    receipt: {
      hash: `${id}_hash000`,
      source: `src://${id}`,
      owner: "ricardo-bot",
      classification: "internal",
    },
  };
}

const tree: KpiNodeRow = {
  id: "root",
  label: "Net revenue retention",
  owner: "ricardo-bot",
  classification: "internal",
  confidence: 0.92,
  hasChildren: true,
  receipt: {
    hash: "rooth4sh1234",
    source: "subs",
    owner: "ricardo-bot",
    classification: "internal",
  },
  children: [leaf("a", "Active subs", 0.86), leaf("b", "Churn", 0.34)],
};

beforeEach(() => {
  // Stub fetch so usePoll's refresh tick doesn't blow up under happy-dom.
  // We resolve with the same tree so polling is a no-op behaviorally.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ root: tree }),
    })) as unknown as typeof fetch,
  );
});

describe("KpiTreeView", () => {
  it("renders a node per tree entry with a confidence tier", () => {
    render(<KpiTreeView initial={tree} />);
    const root = screen.getByTestId("kpi-flow-node-root");
    expect(root.getAttribute("data-conf")).toBe("high");
    const child = screen.getByTestId("kpi-flow-node-b");
    expect(child.getAttribute("data-conf")).toBe("low");
  });

  it("opens the side panel with the clicked node's details", () => {
    render(<KpiTreeView initial={tree} />);
    // Click the root node (the rf-stub-node button is the click handler)
    const stubNode = screen.getByTestId("rf-stub-node-root");
    fireEvent.click(stubNode);
    const panel = screen.getByTestId("kpi-side-panel");
    expect(panel.getAttribute("data-selected-id")).toBe("root");
    expect(panel.textContent).toContain("Net revenue retention");
  });

  it("renders the live polling badge", () => {
    render(<KpiTreeView initial={tree} />);
    const live = screen.getByTestId("kpi-tree-liveness");
    expect(live.textContent?.toLowerCase()).toContain("live");
  });
});
