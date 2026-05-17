/**
 * /lake/source-candidates searchParams parser tests (2026-05-16 —
 * Lake-Side Overview activity-stream drill-in completion bundle).
 *
 * Pins the URL-param → :class:`SourceCandidateFilter` conversion +
 * the filter → chip-map projection used by :class:`ActiveFilterChips`.
 * Mirrors the page-level filter parser tests for L2/L3/L5/L6 shipped
 * by ``bdee480`` and L4/L7/L8 from the same bundle.
 */
import { describe, expect, it, vi } from "vitest";

// The page imports server-only modules at the top level (
// ``getCurrentCompanyId`` reads cookies, the accessors instantiate
// pg.Pool). We mock them all to a no-op so the test only exercises
// the pure helpers we export from the page.
vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/source-candidates", () => ({
  getProposedSourceCandidates: vi.fn(async () => []),
  getPromotedSourceCandidates: vi.fn(async () => []),
  getRejectedSourceCandidates: vi.fn(async () => []),
  getSourceCandidateStrategyStatus: vi.fn(async () => []),
}));
vi.mock("../actions", () => ({
  promoteSourceCandidate: vi.fn(),
  rejectSourceCandidate: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/source-candidates searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseSourceCandidatesFilter({})).toBeUndefined();
    expect(
      __test__.parseSourceCandidatesFilter({ unknown: "x" }),
    ).toBeUndefined();
  });

  it("parses ?candidate_id= as the producer-side PK filter", () => {
    const f = __test__.parseSourceCandidatesFilter({
      candidate_id: "cand-aaa",
    });
    expect(f).toEqual({ candidateId: "cand-aaa" });
  });

  it("uses the first value when candidate_id is repeated (array form)", () => {
    const f = __test__.parseSourceCandidatesFilter({
      candidate_id: ["cand-aaa", "cand-bbb"],
    });
    expect(f).toEqual({ candidateId: "cand-aaa" });
  });
});

describe("/lake/source-candidates filterToChipMap", () => {
  it("returns {} when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });

  it("maps SourceCandidateFilter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({ candidateId: "cand-aaa" });
    expect(m).toEqual({ candidate_id: "cand-aaa" });
  });
});
