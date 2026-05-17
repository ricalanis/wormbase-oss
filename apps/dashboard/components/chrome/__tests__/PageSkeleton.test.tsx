/**
 * PageSkeleton — renders an editorial loading surface (W3.A14).
 *
 * The skeleton is a recognizable paged-skeleton, not a generic spinner.
 * Tests cover: default render, custom card count, custom title, ARIA
 * attributes (aria-busy / aria-live).
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import { PageSkeleton } from "../PageSkeleton";

afterEach(() => {
  // Vitest's `globals: true` does not register @testing-library/react's
  // auto-cleanup hook the way Jest does; explicit cleanup keeps state
  // from leaking across tests in this file.
  cleanup();
});

describe("PageSkeleton", () => {
  it("renders the default eyebrow + title + 3 cards", () => {
    render(<PageSkeleton />);
    expect(screen.getByTestId("page-skeleton")).toBeInTheDocument();
    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(screen.getByText("Reading the ledger…")).toBeInTheDocument();
    expect(screen.getByText("the worm is reading the ledger")).toBeInTheDocument();
    expect(screen.getByTestId("page-skeleton-card-0")).toBeInTheDocument();
    expect(screen.getByTestId("page-skeleton-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("page-skeleton-card-2")).toBeInTheDocument();
  });

  it("respects a custom card count", () => {
    render(<PageSkeleton cards={1} testId="custom-skeleton" />);
    expect(screen.getByTestId("custom-skeleton")).toBeInTheDocument();
    expect(screen.getByTestId("page-skeleton-card-0")).toBeInTheDocument();
    expect(screen.queryByTestId("page-skeleton-card-1")).toBeNull();
  });

  it("uses custom eyebrow + title copy when provided", () => {
    render(<PageSkeleton eyebrow="loading sources" title="Fetching the lake…" />);
    expect(screen.getByText("loading sources")).toBeInTheDocument();
    expect(screen.getByText("Fetching the lake…")).toBeInTheDocument();
  });

  it("clamps cards to a minimum of 1", () => {
    render(<PageSkeleton cards={0} />);
    expect(screen.getByTestId("page-skeleton-card-0")).toBeInTheDocument();
  });

  it("marks the wrapper aria-busy and aria-live for assistive tech", () => {
    render(<PageSkeleton />);
    const wrapper = screen.getByTestId("page-skeleton");
    expect(wrapper).toHaveAttribute("aria-busy", "true");
    expect(wrapper).toHaveAttribute("aria-live", "polite");
  });
});
