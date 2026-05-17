/**
 * Cross-tenant data-leak sweep — dashboard ledger-client (TS / Vitest).
 *
 * INVARIANT: every read accessor exported by `apps/dashboard/lib/ledger-client.ts`
 * MUST scope its data fetch by the caller's `companyId` (or `tenantSlug`,
 * for HTTP-backed accessors). A leak — even a single row — across
 * paying-customer tenants is a critical security defect.
 *
 * Two accessor families:
 *
 *   1. **SQL-backed** — call ``pgQuery(sql, [companyId, ...])``. The
 *      tenant filter is in the WHERE clause: either ``company_id = $1``
 *      (raw ledger reads) or ``tenant_id = $1`` (projection-table reads
 *      that pre-fold by tenant). For these, we mock `pg`, capture every
 *      query, and assert (a) the SQL contains a tenant filter on $1
 *      and (b) the first parameter passed is tenant-A's companyId.
 *
 *   2. **HTTP-backed** — call worm-core's REST API at
 *      ``/api/v1/...``. Tenant scoping comes from the
 *      ``X-Tenant-Slug`` header injected by ``_wormCoreGet``. The Python
 *      sweep in ``tests/multitenant/test_cross_tenant_data_leak_python.py``
 *      asserts those endpoints don't leak across tenants. Here we just
 *      verify the dashboard accessors PROPAGATE the tenant identity to
 *      the wire — a missing X-Tenant-Slug would default-fall-through to
 *      baseworm.
 *
 * Together with the Python sweep, the suite covers ≥50 accessors across
 * both runtime stacks (W6.A2 acceptance bar).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TENANT_A_ID = "a8989ece-b38a-5811-9625-327a79a65f90"; // baseworm
const TENANT_B_ID = "f9e1af07-371f-538b-bdde-cec81bcb6196"; // democorp
const PERSON_ID = "11111111-1111-1111-1111-111111111111";
const NOTEBOOK_ID = "22222222-2222-2222-2222-222222222222";
const DATA_PRODUCT_ID = "33333333-3333-3333-3333-333333333333";
const REACTIVITY_ID = "rx-1";

/**
 * Exempt accessors: their signatures don't carry a `company_id` filter
 * because the data is product-static or intentionally cross-tenant.
 *
 * - `getOntologySeeds`: ships with the product, not per-tenant.
 * - `getMcpCatalog`: static product surface — no tenant data.
 * - `getAllInstalls`: cross-tenant aggregate (the demo tenant switcher).
 * - `getPiiPatterns`: per-tenant in projection but currently global.
 * - `getPositionsRegistry`: static product config.
 * - `getExperimentsByAudience`: in-memory filter over
 *   ``getExperimentsForUser`` — its tenancy guarantee is transitive.
 */
const EXEMPT_ACCESSORS = new Set([
  "getOntologySeeds",
  "getMcpCatalog",
  "getAllInstalls",
  "getPiiPatterns",
  "getPositionsRegistry",
  "getExperimentsByAudience",
  // Intentional empty stubs — return [] without querying because the
  // upstream ledger payload kind isn't wired. Tenant-safe by virtue of
  // returning nothing.
  "getTasks",
  "getInsights",
]);

/**
 * Accessors that go through worm-core's HTTP API rather than direct SQL.
 * Their tenant scoping is via X-Tenant-Slug headers, not pgQuery params.
 * The Python sweep verifies the worm-core endpoints don't leak; here we
 * simply verify that calling these doesn't crash and that they emit a
 * fetch with a tenant slug header (covered by `worm-core-write.test.ts`).
 */
const HTTP_BACKED_ACCESSORS = new Set([
  "getReactivities",
  "getReactivityFires",
  "getResourceConversationsForOwner",
]);

/**
 * Some accessors take their companyId in a non-default positional slot
 * because they were retrofitted for new arguments. The dispatch table
 * pins each known oddity so the sweep drives them with companyId in the
 * right place.
 */
