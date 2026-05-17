/**
 * confirmBusinessDefAction graduation tests — Sub-wave D.
 *
 * Validates the three branches:
 *   1. Worm-core endpoint reachable + prior proposal → real PEVR
 *      receipt (entry_ids[0] as hash).
 *   2. Worm-core endpoint returns 404 (no prior proposal) → falls
 *      back to synthetic receipt so the wizard still completes.
 *   3. WORMBASE_LEDGER_API_TOKEN unset → synthetic receipt fallback
 *      (no half-attempt against an unauthenticated endpoint).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const ORIGINAL_ENV = { ...process.env };

const {
  confirmConceptMock,
  confirmBusinessDefMock,
  getCurrentCompanyIdMock,
  getCurrentPersonMock,
  getTenantFromCookiesMock,
} = vi.hoisted(() => ({
  confirmConceptMock: vi.fn(),
  confirmBusinessDefMock: vi.fn(),
  getCurrentCompanyIdMock: vi.fn(),
  getCurrentPersonMock: vi.fn(),
  getTenantFromCookiesMock: vi.fn(),
}));

vi.mock("../../lib/server/worm-core-write", () => ({
  confirmConcept: confirmConceptMock,
}));

vi.mock("../../lib/server/identity", () => ({
  getCurrentPerson: getCurrentPersonMock,
}));

vi.mock("../../lib/ledger-client", () => ({
  assignDomainOwner: vi.fn(async () => ({
    hash: "synth-domain",
    source: "test",
    owner: "test",
    classification: "internal",
    ts: "2026-05-15T00:00:00Z",
  })),
  confirmBusinessDef: confirmBusinessDefMock,
  rejectBusinessDef: vi.fn(async () => ({
    hash: "synth-reject",
    source: "test",
    owner: "test",
    classification: "internal",
    ts: "2026-05-15T00:00:00Z",
  })),
}));

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: getCurrentCompanyIdMock,
  getTenantFromCookies: getTenantFromCookiesMock,
}));

import { confirmBusinessDefAction } from "../../app/onboarding/tier2/actions";

beforeEach(() => {
  confirmConceptMock.mockReset();
  confirmBusinessDefMock.mockReset();
  getCurrentCompanyIdMock.mockReset();
  getCurrentPersonMock.mockReset();
  getTenantFromCookiesMock.mockReset();
  // Default synthetic receipt.
  confirmBusinessDefMock.mockResolvedValue({
    hash: "synth-hash",
    source: "onboarding · tier 2",
    owner: "ricardo",
    classification: "internal",
    ts: "2026-05-15T00:00:00Z",
  });
  getCurrentCompanyIdMock.mockResolvedValue("co-uuid-1");
  getTenantFromCookiesMock.mockResolvedValue({
    slug: "acme",
    companyId: "co-uuid-1",
    source: "cookie",
  });
  getCurrentPersonMock.mockResolvedValue({
    personId: "person-1",
    name: "Carol Admin",
    position: "VP Data",
    tenancyRole: "admin",
  });
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("confirmBusinessDefAction graduation", () => {
  it("returns missing-term error on empty input", async () => {
    const out = await confirmBusinessDefAction("");
    expect(out.ok).toBe(false);
    expect(out.error).toBe("missing term");
  });

  it("calls the real concept_confirmed endpoint when env + prior proposal exist", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "tok";
    confirmConceptMock.mockResolvedValueOnce({
      term: "MRR",
      concept_id: "concept-uuid-1",
      entry_ids: ["entry-uuid-1", "entry-uuid-2", "entry-uuid-3"],
    });
    const out = await confirmBusinessDefAction("MRR");
    expect(out.ok).toBe(true);
    expect(out.receipt?.hash).toBe("entry-uuid-1");
    expect(out.receipt?.source).toContain("concept_confirmed");
    expect(confirmConceptMock).toHaveBeenCalledWith({
      tenantSlug: "acme",
      companyId: "co-uuid-1",
      term: "MRR",
      confirmedByPersonId: "person-1",
    });
  });

  it("falls back to synthetic receipt on 404 (no prior proposal)", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "tok";
    confirmConceptMock.mockRejectedValueOnce(
      new Error("worm-core POST /api/v1/write_actions/concept_confirmed/MRR returned 404: not found"),
    );
    const out = await confirmBusinessDefAction("MRR");
    expect(out.ok).toBe(true);
    expect(out.receipt?.hash).toBe("synth-hash");
  });

  it("surfaces non-404 errors (auth, network) honestly", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "tok";
    confirmConceptMock.mockRejectedValueOnce(
      new Error("worm-core POST /api/v1/write_actions/concept_confirmed/MRR returned 401: unauthorized"),
    );
    const out = await confirmBusinessDefAction("MRR");
    expect(out.ok).toBe(false);
    expect(out.error).toContain("401");
  });

  it("falls back to synthetic receipt when WORMBASE_LEDGER_API_TOKEN unset", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const out = await confirmBusinessDefAction("ARR");
    expect(out.ok).toBe(true);
    expect(out.receipt?.hash).toBe("synth-hash");
    expect(confirmConceptMock).not.toHaveBeenCalled();
  });

  it("threads the current admin Person id through (never a placeholder)", async () => {
    process.env.WORMBASE_LEDGER_API_TOKEN = "tok";
    confirmConceptMock.mockResolvedValueOnce({
      term: "NPS",
      concept_id: "c1",
      entry_ids: ["e1"],
    });
    getCurrentPersonMock.mockResolvedValueOnce({
      personId: "person-admin-uuid",
      name: "Carol",
      position: "VP",
      tenancyRole: "admin",
    });
    await confirmBusinessDefAction("NPS");
    expect(confirmConceptMock).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmedByPersonId: "person-admin-uuid",
      }),
    );
  });
});
