/**
 * /lake/governance accessor tests (Wave 3 Task 6).
 *
 * Mocks the ``pg`` module so the accessor can be exercised without a
 * live Postgres dependency. Pins:
 *
 *   * Honest empty when ``DATABASE_URL`` is unset (test default).
 *   * SQL shape — reads ``projection_external_policy`` LEFT JOIN'd
 *     against ``projection_external_catalog`` for the source label.
 *   * Optional ``sourceId`` filter threads into the WHERE clause
 *     with a parameterized placeholder.
 *   * Row mapping converts Postgres snake_case to dashboard
 *     camelCase + preserves null body (per S2 spike contract).
 *   * applied_to JSON column round-trips as a string[].
 *   * ``getWormbasePolicies`` reads from the ledger via the
 *     ``emit_policy_applied`` DISTINCT-ON-policy_id query and
 *     returns ``[]`` when no policies have been applied.
 *
 * Pins ``feedback_onboarding_production_only`` posture: NO fixture
 * fallback on Postgres failures. Empty Postgres → empty list →
 * dashboard renders honest empty state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getExternalPolicies (no DATABASE_URL)", () => {
  it("returns [] when DATABASE_URL is not set", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getExternalPolicies(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("getWormbasePolicies also returns [] without DATABASE_URL", async () => {
    vi.resetModules();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getWormbasePolicies(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});

describe("getExternalPolicies (Postgres path)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("issues the projection_external_policy SQL with the JOIN", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-governance");
    await mod.getExternalPolicies(COMPANY_ID);

    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("projection_external_policy");
    expect(sql).toContain("projection_external_catalog");
    expect(sql).toContain("p.company_id = $1");
  });

  it("appends a parameterized source_id filter when opts.sourceId is set", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-governance");
    await mod.getExternalPolicies(COMPANY_ID, {
      sourceId: "22222222-2222-2222-2222-222222222222",
    });

    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("p.source_id = $2");
    expect(queryMock.mock.calls[0][1]).toEqual([
      COMPANY_ID,
      "22222222-2222-2222-2222-222222222222",
      expect.any(Number),
    ]);
  });

  it("maps snake_case Postgres rows to camelCase ExternalPolicyRow", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "00000000-0000-0000-0000-000000000099",
          source_id: "00000000-0000-0000-0000-000000000001",
          source_name: "snowflake_native",
          policy_fqn: "ACME.RAW.REVENUE_MASK",
          policy_kind: "masking",
          body:
            "CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END",
          applied_to: [
            "ACME.RAW.REVENUE.amount",
            "ACME.RAW.REVENUE.tax",
          ],
          imported_at: "2026-05-11T10:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getExternalPolicies(COMPANY_ID);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({
      id: "00000000-0000-0000-0000-000000000099",
      sourceId: "00000000-0000-0000-0000-000000000001",
      sourceName: "snowflake_native",
      policyFqn: "ACME.RAW.REVENUE_MASK",
      policyKind: "masking",
      body: "CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END",
      appliedTo: ["ACME.RAW.REVENUE.amount", "ACME.RAW.REVENUE.tax"],
      importedAt: "2026-05-11T10:00:00.000Z",
    });
  });

  it("preserves NULL body verbatim (S2 spike contract)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "00000000-0000-0000-0000-000000000088",
          source_id: "00000000-0000-0000-0000-000000000002",
          source_name: null,
          policy_fqn: "ACME.RAW.PII_ROW_ACCESS",
          policy_kind: "row_access",
          body: null,
          applied_to: ["ACME.RAW.CUSTOMERS"],
          imported_at: "2026-05-11T11:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getExternalPolicies(COMPANY_ID);

    expect(rows[0].body).toBeNull();
    // Falls back to "(unknown source)" when the LEFT JOIN doesn't
    // produce a source_name — the catalog import may not have
    // landed yet on a fresh source.
    expect(rows[0].sourceName).toBe("(unknown source)");
    expect(rows[0].appliedTo).toEqual(["ACME.RAW.CUSTOMERS"]);
  });

  it("falls back to [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getExternalPolicies(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("parses applied_to even when Postgres returns it as a JSON string", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "00000000-0000-0000-0000-000000000077",
          source_id: "00000000-0000-0000-0000-000000000003",
          source_name: "dbt",
          policy_fqn: "ACME.MULTI_COL",
          policy_kind: "masking",
          body: "SELECT 1",
          // Some drivers stringify JSON; defensive parser test.
          applied_to: '["col_a","col_b","col_c"]',
          imported_at: "2026-05-11T12:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getExternalPolicies(COMPANY_ID);
    expect(rows[0].appliedTo).toEqual(["col_a", "col_b", "col_c"]);
  });
});

describe("getWormbasePolicies (Postgres path)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("issues the emit_policy_applied DISTINCT-ON query", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-governance");
    await mod.getWormbasePolicies(COMPANY_ID);

    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("emit_policy_applied");
    expect(sql).toContain("DISTINCT ON");
  });

  it("returns [] when no policies have been applied", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getWormbasePolicies(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("maps ledger rows to WormbasePolicyRow with scope inference", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          policy_id: "warmup_pii_redact",
          policy_name: "Warmup PII redaction",
          gate_impl: "policy.warmup_pii_redact_v1",
          applies_to: { domain: "finance" },
        },
        {
          policy_id: "interjection_budget",
          policy_name: null,
          gate_impl: "policy.interjection_budget_v1",
          applies_to: null,
        },
        {
          policy_id: "channel_talkativeness",
          policy_name: "Channel talkativeness",
          gate_impl: "policy.channel_talkativeness_v1",
          applies_to: { channel: "C012345" },
        },
      ],
      rowCount: 3,
    });
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getWormbasePolicies(COMPANY_ID);

    expect(rows).toHaveLength(3);
    const byId = new Map(rows.map((r) => [r.id, r]));
    expect(byId.get("warmup_pii_redact")?.scope).toBe("per-domain");
    expect(byId.get("interjection_budget")?.scope).toBe("global");
    expect(byId.get("channel_talkativeness")?.scope).toBe("per-channel");
    expect(byId.get("interjection_budget")?.policyName).toBe(
      "interjection_budget",
    );
  });

  it("returns [] when the query throws (honest empty)", async () => {
    queryMock.mockRejectedValueOnce(new Error("table missing"));
    const mod = await import("../../lib/lake-governance");
    const rows = await mod.getWormbasePolicies(COMPANY_ID);
    expect(rows).toEqual([]);
  });
});
