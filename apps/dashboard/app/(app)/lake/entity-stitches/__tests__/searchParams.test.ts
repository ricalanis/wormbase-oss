/**
 * /lake/entity-stitches searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`EntityStitchFilter` conversion.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/entity-stitches", () => ({
  getProposedEntityStitches: vi.fn(async () => []),
  getConfirmedEntityStitches: vi.fn(async () => []),
  getRejectedEntityStitches: vi.fn(async () => []),
  getEntityStitchStrategyStatus: vi.fn(async () => []),
  getL5DependencyStateForStitches: vi.fn(async () => ({
    l5Enabled: false,
    confirmedSemanticTypeCount: 0,
  })),
}));
vi.mock("../actions", () => ({
  confirmEntityStitch: vi.fn(),
  rejectEntityStitch: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/entity-stitches searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseEntityStitchFilter({})).toBeUndefined();
  });

  it("parses upstream_semantic_type_id (R3 reverse arc)", () => {
    const f = __test__.parseEntityStitchFilter({
      upstream_semantic_type_id: "sem-aaa",
    });
    expect(f).toEqual({ upstreamSemanticTypeId: "sem-aaa" });
  });

  // L8 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("parses stitch_id producer-side PK deep-link", () => {
    const f = __test__.parseEntityStitchFilter({ stitch_id: "stitch-xyz" });
    expect(f).toEqual({ stitchId: "stitch-xyz" });
  });

  it("composes upstream_semantic_type_id AND stitch_id when both present", () => {
    const f = __test__.parseEntityStitchFilter({
      upstream_semantic_type_id: "sem-1",
      stitch_id: "stitch-2",
    });
    expect(f).toEqual({
      upstreamSemanticTypeId: "sem-1",
      stitchId: "stitch-2",
    });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({
      upstreamSemanticTypeId: "sem-aaa",
    });
    expect(m).toEqual({
      upstream_semantic_type_id: "sem-aaa",
      stitch_id: undefined,
    });
  });

  it("maps stitch_id back to its URL-param key", () => {
    const m = __test__.filterToChipMap({ stitchId: "stitch-zzz" });
    expect(m.stitch_id).toBe("stitch-zzz");
  });
});
