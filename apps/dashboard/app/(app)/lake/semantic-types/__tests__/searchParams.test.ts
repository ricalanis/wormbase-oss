/**
 * /lake/semantic-types searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`SemanticTypeFilter` conversion +
 * the filter → chip-map projection used by :class:`ActiveFilterChips`.
 * Closes the producer-side ``?type_id=<id>`` deep-link from any
 * consumer-page row carrying an upstream L5 semantic type id.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/semantic-types", () => ({
  getProposedSemanticTypes: vi.fn(async () => []),
  getConfirmedSemanticTypes: vi.fn(async () => []),
  getRejectedSemanticTypes: vi.fn(async () => []),
  getSemanticTypeStrategyStatus: vi.fn(async () => []),
  getClassificationCountBySemanticType: vi.fn(async () => ({})),
  getEntityStitchCountBySemanticType: vi.fn(async () => ({})),
  getQualityCheckCountBySemanticType: vi.fn(async () => ({})),
  getSchemaImpactCountBySemanticType: vi.fn(async () => ({})),
}));
vi.mock("../actions", () => ({
  confirmSemanticType: vi.fn(),
  rejectSemanticType: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/semantic-types searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseSemanticTypeFilter({})).toBeUndefined();
  });

  it("parses type_id (producer-side deep-link)", () => {
    const f = __test__.parseSemanticTypeFilter({ type_id: "type-aaa" });
    expect(f).toEqual({ typeId: "type-aaa" });
  });

  it("uses first value when type_id is repeated (array form)", () => {
    const f = __test__.parseSemanticTypeFilter({
      type_id: ["type-aaa", "type-bbb"],
    });
    expect(f).toEqual({ typeId: "type-aaa" });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({ typeId: "type-aaa" });
    expect(m).toEqual({ type_id: "type-aaa" });
  });

  it("returns {} chip map when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });
});
