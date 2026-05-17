/**
 * Phase 3 Task 3E — replay-determinism unit tests for the KPI compare
 * accessor. Covers ``normalizeKpiValue`` (pure) and exercises the public
 * surface of ``replayKpiCompare`` (graceful no-Postgres path) so the
 * /kpis/compare RSC pass is honest about its dependencies.
 */
import { describe, it, expect } from "vitest";
import {
  normalizeKpiValue,
  replayKpiCompare,
} from "../../lib/server/kpi-compare";

describe("normalizeKpiValue", () => {
  it("passes through scalars", () => {
    expect(normalizeKpiValue(42)).toBe(42);
    expect(normalizeKpiValue(3.14)).toBe(3.14);
    expect(normalizeKpiValue("net_revenue")).toBe("net_revenue");
  });

  it("returns null for null / undefined", () => {
    expect(normalizeKpiValue(null)).toBeNull();
    expect(normalizeKpiValue(undefined)).toBeNull();
  });

  it("unwraps {value: x} dicts to x", () => {
    expect(normalizeKpiValue({ value: 99 })).toBe(99);
    expect(normalizeKpiValue({ value: "tier_1" })).toBe("tier_1");
  });

  it("unwraps single-key dicts to the inner scalar", () => {
    expect(normalizeKpiValue({ count: 12 })).toBe(12);
    expect(normalizeKpiValue({ label: "q3" })).toBe("q3");
  });

  it("falls back to canonical sorted-key JSON for multi-key dicts", () => {
    const a = normalizeKpiValue({ b: 2, a: 1, c: 3 });
    // Sorted-key JSON is byte-stable across two snapshots of the same dict.
    expect(a).toBe('{"a":1,"b":2,"c":3}');
    expect(normalizeKpiValue({ a: 1, b: 2, c: 3 })).toBe(a);
  });

  it("stringifies arrays for deterministic comparison", () => {
    expect(normalizeKpiValue([1, 2, 3])).toBe("[1,2,3]");
  });

  it("encodes booleans as 'true' / 'false' strings", () => {
    expect(normalizeKpiValue(true)).toBe("true");
    expect(normalizeKpiValue(false)).toBe("false");
  });
});

describe("replayKpiCompare (no Postgres path)", () => {
  it("returns honest empty snapshots when no Postgres is wired", async () => {
    // No DATABASE_URL in test env → pgQuery throws → catch returns empty.
    const { a, b } = await replayKpiCompare(
      "revenue.q3",
      "2026-04-26T00:00:00Z",
      "2026-04-27T00:00:00Z",
    );
    expect(a.found).toBe(false);
    expect(a.value).toBeNull();
    expect(a.hash).toBe("");
    expect(b.found).toBe(false);
    expect(b.value).toBeNull();
    expect(b.hash).toBe("");
  });

  it("returns honest empty snapshots when both timestamps are null", async () => {
    const { a, b } = await replayKpiCompare("revenue.q3", null, null);
    expect(a.found).toBe(false);
    expect(b.found).toBe(false);
    expect(a.scanCount).toBe(0);
    expect(b.scanCount).toBe(0);
  });

  it("treats only-T1 as a single-replay surface (B is empty)", async () => {
    const { a, b } = await replayKpiCompare(
      "revenue.q3",
      "2026-04-26T00:00:00Z",
      null,
    );
    // The DB call may still fail → both empty; the contract is that B
    // is at least empty and matches the ``found: false`` shape.
    expect(b.found).toBe(false);
    expect(b.hash).toBe("");
    // A may also be ``found: false`` in the no-Postgres path; we don't
    // assert on that here — see the top-level test for the no-Postgres
    // contract.
    expect(a).toBeDefined();
  });
});
