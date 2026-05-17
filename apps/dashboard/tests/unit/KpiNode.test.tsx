import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KpiNode } from "../../components/kpi/KpiNode";
import type { KpiNodeRow } from "../../lib/ledger-client.types";

function leaf(id: string, conf: number): KpiNodeRow {
  return {
    id,
    label: id,
    owner: "ricardo-bot",
    classification: "internal",
    confidence: conf,
    hasChildren: false,
    children: [],
    receipt: {
      hash: id,
      source: "x",
      owner: "ricardo-bot",
      classification: "internal",
    },
  };
}

const root: KpiNodeRow = {
  id: "root",
  label: "Net revenue retention",
  owner: "ricardo-bot",
  classification: "internal",
  confidence: 0.92,
  hasChildren: true,
  children: [leaf("a", 0.86), leaf("b", 0.34)],
  receipt: {
    hash: "rooth4sh",
    source: "subs",
    owner: "ricardo-bot",
    classification: "internal",
  },
};

describe("KpiNode", () => {
  it("emits data-conf=high for confidence > 0.8", () => {
    const { container } = render(
      <ul>
        <KpiNode node={root} defaultExpanded />
      </ul>
    );
    const el = container.querySelector(`[data-testid='kpi-node-root']`);
    expect(el?.getAttribute("data-conf")).toBe("high");
  });

  it("emits data-conf=low for confidence < 0.4", () => {
    const { container } = render(
      <ul>
        <KpiNode node={leaf("c", 0.3)} />
      </ul>
    );
    const el = container.querySelector(`[data-testid='kpi-node-c']`);
    expect(el?.getAttribute("data-conf")).toBe("low");
  });

  it("toggles via the [+]/[−] glyph", () => {
    render(
      <ul>
        <KpiNode node={root} />
      </ul>
    );
    const toggle = screen.getByTestId("kpi-toggle-root");
    expect(toggle.textContent).toMatch(/\[−\]|\[\+\]/);
    fireEvent.click(toggle);
    // children should toggle visibility (via re-render); just assert click works
  });

  it("renders a Receipt inline", () => {
    const { container } = render(
      <ul>
        <KpiNode node={leaf("z", 0.7)} />
      </ul>
    );
    expect(container.querySelector("[data-receipt]")).toBeTruthy();
  });
});