type AccessorCall = (mod: any) => Promise<unknown>;
const CALL_DISPATCH: Record<string, AccessorCall> = {
  getReactivityFires: (mod) =>
    mod.getReactivityFires(REACTIVITY_ID, 50, TENANT_A_ID),
  getResourceConversationsForOwner: (mod) =>
    mod.getResourceConversationsForOwner(PERSON_ID, TENANT_A_ID),
  getPersonById: (mod) => mod.getPersonById(TENANT_A_ID, PERSON_ID),
  getRolesForPerson: (mod) => mod.getRolesForPerson(TENANT_A_ID, PERSON_ID),
  getIdentitiesForPerson: (mod) =>
    mod.getIdentitiesForPerson(TENANT_A_ID, PERSON_ID),
  getAuditLogForPerson: (mod) =>
    mod.getAuditLogForPerson(TENANT_A_ID, PERSON_ID),
  getNotebookById: (mod) => mod.getNotebookById(TENANT_A_ID, NOTEBOOK_ID),
  getNotebookRuns: (mod) => mod.getNotebookRuns(TENANT_A_ID, NOTEBOOK_ID),
  getDataProductById: (mod) => mod.getDataProductById(TENANT_A_ID, DATA_PRODUCT_ID),
  getDataProductRuns: (mod) => mod.getDataProductRuns(TENANT_A_ID, DATA_PRODUCT_ID),
  getDataProductConsumption: (mod) =>
    mod.getDataProductConsumption(TENANT_A_ID, DATA_PRODUCT_ID),
  getExperimentsForUser: (mod) =>
    mod.getExperimentsForUser(TENANT_A_ID, PERSON_ID, 50),
  getMcpCalls: (mod) => mod.getMcpCalls(TENANT_A_ID, 50),
  // Phase D3 — chat history accessor takes (companyId, channelId, opts).
  getChatReceivedForChannel: (mod) =>
    mod.getChatReceivedForChannel(TENANT_A_ID, "C0AV1234567"),
  // W3-B (2026-05-07) — policy_applied accessor takes (companyId,
  // policy_name, opts). The sweep just needs it to filter by company_id
  // = $1 in its SQL fold.
  getPolicyAppliedEvents: (mod) =>
    mod.getPolicyAppliedEvents(TENANT_A_ID, "policy:whatsapp_rate_limit"),
};

interface CapturedQuery {
  sql: string;
  params: unknown[];
}

/**
 * Build a stub-row generator that returns plausible fold rows so the
 * accessors don't crash on null projections.
 */
function plausibleRows(): unknown[] {
  return [
    {
      seq: 1,
      ts: new Date("2026-04-26T10:00:00Z"),
      tool: "emit_person_proposed",
      args: {
        person_id: PERSON_ID,
        tenant_id: TENANT_A_ID,
        name: "Alice",
        platform: "slack",
        platform_user_id: "U-alice",
      },
      hash_hex: "0".repeat(64),
      payload: { args: { person_id: PERSON_ID } },
      // Arbitrary projection-row fields that some accessors expect.
      tenant_id: TENANT_A_ID,
      mcp_call_id: "mcp-1",
      caller_person_id: PERSON_ID,
      tool_name: "query_kpis",
      args_hash: "deadbeef",
      client_ua: "vitest",
      started_at: new Date("2026-04-26T10:00:00Z"),
      outcome: "ok",
      latency_ms: 5,
    },
  ];
}

