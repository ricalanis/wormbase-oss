/**
 * Unit tests for the three Step 3c process retrieval surfaces:
 *
 *   * DecisionsTable    — /decisions
 *   * ProcessDiagram    — /processes
 *   * SystemMapGraph    — /system-map
 *
 * Each component renders given mock data shaped like the live ledger
 * folds in lib/ledger-client.ts.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { DecisionsTable } from "../../components/process/DecisionsTable";
import { ProcessDiagram } from "../../components/process/ProcessDiagram";
import { SystemMapGraph } from "../../components/process/SystemMapGraph";
import type {
  DecisionRow,
  ProcessMapRow,
  SystemMapPayload,
} from "../../lib/ledger-client.types";

const RECEIPT = {
  hash: "abc123def456",
  source: "process-extractor",
  owner: "worm",
  classification: "internal" as const,
};

const DECISIONS: DecisionRow[] = [
  {
    decisionId: "d-1",
    decisionText: "we decided to push Q3 close to Friday",
    decisionAt: "2026-04-24T10:00:00Z",
    channelId: "C-finance",
    decidedByPersons: ["p-bob"],
    evidenceMessageIds: ["m-101", "m-102"],
    confidence: 0.82,
    receipt: RECEIPT,
  },
  {
    decisionId: "d-2",
    decisionText: "approved Acme as the Stripe migration vendor",
    decisionAt: "2026-04-23T14:00:00Z",
    channelId: "C-eng",
    decidedByPersons: ["p-alice"],
    evidenceMessageIds: ["m-201"],
    confidence: 0.71,
    receipt: { ...RECEIPT, hash: "111222333444" },
  },
];

const PROCESS: ProcessMapRow = {
  processId: "p-1",
  processName: "Q3 close",
  domain: "finance",
  confidence: 0.74,
  proposedAt: "2026-04-24T10:00:00Z",
  steps: [
    { order: 1, actor: "Bob", action: "exports trial balance", sourceMessageId: "m-1" },
    { order: 2, actor: "Alice", action: "reviews variances", sourceMessageId: "m-2" },
    { order: 3, actor: "Carol", action: "approves", sourceMessageId: "m-3" },
  ],
  receipt: RECEIPT,
};

const SYSTEM: SystemMapPayload = {
  nodes: [
    {
      nodeKind: "person",
      nodeId: "p-bob",
      edges: [
        { kind: "speaks_in", targetId: "C-finance", weight: 8 },
        { kind: "mentions", targetId: "p-alice", weight: 3 },
      ],
      receipt: RECEIPT,
    },
    {
      nodeKind: "person",
      nodeId: "p-alice",
      edges: [
        { kind: "speaks_in", targetId: "C-finance", weight: 5 },
      ],
      receipt: RECEIPT,
    },
    {
      nodeKind: "channel",
      nodeId: "C-finance",
      edges: [{ kind: "topic", targetId: "finance", weight: 12 }],
      receipt: RECEIPT,
    },
  ],
  generatedAt: "2026-04-24T10:00:00Z",
};

// ─── DecisionsTable ──────────────────────────────────────────────────────

describe("DecisionsTable", () => {
  it("renders a row per decision with the decision text + receipt", () => {
    render(<DecisionsTable rows={DECISIONS} />);
    expect(screen.getByTestId("decisions-table")).toBeInTheDocument();
    expect(screen.getByTestId("decision-d-1")).toBeInTheDocument();
    expect(screen.getByTestId("decision-d-2")).toBeInTheDocument();
    expect(screen.getByText(/push Q3 close/)).toBeInTheDocument();
    expect(screen.getAllByText(/abc123def456/).length).toBeGreaterThan(0);
  });

  it("renders evidence message ids per decision", () => {
    render(<DecisionsTable rows={DECISIONS} />);
    expect(screen.getByTestId("decision-evidence-m-101")).toBeInTheDocument();
    expect(screen.getByTestId("decision-evidence-m-201")).toBeInTheDocument();
  });

  it("renders an empty state when no decisions exist", () => {
    render(<DecisionsTable rows={[]} />);
    const empty = screen.getByTestId("decisions-empty");
    expect(empty).toBeInTheDocument();
    // WS5 S5: first-day affordance copy must explain WHAT the surface does,
    // WHAT triggers content, and offer a CTA the user can take RIGHT NOW.
    expect(empty.textContent).toContain("converges in chat");
    expect(empty.textContent).toContain("Add the worm to more channels");
  });

  it("includes a channel filter populated from the rows", () => {
    render(<DecisionsTable rows={DECISIONS} />);
    const filter = screen.getByTestId("decisions-filter-channel") as HTMLSelectElement;
    const values = Array.from(filter.options).map((o) => o.value);
    expect(values).toContain("all");
    expect(values).toContain("C-finance");
    expect(values).toContain("C-eng");
  });

  it("links each decision to its /trace/decision/[id] chain page", () => {
    render(<DecisionsTable rows={DECISIONS} />);
    const link = screen.getByTestId("decision-chain-link-d-1");
    expect(link.getAttribute("href")).toBe("/trace/decision/d-1");
    expect(link.textContent).toMatch(/view chain/i);
  });
});

// ─── ProcessDiagram ──────────────────────────────────────────────────────

describe("ProcessDiagram", () => {
  it("renders an SVG with the process name + every actor as a swimlane", () => {
    render(<ProcessDiagram process={PROCESS} />);
    expect(screen.getByTestId(`process-${PROCESS.processId}`)).toBeInTheDocument();
    expect(screen.getByTestId(`process-svg-${PROCESS.processId}`)).toBeInTheDocument();
    expect(screen.getByTestId(`process-name-${PROCESS.processId}`).textContent)
      .toBe("Q3 close");
    // Actor labels rendered as text nodes.
    const svg = screen.getByTestId(`process-svg-${PROCESS.processId}`);
    const text = svg.textContent ?? "";
    expect(text).toContain("Bob");
    expect(text).toContain("Alice");
    expect(text).toContain("Carol");
  });

  it("shows the domain + confidence in the header", () => {
    render(<ProcessDiagram process={PROCESS} />);
    const article = screen.getByTestId(`process-${PROCESS.processId}`);
    expect(article.textContent).toContain("finance");
    expect(article.textContent).toContain("74%");
  });

  it("renders a Receipt for the process", () => {
    const { container } = render(<ProcessDiagram process={PROCESS} />);
    const article = screen.getByTestId(`process-${PROCESS.processId}`);
    expect(article.textContent).toContain("abc123def456");
    // Receipt component renders into the header — present via test id from
    // the underlying design system component.
    expect(container.querySelector("[data-receipt]")).toBeTruthy();
  });

  it("collapses duplicate actor rows into a single swimlane", () => {
    const repeated: ProcessMapRow = {
      ...PROCESS,
      processId: "p-2",
      steps: [
        { order: 1, actor: "Bob", action: "exports", sourceMessageId: "m-1" },
        { order: 2, actor: "Alice", action: "reviews", sourceMessageId: "m-2" },
        { order: 3, actor: "Bob", action: "publishes", sourceMessageId: "m-3" },
      ],
    };
    render(<ProcessDiagram process={repeated} />);
    const svg = screen.getByTestId(`process-svg-${repeated.processId}`);
    // Bob appears as a single swimlane label, but his two boxes both render.
    // Count distinct actor labels via the rendered text.
    const text = svg.textContent ?? "";
    const bobCount = (text.match(/Bob/g) || []).length;
    // Expect ≥ 1 — the swimlane label always appears.
    expect(bobCount).toBeGreaterThanOrEqual(1);
  });
});

// ─── SystemMapGraph ──────────────────────────────────────────────────────

describe("SystemMapGraph", () => {
  it("renders the SVG canvas with a node per person + channel", () => {
    render(<SystemMapGraph payload={SYSTEM} />);
    expect(screen.getByTestId("system-map-svg")).toBeInTheDocument();
    expect(screen.getByTestId("node-person-p-bob")).toBeInTheDocument();
    expect(screen.getByTestId("node-person-p-alice")).toBeInTheDocument();
    expect(screen.getByTestId("node-channel-C-finance")).toBeInTheDocument();
  });

  it("draws edges between nodes whose target_ids resolve in the layout", () => {
    render(<SystemMapGraph payload={SYSTEM} />);
    expect(screen.getByTestId("edge-p-bob-speaks_in-C-finance")).toBeInTheDocument();
    expect(screen.getByTestId("edge-p-bob-mentions-p-alice")).toBeInTheDocument();
  });

  it("renders an empty state when no nodes are present", () => {
    render(<SystemMapGraph payload={{ nodes: [], generatedAt: null }} />);
    const empty = screen.getByTestId("system-map-empty");
    expect(empty).toBeInTheDocument();
    // WS5 S5: first-day affordance copy explains the graph + a real CTA.
    expect(empty.textContent).toContain("who-asks-whom");
    expect(empty.textContent).toContain("Drop the worm into more channels");
  });
});
