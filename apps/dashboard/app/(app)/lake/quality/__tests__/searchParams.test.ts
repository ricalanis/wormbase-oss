/**
 * /lake/quality searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`QualityCheckFilter` conversion.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/quality", () => ({
  getProposedQualityChecks: vi.fn(async () => []),
  getConfirmedQualityChecks: vi.fn(async () => []),
  getRejectedQualityChecks: vi.fn(async () => []),
  getQualityStrategyStatus: vi.fn(async () => []),
}));
vi.mock("../actions", () => ({
  confirmQualityCheck: vi.fn(),
  rejectQualityCheck: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/quality searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseQualityCheckFilter({})).toBeUndefined();
  });

  it("parses upstream_semantic_type_id (R4 reverse arc)", () => {
    const f = __test__.parseQualityCheckFilter({
      upstream_semantic_type_id: "sem-aaa",
    });
    expect(f).toEqual({ upstreamSemanticTypeId: "sem-aaa" });
  });

  // L7 producer-side PK deep-link (2026-05-16 — drill-in completion bundle).
  it("parses check_id producer-side PK deep-link", () => {
    const f = __test__.parseQualityCheckFilter({ check_id: "check-xyz" });
    expect(f).toEqual({ checkId: "check-xyz" });
  });

  it("composes upstream_semantic_type_id AND check_id when both present", () => {
    const f = __test__.parseQualityCheckFilter({
      upstream_semantic_type_id: "sem-1",
      check_id: "check-2",
    });
    expect(f).toEqual({ upstreamSemanticTypeId: "sem-1", checkId: "check-2" });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({
      upstreamSemanticTypeId: "sem-aaa",
    });
    expect(m).toEqual({
      upstream_semantic_type_id: "sem-aaa",
      check_id: undefined,
    });
  });

  it("maps check_id back to its URL-param key", () => {
    const m = __test__.filterToChipMap({ checkId: "check-zzz" });
    expect(m.check_id).toBe("check-zzz");
  });
});
