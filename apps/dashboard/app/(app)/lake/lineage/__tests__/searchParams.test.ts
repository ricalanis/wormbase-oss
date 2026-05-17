/**
 * /lake/lineage searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`LineageFilter` conversion + the
 * filter → chip-map projection used by :class:`ActiveFilterChips`.
 * Closes the producer-side ``?edge_id=<id>`` deep-link from the L4
 * row's "view L3 edge" chain link.
 */
import { describe, expect, it, vi } from "vitest";

// Mock server-only modules so the parser tests don't try to read
// cookies or instantiate pg.Pool. We only exercise the pure helpers
// exported from the page.
vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/lineage", () => ({
  getProposedLineageEdges: vi.fn(async () => []),
  getConfirmedLineageEdges: vi.fn(async () => []),
  getRejectedLineageEdges: vi.fn(async () => []),
  getLineageStrategyStatus: vi.fn(async () => []),
  getSchemaImpactCountByLineageEdge: vi.fn(async () => ({})),
}));
vi.mock("../actions", () => ({
  confirmLineageEdge: vi.fn(),
  rejectLineageEdge: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/lineage searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseLineageFilter({})).toBeUndefined();
  });

  it("parses edge_id (producer-side deep-link)", () => {
    const f = __test__.parseLineageFilter({ edge_id: "edge-aaa" });
    expect(f).toEqual({ edgeId: "edge-aaa" });
  });

  it("uses first value when edge_id is repeated (array form)", () => {
    const f = __test__.parseLineageFilter({
      edge_id: ["edge-aaa", "edge-bbb"],
    });
    expect(f).toEqual({ edgeId: "edge-aaa" });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({ edgeId: "edge-aaa" });
    expect(m).toEqual({ edge_id: "edge-aaa" });
  });

  it("returns {} chip map when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });
});
