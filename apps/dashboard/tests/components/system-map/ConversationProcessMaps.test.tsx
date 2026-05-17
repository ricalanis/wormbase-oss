/**
 * ConversationProcessMaps — empty state, list rendering, expand-on-click.
 *
 * P10 of 2026-04-29-demo-day-prd.md.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { ConversationProcessMaps } from "../../../components/system-map/ConversationProcessMaps";
import type { ProcessMapDataProductRow } from "../../../lib/ledger-client.types";

function pm(
  over: Partial<ProcessMapDataProductRow> = {},
): ProcessMapDataProductRow {
  return {
    dataProductId: "11111111-1111-1111-1111-111111111111",
    tenantId: "tenant-a",
    name: "Process map · trailing 14d · 1 edge(s)",
    status: "proposed",
    domainId: null,
    proposedAt: "2026-04-28T12:00:00Z",
    payload: {
      nodes: [
        { actorPersonId: "p-bob-0001", roleInMap: "asker" },
        { actorPersonId: "p-carol-0001", roleInMap: "askee" },
      ],
      edges: [
        {
          fromPersonId: "p-bob-0001",
          toPersonId: "p-carol-0001",
          topic: "churn_rate",
          frequency: 3,
          firstSeen: "2026-04-15T08:00:00Z",
          lastSeen: "2026-04-28T12:00:00Z",
        },
      ],
      windowStart: "2026-04-14T12:00:00Z",
      windowEnd: "2026-04-28T12:00:00Z",
      confidence: 1.0,
    },
    receipt: {
      hash: "abcdef012345",
      source: "ledger",
      owner: "p-worm",
      classification: "internal",
    },
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConversationProcessMaps", () => {
  it("renders the explicit empty state when there are no proposals", () => {
    render(<ConversationProcessMaps processMaps={[]} />);
    expect(
      screen.getByTestId("conversation-process-maps-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Conversation process maps/i)).toBeInTheDocument();
    // The empty-state copy describes the worm's threshold so the user
    // understands what would unlock the surface.
    expect(
      screen.getByText(/recurs three times within a 14-day window/i),
    ).toBeInTheDocument();
  });

  it("lists one row per process map proposal", () => {
    const data = [
      pm({
        dataProductId: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name: "Map A",
      }),
      pm({
        dataProductId: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        name: "Map B",
        status: "generated",
      }),
    ];
    render(<ConversationProcessMaps processMaps={data} />);
    expect(
      screen.getByTestId("process-map-row-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("process-map-row-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ).toBeInTheDocument();
    expect(screen.getByText("Map A")).toBeInTheDocument();
    expect(screen.getByText("Map B")).toBeInTheDocument();
  });

  it("shows status chips with the correct text", () => {
    const data = [
      pm({
        dataProductId: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        status: "proposed",
      }),
      pm({
        dataProductId: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        status: "generated",
      }),
    ];
    render(<ConversationProcessMaps processMaps={data} />);
    expect(
      screen.getByTestId(
        "process-map-status-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      ),
    ).toHaveTextContent("proposed");
    expect(
      screen.getByTestId(
        "process-map-status-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      ),
    ).toHaveTextContent("generated");
  });

  it("renders edge count and confidence in the row summary", () => {
    const data = [
      pm({
        payload: {
          ...pm().payload,
          confidence: 0.5,
          edges: [
            {
              fromPersonId: "p1",
              toPersonId: "p2",
              topic: "x",
              frequency: 3,
              firstSeen: "2026-04-15T08:00:00Z",
              lastSeen: "2026-04-28T12:00:00Z",
            },
            {
              fromPersonId: "p3",
              toPersonId: "p2",
              topic: "y",
              frequency: 2,
              firstSeen: "2026-04-15T08:00:00Z",
              lastSeen: "2026-04-28T12:00:00Z",
            },
          ],
        },
      }),
    ];
    render(<ConversationProcessMaps processMaps={data} />);
    expect(
      screen.getByText(/2 edges · 50% confidence/i),
    ).toBeInTheDocument();
  });

  it("expands the edge table on click and renders one row per edge", () => {
    const dpId = "11111111-1111-1111-1111-111111111111";
    render(<ConversationProcessMaps processMaps={[pm({ dataProductId: dpId })]} />);
    // Row exists but detail not yet rendered.
    expect(
      screen.queryByTestId(`process-map-detail-${dpId}`),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen
        .getByTestId(`process-map-row-${dpId}`)
        .querySelector("button")!,
    );
    expect(
      screen.getByTestId(`process-map-detail-${dpId}`),
    ).toBeInTheDocument();
    const edgeRows = screen.getAllByTestId("process-map-edge-row");
    expect(edgeRows).toHaveLength(1);
    expect(screen.getByText("churn_rate")).toBeInTheDocument();
    expect(screen.getByText(/3×/)).toBeInTheDocument();
  });

  it("links to the canonical /data-products/{id} page when expanded", () => {
    const dpId = "deadbeef-dead-beef-dead-beefdeadbeef";
    render(<ConversationProcessMaps processMaps={[pm({ dataProductId: dpId })]} />);
    fireEvent.click(
      screen
        .getByTestId(`process-map-row-${dpId}`)
        .querySelector("button")!,
    );
    const link = screen.getByTestId(`process-map-link-${dpId}`);
    expect(link).toHaveAttribute("href", `/data-products/${dpId}`);
  });

  it("renders a header summary count when there are proposals", () => {
    render(
      <ConversationProcessMaps
        processMaps={[
          pm({
            dataProductId: "11111111-1111-1111-1111-111111111111",
          }),
          pm({
            dataProductId: "22222222-2222-2222-2222-222222222222",
            status: "generated",
          }),
        ]}
      />,
    );
    expect(screen.getByText(/2 proposals/i)).toBeInTheDocument();
  });
});
