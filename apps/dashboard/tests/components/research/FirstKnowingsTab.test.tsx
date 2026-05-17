/**
 * FirstKnowingsTab — Demo-day P12 component test.
 *
 * Covers:
 *   - Renders header chrome + filter chips.
 *   - Honest empty state when no rows (CLAUDE.md ¶9).
 *   - Filter-no-match copy when filters narrow result to zero.
 *   - Rows render with kind label, summary, seq, and click-through to /trace.
 *   - Trace deep-link preserves the InfraEvent seq (W2.A10 pattern).
 *   - Filter chips: kind / scope / recency narrow the visible row set.
 *   - Chatter-context expand toggle reveals the ±3 chatter slice.
 */
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { FirstKnowingsTab } from "../../../components/research/FirstKnowingsTab";
import type {
  FirstKnowingPhenomenonKind,
  FirstKnowingRow,
  FirstKnowingScope,
} from "../../../lib/ledger-client.types";

function makeRow(overrides: Partial<FirstKnowingRow> = {}): FirstKnowingRow {
  return {
    kind: "kpi_gap",
    summary: "KPI gap detected: Q3 Revenue (confidence 0.84)",
    firstDetectedSeq: 102,
    firstDetectedTs: new Date().toISOString(),
    refId: "phenomenon_gap:kpi:q3_rev",
    referencedInSeq: 99,
    confidence: 0.84,
    noveltyKey: "kpi:q3_rev",
    proposedBy: "phenomenon_gap_detector",
    targetKind: "phenomenon_gap_detected",
    scope: "company",
    chatterContext: [
      {
        seq: 96,
        ts: new Date().toISOString(),
        channelId: "C1",
        senderPerson: "alice",
        text: "what's our Q3 rev?",
        isAnchor: false,
      },
      {
        seq: 99,
        ts: new Date().toISOString(),
        channelId: "C1",
        senderPerson: "bob",
        text: "we should track Q3 Rev",
        isAnchor: true,
      },
      {
        seq: 100,
        ts: new Date().toISOString(),
        channelId: "C1",
        senderPerson: "carol",
        text: "agreed, no dashboard",
        isAnchor: false,
      },
    ],
    receipt: {
      hash: "abc123def456",
      source: "phenomenon_gap_detector",
      owner: "phenomenon_gap_detector",
      classification: "internal",
    },
    ...overrides,
  };
}

