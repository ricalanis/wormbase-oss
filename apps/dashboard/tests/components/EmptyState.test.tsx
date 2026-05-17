/**
 * EmptyState — chrome primitive used to surface honest empty surfaces
 * across the dashboard. Verifies the public contract: title, description,
 * eyebrow, and CTAs render, internal `href` becomes a Link, prose-only
 * CTAs render as a span (not a clickable element).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { EmptyState } from "../../components/chrome/EmptyState";

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(
      <EmptyState
        title="The worm hasn't proposed any KPIs yet."
        description="Connect a data source to begin."
      />,
    );
    expect(
      screen.getByText("The worm hasn't proposed any KPIs yet."),
    ).toBeTruthy();
    expect(screen.getByText("Connect a data source to begin.")).toBeTruthy();
  });

  it("renders eyebrow when provided", () => {
    render(
      <EmptyState
        eyebrow="no kpis yet"
        title="No KPIs"
        description="..."
      />,
    );
    expect(screen.getByText("no kpis yet")).toBeTruthy();
  });

  it("renders a primary CTA with href as a Next Link", () => {
    const { container } = render(
      <EmptyState
        title="No sources"
        description="..."
        cta={{ label: "Add source", href: "/sources/new" }}
      />,
    );
    const cta = container.querySelector(
      "[data-testid='empty-state-cta']",
    ) as HTMLAnchorElement;
    expect(cta).toBeTruthy();
    expect(cta.tagName.toLowerCase()).toBe("a");
    expect(cta.getAttribute("href")).toBe("/sources/new");
    expect(cta.textContent).toBe("Add source");
  });

  it("renders prose-only CTAs as a non-link span", () => {
    const { container } = render(
      <EmptyState
        title="No sources"
        description="..."
        cta={{ label: "Drop a file in your worm channel" }}
      />,
    );
    const cta = container.querySelector(
      "[data-testid='empty-state-cta']",
    ) as HTMLElement;
    expect(cta).toBeTruthy();
    expect(cta.tagName.toLowerCase()).toBe("span");
    expect(cta.textContent).toBe("Drop a file in your worm channel");
  });

  it("renders both primary and secondary CTAs", () => {
    const { container } = render(
      <EmptyState
        title="No sources"
        description="..."
        cta={{ label: "Add source", href: "/sources/new" }}
        secondaryCta={{ label: "Connect chat", href: "/channels" }}
      />,
    );
    const ctas = container.querySelectorAll("[data-testid='empty-state-cta']");
    expect(ctas.length).toBe(2);
    expect(ctas[0].textContent).toBe("Add source");
    expect(ctas[1].textContent).toBe("Connect chat");
  });

  it("uses the default empty-state testId when none provided", () => {
    render(<EmptyState title="No data" description="..." />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
  });

  it("respects a custom testId", () => {
    render(
      <EmptyState
        testId="kpis-empty"
        title="No KPIs"
        description="..."
      />,
    );
    expect(screen.getByTestId("kpis-empty")).toBeTruthy();
  });
});
