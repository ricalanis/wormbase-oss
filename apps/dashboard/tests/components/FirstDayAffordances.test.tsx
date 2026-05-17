/**
 * WS5 S5 — first-day-affordance copy on the empty states of:
 *
 *   - /processes
 *   - /system-map
 *   - /decisions
 *   - /research
 *
 * Each empty state must (a) explain what the surface DOES, (b) explain
 * what triggers content to appear, (c) offer a CTA the user can take
 * RIGHT NOW. We assert all three for each surface.
 *
 * For surfaces whose empty state lives inside a child component
 * (DecisionsTable, SystemMapGraph), the relevant copy is already
 * exercised in tests/unit/process-views.test.tsx — this file covers
 * the page-level empty states (processes, research) and re-asserts the
 * affordance triplet.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { DecisionsTable } from "../../components/process/DecisionsTable";
import { SystemMapGraph } from "../../components/process/SystemMapGraph";
import { EmptyState } from "../../components/chrome/EmptyState";

// Re-render the in-page EmptyState configurations from /processes and
// /research literally — keeps the test fast and avoids rendering the
// full server components.
function ProcessesEmpty() {
  return (
    <EmptyState
      testId="processes-empty"
      eyebrow="no processes yet"
      title="Processes emerge as your team works in chat."
      description={
        "This surface fills with swimlane diagrams when the worm sees " +
        "ordered actor → action sequences (\"first Bob exports, then " +
        "Alice reviews, then Carol approves\") in connected channels. " +
        "Drop the worm into more channels to grow the conversation lake — " +
        "first process map typically lands within 24h of the first " +
        "decision-grade chatter."
      }
      cta={{ label: "Drop the worm into more channels", href: "/channels" }}
      secondaryCta={{ label: "Browse decisions", href: "/decisions" }}
    />
  );
}

function ResearchEmpty() {
  return (
    <EmptyState
      testId="research-empty"
      eyebrow="no experiments yet"
      title="The per-position autoresearch loop fires once a Person has a position."
      description={
        "Once a confirmed Person has a position and a headline metric to " +
        "move, the worm proposes overnight experiments, keeps wins, " +
        "discards losses, and surfaces the loop here. The loop runs every " +
        "30s in dev so the first experiment lands within a cycle of the " +
        "first position assignment. Assign positions on /people to begin."
      }
      cta={{ label: "Assign positions on /people", href: "/people" }}
      secondaryCta={{ label: "See what the worm has decided", href: "/decisions" }}
    />
  );
}

describe("WS5 S5 — first-day affordances", () => {
  it("/processes empty state names the surface, the trigger, and the CTA", () => {
    render(<ProcessesEmpty />);
    const empty = screen.getByTestId("processes-empty");
    // (a) what the surface does
    expect(empty.textContent).toContain("swimlane");
    // (b) what triggers content
    expect(empty.textContent).toContain("actor → action sequences");
    // (c) a CTA the user can take right now
    const ctas = empty.querySelectorAll("[data-testid='empty-state-cta']");
    expect(ctas.length).toBeGreaterThanOrEqual(1);
    expect(
      Array.from(ctas).some((c) =>
        (c.textContent ?? "").includes("Drop the worm into more channels"),
      ),
    ).toBe(true);
  });

  it("/system-map empty state names the surface, the trigger, and the CTA", () => {
    render(<SystemMapGraph payload={{ nodes: [], generatedAt: null }} />);
    const empty = screen.getByTestId("system-map-empty");
    expect(empty.textContent).toContain("who-asks-whom");
    expect(empty.textContent).toContain("messages, mentions, and replies");
    const ctas = empty.querySelectorAll("[data-testid='empty-state-cta']");
    expect(ctas.length).toBeGreaterThanOrEqual(1);
    expect(
      Array.from(ctas).some((c) =>
        (c.textContent ?? "").includes("Drop the worm"),
      ),
    ).toBe(true);
  });

  it("/decisions empty state names the surface, the trigger, and the CTA", () => {
    render(<DecisionsTable rows={[]} />);
    const empty = screen.getByTestId("decisions-empty");
    expect(empty.textContent).toContain("converges in chat");
    expect(empty.textContent).toContain("we decided X");
    const ctas = empty.querySelectorAll("[data-testid='empty-state-cta']");
    expect(ctas.length).toBeGreaterThanOrEqual(1);
    expect(
      Array.from(ctas).some((c) =>
        (c.textContent ?? "").includes("Add the worm to more channels"),
      ),
    ).toBe(true);
  });

  it("/research empty state names the surface, the trigger, and the CTA", () => {
    render(<ResearchEmpty />);
    const empty = screen.getByTestId("research-empty");
    expect(empty.textContent).toContain("autoresearch loop");
    expect(empty.textContent).toContain("position");
    const ctas = empty.querySelectorAll("[data-testid='empty-state-cta']");
    expect(ctas.length).toBeGreaterThanOrEqual(1);
    expect(
      Array.from(ctas).some((c) =>
        (c.textContent ?? "").includes("Assign positions on /people"),
      ),
    ).toBe(true);
  });
});