describe("FirstKnowingsTab", () => {
  it("renders the header chrome and the Altman-Q1 framing", () => {
    render(<FirstKnowingsTab rows={[]} />);
    expect(screen.getByTestId("first-knowings-tab")).toBeTruthy();
    expect(
      screen.getByText(
        /What the worm has flagged that the org has not yet confirmed/i,
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Altman Q1/i)).toBeTruthy();
  });

  it("renders an honest empty state when no rows exist", () => {
    render(<FirstKnowingsTab rows={[]} />);
    const empty = screen.getByTestId("first-knowings-empty");
    expect(empty).toBeTruthy();
    expect(empty.textContent).toMatch(/no first-knowings yet/i);
  });

  it("renders the row list when at least one row is present", () => {
    render(<FirstKnowingsTab rows={[makeRow()]} />);
    expect(screen.getByTestId("first-knowings-list")).toBeTruthy();
    expect(screen.queryByTestId("first-knowings-empty")).toBeNull();
  });

  it("renders the kind label, summary, and seq for each row", () => {
    const row = makeRow({ firstDetectedSeq: 200 });
    render(<FirstKnowingsTab rows={[row]} />);
    expect(screen.getByTestId("first-knowing-kind-200")).toBeTruthy();
    expect(screen.getByTestId("first-knowing-kind-200").textContent).toMatch(
      /KPI gap/i,
    );
    expect(
      screen.getByTestId("first-knowing-summary-200").textContent,
    ).toMatch(/Q3 Revenue/);
  });

  it("trace deep-link encodes the InfraEvent seq + chat_received kind", () => {
    const row = makeRow({ firstDetectedSeq: 200, referencedInSeq: 137 });
    render(<FirstKnowingsTab rows={[row]} />);
    const link = screen.getByTestId(
      "first-knowing-trace-link-200",
    ) as HTMLAnchorElement;
    const href = link.getAttribute("href") ?? "";
    expect(href.startsWith("/trace?")).toBe(true);
    expect(href).toContain("seq=137");
    expect(href).toContain("kind=chat_received");
    expect(href).toContain("surface=research");
  });

  it("trace deep-link falls back to the propose seq when no chat triggered", () => {
    const row = makeRow({
      firstDetectedSeq: 50,
      referencedInSeq: 0,
      chatterContext: [],
      kind: "person_gap",
      targetKind: "person_proposed",
    });
    render(<FirstKnowingsTab rows={[row]} />);
    const link = screen.getByTestId(
      "first-knowing-trace-link-50",
    ) as HTMLAnchorElement;
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("seq=50");
    expect(href).toContain("kind=person_proposed");
  });

  it("filter chips narrow the visible rows by kind", () => {
    const kpi = makeRow({
      firstDetectedSeq: 1,
      kind: "kpi_gap",
      referencedInSeq: 0,
      chatterContext: [],
    });
    const person = makeRow({
      firstDetectedSeq: 2,
      kind: "person_gap",
      targetKind: "person_proposed",
      summary: "Person gap: 'Bob' on slack not yet confirmed",
      referencedInSeq: 0,
      chatterContext: [],
      scope: "mine",
    });
    render(<FirstKnowingsTab rows={[kpi, person]} />);

    // Both rows visible initially.
    expect(screen.getByTestId("first-knowing-row-1")).toBeTruthy();
    expect(screen.getByTestId("first-knowing-row-2")).toBeTruthy();

    // Pick "Person gap" chip → only row-2 shows.
    fireEvent.click(screen.getByTestId("chip-kind-person_gap"));
    expect(screen.queryByTestId("first-knowing-row-1")).toBeNull();
    expect(screen.getByTestId("first-knowing-row-2")).toBeTruthy();

    // Reset to all kinds.
    fireEvent.click(screen.getByTestId("chip-kind-all"));
    expect(screen.getByTestId("first-knowing-row-1")).toBeTruthy();
    expect(screen.getByTestId("first-knowing-row-2")).toBeTruthy();
  });

  it("filter chips narrow the visible rows by scope", () => {
    const company = makeRow({
      firstDetectedSeq: 1,
      scope: "company" as FirstKnowingScope,
      referencedInSeq: 0,
      chatterContext: [],
    });
    const mine = makeRow({
      firstDetectedSeq: 2,
      kind: "person_gap" as FirstKnowingPhenomenonKind,
      scope: "mine" as FirstKnowingScope,
      summary: "Person gap mine",
      referencedInSeq: 0,
      chatterContext: [],
    });
    render(<FirstKnowingsTab rows={[company, mine]} />);
    fireEvent.click(screen.getByTestId("chip-scope-mine"));
    expect(screen.queryByTestId("first-knowing-row-1")).toBeNull();
    expect(screen.getByTestId("first-knowing-row-2")).toBeTruthy();
  });

  it("renders an empty-with-filters message when filters narrow to zero", () => {
    const company = makeRow({
      firstDetectedSeq: 1,
      scope: "company",
      referencedInSeq: 0,
      chatterContext: [],
    });
    render(<FirstKnowingsTab rows={[company]} />);
    fireEvent.click(screen.getByTestId("chip-scope-mine"));
    const empty = screen.getByTestId("first-knowings-empty");
    expect(empty.textContent).toMatch(/match the active filters/i);
  });

  it("toggles the chatter context window on click-through", () => {
    const row = makeRow({ firstDetectedSeq: 999 });
    render(<FirstKnowingsTab rows={[row]} />);
    // Hidden initially.
    expect(screen.queryByTestId("first-knowing-chatter-999")).toBeNull();
    fireEvent.click(screen.getByTestId("first-knowing-toggle-chatter-999"));
    const chatter = screen.getByTestId("first-knowing-chatter-999");
    expect(chatter).toBeTruthy();
    // The anchor row is marked.
    const anchor = screen.getByTestId("chatter-row-99");
    expect(anchor.getAttribute("data-anchor")).toBe("true");
    // Above and below rows present.
    expect(screen.getByTestId("chatter-row-96")).toBeTruthy();
    expect(screen.getByTestId("chatter-row-100")).toBeTruthy();
    // Toggle hides again.
    fireEvent.click(screen.getByTestId("first-knowing-toggle-chatter-999"));
    expect(screen.queryByTestId("first-knowing-chatter-999")).toBeNull();
  });

  it("does not render a chatter toggle when context is empty", () => {
    const row = makeRow({
      firstDetectedSeq: 5,
      referencedInSeq: 0,
      chatterContext: [],
    });
    render(<FirstKnowingsTab rows={[row]} />);
    expect(
      screen.queryByTestId("first-knowing-toggle-chatter-5"),
    ).toBeNull();
  });
});