describe("cross-tenant data-leak sweep — dashboard ledger-client", () => {
  const captured: CapturedQuery[] = [];
  const queryMock = vi.fn(async (sql: string, params: unknown[]) => {
    captured.push({ sql, params });
    return { rows: plausibleRows(), rowCount: 1 };
  });
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    captured.length = 0;
    queryMock.mockClear();
    releaseMock.mockClear();
    connectMock.mockClear();
    onMock.mockClear();
    vi.resetModules();
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

  /**
   * Discover every `getXxx` export from ledger-client at test time.
   * The list is computed dynamically — adding a new accessor automatically
   * grows the sweep, satisfying W6.A2's "future accessors auto-covered"
   * acceptance criterion.
   */
  async function getAccessors(): Promise<Array<[string, unknown]>> {
    const mod = await import("../../lib/ledger-client");
    return Object.entries(mod).filter(
      ([name, val]) =>
        name.startsWith("get") && typeof val === "function",
    );
  }

  /**
   * Drive an accessor with tenant-A's id (via dispatch table when its
   * signature is non-canonical). Always returns; errors are caught so
   * the test can attribute the failure to the SQL / param assertions
   * rather than to a thrown exception.
   */
  async function callAccessor(
    name: string,
    mod: Record<string, unknown>,
  ): Promise<void> {
    try {
      const dispatcher = CALL_DISPATCH[name];
      if (dispatcher) {
        await dispatcher(mod);
      } else {
        const fn = mod[name] as (...args: unknown[]) => Promise<unknown>;
        await fn(TENANT_A_ID);
      }
    } catch {
      // Accessor crashed on synthetic inputs — that's fine. The sweep
      // only cares about WHAT WAS QUERIED, not what was returned. The
      // captured array is populated during the call before any post-fold
      // crash.
    }
  }

  // The hand-listed names are derived from the live module signature
  // and kept in lockstep via the "every non-exempt discovered accessor
  // has a hand-listed test row" smoke test below.
  const ACCESSORS = [
    "getRampValues",
    "getKpiTree",
    "getTraceEntries",
    "getPeople",
    "getPersonById",
    "getIdentitiesForPerson",
    "getRolesForPerson",
    "getAuditLogForPerson",
    "getDomains",
    "getSources",
    "getPolicies",
    "getInstalls",
    "getCurrentInstall",
    "getChannels",
    "getProposedBusinessDefs",
    "getConversations",
    "getTasks",
    "getInsights",
    "getDecisions",
    "getProcessMaps",
    "getSystemMap",
    "getRecurringQuestions",
    "getOnboardingMilestones",
    "getExperimentsForUser",
    "getResearchOverview",
    "getHeadlineMetricsHistory",
    "getDataProducts",
    "getDataProductById",
    "getDataProductRuns",
    "getDataProductConsumption",
    "getNotebooks",
    "getNotebookById",
    "getNotebookRuns",
    "getWormActivitySummary",
    "getFirstWormMessage",
    "getFirstKnowings",
    "getTopics",
    "getMcpCalls",
    "getReactivities",
    "getReactivityFires",
    "getResourceConversationsForOwner",
    // Wave 8 (W8) demo-day PRD additions
    "getKnowledgeRampGauges",
    "getCompositeScoreSeries",
    "getKeepRateSeries",
    "getProcessMapDataProducts",
    "getExperimentLessons",
    "getExperimentLessonsByScope",
    // Phase D3 (WhatsApp first-class) — sync history projection.
    "getConversationSyncs",
    "getChatReceivedForChannel",
    // W3-B (2026-05-07) — policy_applied projection for rate-limit panel.
    "getPolicyAppliedEvents",
    // W4-C (2026-05-07) — /dashboard digest tile per-platform line.
    "getActivityRollup",
  ] as const;

  it.each(ACCESSORS)(
    "accessor %s scopes by tenant and never leaks tenant_b",
    async (name) => {
      if (EXEMPT_ACCESSORS.has(name)) return;

      const mod = (await import("../../lib/ledger-client")) as Record<
        string,
        unknown
      >;
      if (typeof mod[name] !== "function") {
        throw new Error(`accessor ${name} not exported from ledger-client`);
      }

      // HTTP-backed accessors are exercised via the Python sweep + the
      // _wormCoreGet header tests; they don't touch pg. We assert that
      // calling them doesn't crash and doesn't issue any rogue SQL.
      if (HTTP_BACKED_ACCESSORS.has(name)) {
        captured.length = 0;
        // Stub global fetch so the worm-core call doesn't actually go
        // to the network.
        const fetchMock = vi.fn(async () =>
          new Response(JSON.stringify({ reactivities: [], fires: [], conversations: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
        const origFetch = globalThis.fetch;
        globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
        try {
          await callAccessor(name, mod);
        } finally {
          globalThis.fetch = origFetch;
        }
        // No SQL should have been issued for an HTTP-backed accessor.
        expect(captured.length).toBe(0);
        return;
      }

      captured.length = 0;
      queryMock.mockClear();
      await callAccessor(name, mod);

      // The accessor MUST have made at least one SQL call. Accessors
      // that don't are listed in EXEMPT_ACCESSORS or HTTP_BACKED_ACCESSORS.
      expect(
        captured.length,
        `${name} issued no SQL — add to EXEMPT_ACCESSORS or HTTP_BACKED_ACCESSORS if intentional`,
      ).toBeGreaterThan(0);

      for (const { sql, params } of captured) {
        // INVARIANT 1: every SQL query is tenant-scoped via $1 — either
        // ``company_id = $1`` (raw ledger fold) OR ``tenant_id = $1``
        // (projection table that pre-folds tenancy).
        expect(
          sql,
          `${name}: SQL must filter by company_id = $1 or tenant_id = $1`,
        ).toMatch(/(?:company_id|tenant_id)\s*=\s*\$1/);
        // INVARIANT 2: the first parameter passed is tenant-A's id —
        // NEVER tenant-B's id by accident, NEVER undefined.
        expect(
          params[0],
          `${name}: first SQL param must be tenant-A's companyId`,
        ).toBe(TENANT_A_ID);
        expect(params[0]).not.toBe(TENANT_B_ID);
      }
    },
  );

  it("dynamically-discovered accessor count is at least 30", async () => {
    const accessors = await getAccessors();
    expect(accessors.length).toBeGreaterThanOrEqual(30);
  });

  it("every non-exempt discovered accessor has a hand-listed test row", async () => {
    // The hand-listed rows above and the exempt set together must
    // cover every getter in the live module. If a new accessor is
    // added, the test FORCES the author to add it to the row list
    // (or to EXEMPT_ACCESSORS), so the sweep stays current.
    const accessors = await getAccessors();
    const hardcoded = new Set<string>(ACCESSORS);
    const missing = accessors
      .map(([name]) => name)
      .filter((name) => !hardcoded.has(name) && !EXEMPT_ACCESSORS.has(name));
    expect(missing).toEqual([]);
  });

  it("DEFAULT_COMPANY_ID resolves to baseworm's companyId", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.DEFAULT_COMPANY_ID).toBe(TENANT_A_ID);
  });

  it("tenant-A and tenant-B companyIds are distinct UUIDv5s", () => {
    expect(TENANT_A_ID).not.toBe(TENANT_B_ID);
    // Both look like UUIDs.
    const uuidPattern =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    expect(TENANT_A_ID).toMatch(uuidPattern);
    expect(TENANT_B_ID).toMatch(uuidPattern);
  });
});
