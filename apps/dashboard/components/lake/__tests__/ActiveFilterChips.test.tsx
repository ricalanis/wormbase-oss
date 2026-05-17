/**
 * ActiveFilterChips component tests (2026-05-16).
 *
 * Pins:
 *   * Renders nothing when all filter values are undefined / empty
 *     (honest empty state — no chrome when no filter applies).
 *   * Renders one chip per active filter key, with the value
 *     surfaced verbatim and the label override (when provided).
 *   * Clear-filter link points at the supplied ``clearHref``.
 *   * Each chip carries a per-key testid so per-page tests can
 *     assert which filters are active.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ActiveFilterChips } from "../ActiveFilterChips";

describe("ActiveFilterChips", () => {
  it("returns null when no filter values are active", () => {
    const { container } = render(
      <ActiveFilterChips
        filter={{}}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null when all filter values are undefined", () => {
    const { container } = render(
      <ActiveFilterChips
        filter={{ a: undefined, b: undefined }}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null when filter values are empty strings", () => {
    const { container } = render(
      <ActiveFilterChips
        filter={{ a: "", b: undefined }}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders one chip per active filter with the value surfaced", () => {
    render(
      <ActiveFilterChips
        filter={{
          upstream_semantic_type_id: "sem-aaa",
          source_id: "src-1",
        }}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(
      screen.getByTestId("active-filter-chip-upstream_semantic_type_id"),
    ).toHaveTextContent("sem-aaa");
    expect(screen.getByTestId("active-filter-chip-source_id")).toHaveTextContent(
      "src-1",
    );
  });

  it("applies friendly label overrides when provided", () => {
    render(
      <ActiveFilterChips
        filter={{ upstream_semantic_type_id: "sem-aaa" }}
        clearHref="/lake/quality"
        labels={{
          upstream_semantic_type_id: "upstream semantic type",
        }}
      />,
    );
    const chip = screen.getByTestId(
      "active-filter-chip-upstream_semantic_type_id",
    );
    expect(chip.textContent?.toLowerCase()).toContain("upstream semantic type");
  });

  it("renders the clear-filter link pointing at clearHref", () => {
    render(
      <ActiveFilterChips
        filter={{ upstream_semantic_type_id: "sem-aaa" }}
        clearHref="/lake/entity-stitches"
      />,
    );
    const link = screen.getByTestId("active-filter-clear-link");
    expect(link.getAttribute("href")).toBe("/lake/entity-stitches");
    expect(link.textContent?.toLowerCase()).toContain("clear");
  });

  it("honors the testId override", () => {
    render(
      <ActiveFilterChips
        testId="schema-impact-active-filters"
        filter={{ upstream_lineage_edge_id: "edge-1" }}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(
      screen.getByTestId("schema-impact-active-filters"),
    ).toBeInTheDocument();
  });

  it("skips chips for undefined-valued keys when other keys are active", () => {
    render(
      <ActiveFilterChips
        filter={{
          upstream_lineage_edge_id: "edge-1",
          upstream_classification_id: undefined,
          source_id: "src-7",
        }}
        clearHref="/lake/schema-impact"
      />,
    );
    expect(
      screen.getByTestId("active-filter-chip-upstream_lineage_edge_id"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("active-filter-chip-source_id"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("active-filter-chip-upstream_classification_id"),
    ).not.toBeInTheDocument();
  });
});
