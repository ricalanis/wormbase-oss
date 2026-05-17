/**
 * Unit tests for /governance/tenant-quota (post-rest #3, 2026-05-13).
 *
 * The reader accessors are direct raw-ledger scans (parametrized SQL —
 * see lib/tenant-quota.ts); the network path is exercised in
 * integration tests rather than mocked here. These tests pin:
 *
 *   1. ``consumptionBand`` returns the right band for the 90% / 70%
 *      thresholds — the visual hint contract.
 *   2. ``asTrigger`` defaults to ``count_threshold`` on unknown / null
 *      input but round-trips the three real discriminators.
 *   3. ``normalizeTriggerFilter`` (on the page) normalizes the query-
 *      string filter back to the active trigger or "all".
 *   4. Reader empty-state: with no DATABASE_URL / WORMBASE_LEDGER_DSN
 *      env the accessors return ``[]`` without throwing.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  __test__,
  getRecentQuotaEvents,
  getTenantQuotaSummary,
} from "../../lib/tenant-quota";
import { __test__ as page__test__ } from "../../app/(app)/governance/tenant-quota/page";

const { asTrigger, consumptionBand } = __test__;
const { normalizeTriggerFilter } = page__test__;

describe("consumptionBand", () => {
  it("returns 'critical' at >= 90% consumption", () => {
    expect(consumptionBand(90, 100)).toBe("critical");
    expect(consumptionBand(100, 100)).toBe("critical");
    expect(consumptionBand(95_000, 100_000)).toBe("critical");
  });

  it("returns 'warn' at >= 70% and < 90%", () => {
    expect(consumptionBand(70, 100)).toBe("warn");
    expect(consumptionBand(89, 100)).toBe("warn");
    expect(consumptionBand(75_000, 100_000)).toBe("warn");
  });

  it("returns 'healthy' below 70%", () => {
    expect(consumptionBand(0, 100)).toBe("healthy");
    expect(consumptionBand(69, 100)).toBe("healthy");
    expect(consumptionBand(12_234, 100_000)).toBe("healthy");
  });

  it("returns 'healthy' when limit is zero or negative (degenerate)", () => {
    expect(consumptionBand(10, 0)).toBe("healthy");
    expect(consumptionBand(10, -5)).toBe("healthy");
  });
});

describe("asTrigger", () => {
  it("round-trips each real discriminator", () => {
    expect(asTrigger("count_threshold")).toBe("count_threshold");
    expect(asTrigger("time_threshold")).toBe("time_threshold");
    expect(asTrigger("quota_exhausted")).toBe("quota_exhausted");
  });

  it("defaults to 'count_threshold' on null / unknown input", () => {
    // Defensive — the read accessor never wants to crash on a stale row.
    expect(asTrigger(null)).toBe("count_threshold");
    expect(asTrigger(undefined)).toBe("count_threshold");
    expect(asTrigger("unknown_kind")).toBe("count_threshold");
    expect(asTrigger("")).toBe("count_threshold");
  });
});

describe("normalizeTriggerFilter (page)", () => {
  it("round-trips the three real triggers", () => {
    expect(normalizeTriggerFilter("count_threshold")).toBe("count_threshold");
    expect(normalizeTriggerFilter("time_threshold")).toBe("time_threshold");
    expect(normalizeTriggerFilter("quota_exhausted")).toBe("quota_exhausted");
  });

  it("falls back to 'all' on null / unknown query-param input", () => {
    expect(normalizeTriggerFilter(null)).toBe("all");
    expect(normalizeTriggerFilter("")).toBe("all");
    expect(normalizeTriggerFilter("garbage")).toBe("all");
  });
});

describe("reader empty-state (no Postgres env)", () => {
  let savedDb: string | undefined;
  let savedDsn: string | undefined;
  beforeEach(() => {
    savedDb = process.env.DATABASE_URL;
    savedDsn = process.env.WORMBASE_LEDGER_DSN;
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
  });
  afterEach(() => {
    if (savedDb === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = savedDb;
    if (savedDsn === undefined) delete process.env.WORMBASE_LEDGER_DSN;
    else process.env.WORMBASE_LEDGER_DSN = savedDsn;
  });

  it("getTenantQuotaSummary returns [] when no env is wired", async () => {
    const rows = await getTenantQuotaSummary("any-company-id");
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("getRecentQuotaEvents returns [] when no env is wired", async () => {
    const rows = await getRecentQuotaEvents("any-company-id");
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("getRecentQuotaEvents respects the triggeredBy filter shape even on empty", async () => {
    const rows = await getRecentQuotaEvents("any-company-id", {
      triggeredBy: "quota_exhausted",
      limit: 10,
    });
    expect(rows).toEqual([]);
  });
});
