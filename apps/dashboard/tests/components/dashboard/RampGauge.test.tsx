/**
 * RampGauge — knowledge-ramp counter tile (Demo-day P2).
 *
 * Verifies the public contract documented in
 * ``docs/superpowers/specs/2026-04-29-demo-day-prd.md`` §7 P2:
 *
 *   * Renders a count + sparkline + hint per axis.
 *   * The whole tile is a deep-link to ``/trace?kind=<filter>``.
 *   * Empty state (count === 0) renders ``0`` honestly + emptyHint.
 *   * Populated state renders count + populatedHint + a sparkline that
 *     reflects the per-bucket data.
 *   * The ``last_seq`` is threaded onto the trace deep-link so a future
 *     trace UX can scroll the contributing row into view.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { RampGauge } from "../../../components/dashboard/RampGauge";

const FULL_SPARK = (() => {
  const a = new Array<number>(60).fill(0);
  // Plant a few entries in the most recent buckets so the bars render.
  a[58] = 1;
  a[59] = 2;
  return a;
})();

const EMPTY_SPARK = new Array<number>(60).fill(0);

describe("RampGauge (P2 · knowledge-ramp counters)", () => {
  it("renders the count, label, and populated hint when count > 0", () => {
    render(
      <RampGauge
        axis="ontology"
        label="Ontology"
        count={42}
        sparkline={FULL_SPARK}
        emptyHint="no concepts confirmed yet"
        populatedHint="concepts confirmed against the seed ontology"
        traceFilter="concept_"
        lastSeq={1234}
        lastTs={new Date(Date.now() - 2 * 60 * 1000).toISOString()}
      />,
    );
    expect(screen.getByTestId("ramp-gauge-ontology")).toBeTruthy();
    expect(screen.getByTestId("ramp-gauge-ontology-count").textContent).toBe(
      "42",
    );
    expect(screen.getByText("Ontology")).toBeTruthy();
    expect(
      screen.getByText("concepts confirmed against the seed ontology"),
    ).toBeTruthy();
  });

  it("renders 0 honestly with the empty hint when count === 0", () => {
    render(
      <RampGauge
        axis="conversational"
        label="Conversational"
        count={0}
        sparkline={EMPTY_SPARK}
        emptyHint="no chat captured yet · invite the worm into a channel"
        populatedHint="messages captured from connected channels"
        traceFilter="chat_received"
        lastSeq={0}
        lastTs={null}
      />,
    );
    const tile = screen.getByTestId("ramp-gauge-conversational");
    expect(tile.getAttribute("data-empty")).toBe("true");
    expect(
      screen.getByTestId("ramp-gauge-conversational-count").textContent,
    ).toBe("0");
    expect(
      screen.getByText("no chat captured yet · invite the worm into a channel"),
    ).toBeTruthy();
  });

  it("the whole tile is a deep-link to /trace?kind=<filter>", () => {
    render(
      <RampGauge
        axis="relational"
        label="Relational"
        count={7}
        sparkline={EMPTY_SPARK}
        emptyHint="no KPI tree growth yet"
        populatedHint="KPI nodes + edges threaded into the tree"
        traceFilter="kpi_"
        lastSeq={88}
        lastTs={new Date().toISOString()}
      />,
    );
    const tile = screen.getByTestId("ramp-gauge-relational");
    // The tile itself is the link (next/link renders an <a>).
    expect(tile.tagName.toLowerCase()).toBe("a");
    const href = tile.getAttribute("href") ?? "";
    expect(href.startsWith("/trace?")).toBe(true);
    expect(href).toContain("kind=kpi_");
    expect(href).toContain("last_seq=88");
  });

  it("threads last_seq into the deep-link only when > 0", () => {
    render(
      <RampGauge
        axis="ontology"
        label="Ontology"
        count={0}
        sparkline={EMPTY_SPARK}
        emptyHint="empty"
        populatedHint="populated"
        traceFilter="concept_"
        lastSeq={0}
        lastTs={null}
      />,
    );
    const tile = screen.getByTestId("ramp-gauge-ontology");
    const href = tile.getAttribute("href") ?? "";
    expect(href).toContain("kind=concept_");
    expect(href).not.toContain("last_seq=");
  });

  it("renders a sparkline with the canonical 60-bucket geometry", () => {
    const { container } = render(
      <RampGauge
        axis="ontology"
        label="Ontology"
        count={3}
        sparkline={FULL_SPARK}
        emptyHint="empty"
        populatedHint="populated"
        traceFilter="concept_"
        lastSeq={5}
        lastTs={new Date().toISOString()}
      />,
    );
    const sparkline = screen.getByTestId("ramp-gauge-sparkline");
    expect(sparkline.tagName.toLowerCase()).toBe("svg");
    expect(sparkline.getAttribute("data-bucket-count")).toBe("60");
    // Two buckets had data; rect count must equal that.
    const rects = container.querySelectorAll("svg rect");
    expect(rects.length).toBe(2);
  });

  it("renders an empty-state sparkline as a flat baseline (no bars)", () => {
    const { container } = render(
      <RampGauge
        axis="conversational"
        label="Conversational"
        count={0}
        sparkline={EMPTY_SPARK}
        emptyHint="empty"
        populatedHint="populated"
        traceFilter="chat_received"
        lastSeq={0}
        lastTs={null}
      />,
    );
    const rects = container.querySelectorAll("svg rect");
    expect(rects.length).toBe(0);
    // The baseline rule must still render so the sparkline isn't invisible.
    const lines = container.querySelectorAll("svg line");
    expect(lines.length).toBe(1);
  });

  it("publishes data-attributes the dashboard E2E suite asserts on", () => {
    render(
      <RampGauge
        axis="conversational"
        label="Conversational"
        count={5}
        sparkline={FULL_SPARK}
        emptyHint="empty"
        populatedHint="populated"
        traceFilter="chat_received"
        lastSeq={2}
        lastTs={new Date().toISOString()}
      />,
    );
    const tile = screen.getByTestId("ramp-gauge-conversational");
    expect(tile.getAttribute("data-axis")).toBe("conversational");
    expect(tile.getAttribute("data-count")).toBe("5");
    expect(tile.getAttribute("data-empty")).toBe("false");
    expect(tile.getAttribute("data-trace-filter")).toBe("chat_received");
  });

  it("aria-label exposes the count and trace-filter for screen readers", () => {
    render(
      <RampGauge
        axis="ontology"
        label="Ontology"
        count={9}
        sparkline={FULL_SPARK}
        emptyHint="empty"
        populatedHint="populated"
        traceFilter="concept_"
        lastSeq={1}
        lastTs={new Date().toISOString()}
      />,
    );
    const tile = screen.getByTestId("ramp-gauge-ontology");
    const aria = tile.getAttribute("aria-label") ?? "";
    expect(aria).toContain("Ontology");
    expect(aria).toContain("9");
    expect(aria).toContain("concept_");
  });
});
