/**
 * /lake/catalog-drift searchParams parser tests (2026-05-16).
 *
 * Pins the URL-param → :class:`CatalogDriftFilter` conversion +
 * the filter → chip-map projection used by :class:`ActiveFilterChips`.
 * Closes the producer-side ``?drift_id=<id>`` deep-link from the L4
 * row's NEW "view L2 drift" chain link, completing the L4↦L2
 * evidence-link symmetry.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));
vi.mock("../../../../../lib/server/identity", () => ({
  getCurrentPerson: async () => null,
}));
vi.mock("../../../../../lib/catalog-drift", () => ({
  getProposedCatalogDrifts: vi.fn(async () => []),
  getAcknowledgedCatalogDrifts: vi.fn(async () => []),
  getRejectedCatalogDrifts: vi.fn(async () => []),
  getCatalogDriftStrategyStatus: vi.fn(async () => []),
  getImpactCountByDriftSource: vi.fn(async () => ({})),
  makeImpactCountKey: vi.fn(() => "key"),
}));
vi.mock("../actions", () => ({
  acknowledgeCatalogDrift: vi.fn(),
  rejectCatalogDrift: vi.fn(),
}));

import { __test__ } from "../page";

describe("/lake/catalog-drift searchParams parsing", () => {
  it("returns undefined when no recognised params are present", () => {
    expect(__test__.parseCatalogDriftFilter({})).toBeUndefined();
  });

  it("parses drift_id (producer-side deep-link)", () => {
    const f = __test__.parseCatalogDriftFilter({ drift_id: "drift-aaa" });
    expect(f).toEqual({ driftId: "drift-aaa" });
  });

  it("uses first value when drift_id is repeated (array form)", () => {
    const f = __test__.parseCatalogDriftFilter({
      drift_id: ["drift-aaa", "drift-bbb"],
    });
    expect(f).toEqual({ driftId: "drift-aaa" });
  });

  it("maps filter back to URL-param keys for the chip row", () => {
    const m = __test__.filterToChipMap({ driftId: "drift-aaa" });
    expect(m).toEqual({ drift_id: "drift-aaa" });
  });

  it("returns {} chip map when filter is undefined", () => {
    expect(__test__.filterToChipMap(undefined)).toEqual({});
  });
});
