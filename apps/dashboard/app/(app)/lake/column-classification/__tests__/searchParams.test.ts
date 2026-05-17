/**
 * /lake/column-classification searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`ColumnClassificationFilter` conversion.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/column-classification", () => ({
  getProposedColumnClassifications: vi.fn(async () => []),
  getConfirmedColumnClassifications: vi.fn(async () => []),
  getRejectedColumnClassifications: vi.fn(async () => []),
  getColumnClassificationStrategyStatus: vi.fn(async () => []),
  getL5DependencyState: vi.fn(async () => ({
    l5Enabled: false,
    confirmedSemanticTypeCount: 0,
  })),
  getSchemaImpactCountByClassification: vi.fn(async () => ({})),
}));
vi.mock("../actions", () => ({
  confirmColumnClassification: vi.fn(),
  rejectColumnClassification: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/column-classification searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(
      __test__.parseColumnClassificationFilter({}),
    ).toBeUndefined();
  });

  it("parses upstream_semantic_type_id (R2 reverse arc)", () => {
    const f = __test__.parseColumnClassificationFilter({
      upstream_semantic_type_id: "sem-aaa",
    });
    expect(f).toEqual({ upstreamSemanticTypeId: "sem-aaa" });
  });

  it("parses classification_id (producer-side deep-link)", () => {
    const f = __test__.parseColumnClassificationFilter({
      classification_id: "cls-111",
    });
    expect(f).toEqual({ classificationId: "cls-111" });
  });

  it("composes both filter axes when both params are present", () => {
    const f = __test__.parseColumnClassificationFilter({
      upstream_semantic_type_id: "sem-aaa",
      classification_id: "cls-111",
    });
    expect(f).toEqual({
      upstreamSemanticTypeId: "sem-aaa",
      classificationId: "cls-111",
    });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({
      upstreamSemanticTypeId: "sem-aaa",
    });
    expect(m).toEqual({
      upstream_semantic_type_id: "sem-aaa",
      classification_id: undefined,
    });
  });

  it("maps classificationId back to URL-param key", () => {
    const m = __test__.filterToChipMap({ classificationId: "cls-111" });
    expect(m).toEqual({
      upstream_semantic_type_id: undefined,
      classification_id: "cls-111",
    });
  });

  it("returns {} chip map when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });
});
