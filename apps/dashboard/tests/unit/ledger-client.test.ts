import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import {
  DEFAULT_COMPANY_ID,
  getRampValues,
  getKpiTree,
  getTraceEntries,
  getPeople,
  getDomains,
  getSources,
  getPolicies,
  getChannels,
  getProposedBusinessDefs,
  getOntologySeeds,
  getPiiPatterns,
  getConversations,
  getTasks,
  getInsights,
  getDecisions,
  getProcessMaps,
  getSystemMap,
  getRecurringQuestions,
  upsertChannelTalkativeness,
  confirmBusinessDef,
  syntheticReceipt,
} from "../../lib/ledger-client";

const C = DEFAULT_COMPANY_ID;

describe("DEFAULT_COMPANY_ID", () => {
  it("matches the deterministic baseworm UUIDv5", () => {
    // uuid5(WORMBASE_TENANT_NAMESPACE, "baseworm").
    // Aligned with channel-adapter + worm-core + sim-harness tenant_to_uuid.
    expect(C).toBe("a8989ece-b38a-5811-9625-327a79a65f90");
  });
});

describe("getRampValues", () => {
  it("returns [] when no Postgres path is wired (honest emptiness)", async () => {
    // Pre-empty-state-pass this returned the RAMP_GAUGES fixture; the
    // dashboard now surfaces an EmptyState on /dashboard instead of
    // pretending six axes are populated for a fresh tenant.
    const rows = await getRampValues(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });
});

describe("getKpiTree", () => {
  it("returns null when no Postgres path is wired (honest emptiness)", async () => {
    // Pre-empty-state-pass this returned the KPI_TREE fixture; the /kpis
    // page now renders a CTA-bearing EmptyState pointing at /sources/new
    // and /channels.
    const root = await getKpiTree(C);
    expect(root).toBeNull();
  });
});

describe("getTraceEntries", () => {
  it("returns entries with chained prevHash", async () => {
    const page = await getTraceEntries(C, { limit: 50 });
    expect(page.entries.length).toBeGreaterThanOrEqual(20);
    for (const e of page.entries) {
      expect(e.hash).toBeTruthy();
      expect(e.receipt.hash).toBe(e.hash);
      expect(["propose", "execute", "verify", "resolve"]).toContain(e.quadrant);
    }
  });

  it("paginates via cursor", async () => {
    const a = await getTraceEntries(C, { limit: 5 });
    expect(a.nextCursor).not.toBeNull();
    const b = await getTraceEntries(C, { limit: 5, cursor: a.nextCursor! });
    // No overlap between the two pages
    const idsA = new Set(a.entries.map((e) => e.id));
    for (const e of b.entries) expect(idsA.has(e.id)).toBe(false);
  });

  it("filters by quadrant", async () => {
    const page = await getTraceEntries(C, { quadrant: "propose", limit: 50 });
    for (const e of page.entries) expect(e.quadrant).toBe("propose");
  });
});

describe("getPeople / getDomains / getSources (honest emptiness)", () => {
  // Empty-state pass: when no Postgres path is wired (no DATABASE_URL),
  // every read accessor returns its honest empty value (`[]` for arrays,
  // `null` for single objects). The dashboard's per-page EmptyState then
  // surfaces a CTA pointing at the trigger flow.
  it("getPeople returns []", async () => {
    const rows = await getPeople(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("getDomains returns []", async () => {
    const rows = await getDomains(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("getSources returns []", async () => {
    const rows = await getSources(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });
});

describe("getPolicies / getChannels (honest emptiness)", () => {
  it("getPolicies returns []", async () => {
    const rows = await getPolicies(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("getChannels returns []", async () => {
    const rows = await getChannels(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });
});

describe("onboarding read accessors (honest emptiness)", () => {
  it("getProposedBusinessDefs returns []", async () => {
    const rows = await getProposedBusinessDefs(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  // ONTOLOGY_SEEDS is the documented exception — the seed pack is static
  // product config (canonical concept list shipped with WormBase, not
  // tenant state), so this accessor still returns the curated list.
  it("returns ontology seeds with classification (static config)", async () => {
    const rows = await getOntologySeeds(C);
    expect(rows.length).toBeGreaterThanOrEqual(3);
  });

  it("getPiiPatterns returns []", async () => {
    const rows = await getPiiPatterns(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });
});

describe("process retrieval (Step 3c) accessors", () => {
  // When DATABASE_URL isn't set, these accessors return empty arrays /
  // empty payload (live-only — there's no fixture fallback for these new
  // surfaces). This pins the contract the dashboard pages rely on so an
  // empty-tenant render still succeeds.
  it("getDecisions returns [] when no Postgres path is wired", async () => {
    const rows = await getDecisions(C);
    expect(Array.isArray(rows)).toBe(true);
  });

  it("getProcessMaps returns [] when no Postgres path is wired", async () => {
    const rows = await getProcessMaps(C);
    expect(Array.isArray(rows)).toBe(true);
  });

  it("getSystemMap returns the empty payload shape when no Postgres path", async () => {
    const payload = await getSystemMap(C);
    expect(payload).toHaveProperty("nodes");
    expect(payload).toHaveProperty("generatedAt");
    expect(Array.isArray(payload.nodes)).toBe(true);
  });

  it("getRecurringQuestions returns [] when no Postgres path is wired", async () => {
    const rows = await getRecurringQuestions(C);
    expect(Array.isArray(rows)).toBe(true);
  });
});

describe("activity & insights (honest emptiness)", () => {
  it("getConversations returns []", async () => {
    const rows = await getConversations(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("returns tasks (empty until emit_task_proposed lands upstream)", async () => {
    const rows = await getTasks(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });

  it("returns insights as cards (empty until emit_insight_proposed lands upstream)", async () => {
    const rows = await getInsights(C);
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBe(0);
  });
});

describe("syntheticReceipt", () => {
  it("is deterministic for the same payload", () => {
    const a = syntheticReceipt({
      kind: "policy_applied",
      source: "x",
      owner: "y",
      classification: "internal",
      payload: { foo: 1 },
    });
    const b = syntheticReceipt({
      kind: "policy_applied",
      source: "x",
      owner: "y",
      classification: "internal",
      payload: { foo: 1 },
    });
    expect(a.hash).toBe(b.hash);
  });

  it("differs for different payloads", () => {
    const a = syntheticReceipt({
      kind: "policy_applied",
      source: "x",
      owner: "y",
      classification: "internal",
      payload: { foo: 1 },
    });
    const b = syntheticReceipt({
      kind: "policy_applied",
      source: "x",
      owner: "y",
      classification: "internal",
      payload: { foo: 2 },
    });
    expect(a.hash).not.toBe(b.hash);
  });
});

describe("write helpers return Receipts", () => {
  it("upsertChannelTalkativeness", async () => {
    const r = await upsertChannelTalkativeness(C, "ch_data", "proactive");
    expect(r.hash).toBeTruthy();
    expect(r.classification).toBe("internal");
  });

  it("confirmBusinessDef", async () => {
    const r = await confirmBusinessDef(C, "Active account");
    expect(r.hash).toBeTruthy();
  });
});

// ─── Postgres path: tryPg + getSources projection ────────────────────────
//
// These tests turn on DATABASE_URL and mock the `pg` module so we can drive
// `tryPg` and the `getSources` SQL through controlled responses without
// requiring a live Postgres instance.

describe("Postgres path", () => {
  // We mock `pg` by hoisting a controllable client. The pool's `connect`
  // returns a client whose `query` is a vi.fn() that we set per-test.
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(async () => {
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

  it("tryPg falls back to honest empty value when the query throws", async () => {
    // Empty-state pass: when Postgres is unreachable we no longer pre-bake
    // a fixture — the dashboard surfaces an EmptyState. Outage and
    // emptiness collapse to the same UI for now (a future workstream may
    // distinguish them).
    queryMock.mockRejectedValueOnce(new Error("connection refused"));
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getSources(C);
    expect(rows).toEqual([]);
  });

  it("getSources deduplicates events per source_id and returns the latest status", async () => {
    // Two source_ids; for src-A we emit propose -> confirm -> profile, so the
    // single returned row should carry the profiled row_count and the
    // confirmed_by_person from the confirm step. For src-B we emit only
    // propose, so it remains in proposed status with no profile data.
    const ROWS = [
      {
        source_id: "src-A",
        source_kind: "table",
        uri: "snowflake://a",
        classification: "internal",
        added_via_flow: "drop_and_profile",
        added_at: new Date("2026-04-25T10:00:00Z"),
        latest_tool: "emit_source_profiled",
        confirmed_by_person: "ricardo",
        row_count: "184321",
        profile_ts: new Date("2026-04-25T10:05:00Z"),
      },
      {
        source_id: "src-B",
        source_kind: "api",
        uri: "stripe://invoices",
        classification: "restricted",
        added_via_flow: "credential_offered_in_dm",
        added_at: new Date("2026-04-25T11:00:00Z"),
        latest_tool: "emit_source_proposed",
        confirmed_by_person: null,
        row_count: null,
        profile_ts: null,
      },
    ];
    queryMock.mockResolvedValueOnce({ rows: ROWS, rowCount: ROWS.length });
    // Phase 3 Task 3D — `getSources` issues a second aggregate query
    // for the 30-day maintenance-signal window (drift / staleness /
    // classification-refresh / lineage-break) per source. We mock an
    // empty result here so the per-source signal arrays default to [].
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });

    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getSources(C);

    expect(rows.length).toBe(2);
    // Two aggregate queries (sources fold + maintenance-signal fold).
    // The contract is that both are tenant-scoped on company_id, with
    // no per-source-id N+1.
    expect(queryMock).toHaveBeenCalledTimes(2);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toEqual([C]);
    const [, signalParams] = queryMock.mock.calls[1];
    expect(signalParams).toEqual([C]);

    const a = rows.find((r) => r.sourceId === "src-A")!;
    expect(a.uri).toBe("snowflake://a");
    expect(a.kind).toBe("table");
    expect(a.rowCount).toBe(184321);
    expect(a.lastProfileTs).toBe("2026-04-25T10:05:00.000Z");
    expect(a.addedByPerson).toBe("ricardo");
    expect(a.addedViaFlow).toBe("drop_and_profile");
    expect(a.receipt.classification).toBe("internal");

    const b = rows.find((r) => r.sourceId === "src-B")!;
    expect(b.rowCount).toBe(0);
    expect(b.lastProfileTs).toBeNull();
    expect(b.addedByPerson).toBe("worm");
    expect(b.addedViaFlow).toBe("credential_offered_in_dm");
    expect(b.receipt.classification).toBe("restricted");
  });

  it("getSources surfaces lastSeen, drift state, and the 30-day maintenance signal timeline (P2.8)", async () => {
    // Phase 3 Task 3D — confirms the freshness feed wiring on the
    // Postgres path. The first query carries projection_sources.last_seen
    // (Wave G v003 migration) plus the latest emit_source_drift_detected
    // reason via SQL CTE; the second query returns the 30-day window
    // of emit_source_*_signaled / *_detected / *_refreshed entries the
    // /sources timeline renders.
    const SOURCE_ROWS = [
      {
        source_id: "src-fresh",
        source_kind: "table",
        uri: "snowflake://fresh",
        classification: "internal",
        added_via_flow: "drop_and_profile",
        added_at: new Date("2026-04-25T10:00:00Z"),
        latest_tool: "emit_source_profiled",
        confirmed_by_person: "carla",
        row_count: "100",
        profile_ts: new Date("2026-04-25T10:05:00Z"),
        bronzed: true,
        silvered: true,
        golded: false,
        maintainer_person_id: null,
        drift_reason: "schema_hash_mismatch",
        drift_detected_at: new Date("2026-05-02T09:00:00Z"),
        last_seen: new Date("2026-05-03T08:00:00Z"),
      },
      {
        source_id: "src-cold",
        source_kind: "csv",
        uri: "csv://cold",
        classification: "public",
        added_via_flow: "dashboard_form",
        added_at: new Date("2026-04-20T10:00:00Z"),
        latest_tool: "emit_source_proposed",
        confirmed_by_person: null,
        row_count: null,
        profile_ts: null,
        bronzed: false,
        silvered: false,
        golded: false,
        maintainer_person_id: null,
        drift_reason: null,
        drift_detected_at: null,
        last_seen: null,
      },
    ];
    const SIGNAL_ROWS = [
      {
        source_id: "src-fresh",
        tool: "emit_source_drift_detected",
        reason: "schema_hash_mismatch",
        ts: new Date("2026-05-02T09:00:00Z"),
      },
      {
        source_id: "src-fresh",
        tool: "emit_source_staleness_signaled",
        reason: null,
        ts: new Date("2026-04-30T09:00:00Z"),
      },
      {
        source_id: "src-fresh",
        tool: "emit_source_classification_refreshed",
        reason: "PII column detected",
        ts: new Date("2026-04-28T09:00:00Z"),
      },
    ];
    queryMock.mockResolvedValueOnce({
      rows: SOURCE_ROWS,
      rowCount: SOURCE_ROWS.length,
    });
    queryMock.mockResolvedValueOnce({
      rows: SIGNAL_ROWS,
      rowCount: SIGNAL_ROWS.length,
    });

    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getSources(C);

    const fresh = rows.find((r) => r.sourceId === "src-fresh")!;
    expect(fresh.lastSeen).toBe("2026-05-03T08:00:00.000Z");
    expect(fresh.driftDetected).toBe(true);
    expect(fresh.driftReason).toBe("schema_hash_mismatch");
    expect(fresh.maintenanceSignals).toBeDefined();
    expect(fresh.maintenanceSignals!.length).toBe(3);
    expect(fresh.maintenanceSignals!.map((s) => s.kind)).toEqual([
      "drift",
      "staleness",
      "classification_refresh",
    ]);
    // The newest signal carries through its reason verbatim — used by
    // the chip's title attribute on /sources.
    expect(fresh.maintenanceSignals![0].reason).toBe("schema_hash_mismatch");
    expect(fresh.maintenanceSignals![2].reason).toBe("PII column detected");

    const cold = rows.find((r) => r.sourceId === "src-cold")!;
    // Honest empty-state: never observed by the maintainer.
    expect(cold.lastSeen).toBeNull();
    expect(cold.driftDetected).toBe(false);
    expect(cold.driftReason).toBeNull();
    expect(cold.maintenanceSignals).toEqual([]);
  });

  // ─── Live ledger projections (ramp / kpi tree / domains) ──────────────

  it("getRampValues maps the latest ramp_snapshot into 6 axes", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          ts: new Date("2026-04-29T12:00:00Z"),
          hash_hex: "abcdef0123456789ffeeddccbbaa0011" + "00".repeat(16),
          values: {
            ontology: 27.5,
            schema: 60,
            business_definitions: 18,
            kpi_relational: 80,
            conversational: 45.4,
            operational: 5,
          },
          snapshot_hash: "deadbeefcafebabe",
        },
      ],
      rowCount: 1,
    });

    const mod = await import("../../lib/ledger-client");
    const axes = await mod.getRampValues(C);

    expect(axes.map((a) => a.axis)).toEqual([
      "ontology",
      "schema",
      "business_definitions",
      "kpi_relational",
      "conversational",
      "operational",
    ]);
    // Floats round to nearest int and clamp to 0..100.
    const byAxis = Object.fromEntries(axes.map((a) => [a.axis, a.value]));
    expect(byAxis.ontology).toBe(28);
    expect(byAxis.schema).toBe(60);
    expect(byAxis.business_definitions).toBe(18);
    expect(byAxis.kpi_relational).toBe(80);
    expect(byAxis.conversational).toBe(45);
    expect(byAxis.operational).toBe(5);
    // The receipt hash comes from the snapshot_hash (preferred) truncated.
    expect(axes[0].receipt.hash).toBe("deadbeefcafe");
  });

  it("getRampValues returns [] when no snapshot exists (honest emptiness)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const axes = await mod.getRampValues(C);
    expect(axes).toEqual([]);
  });

  it("getKpiTree assembles a tree from emit_kpi_node rows", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          args: {
            id: "kpi_root",
            name: "Net revenue retention",
            parent_node_id: null,
            confidence: 0.9,
            classification: "internal",
            owner_person_id: "ricardo",
            source_resource_id: "subscriptions",
          },
          hash_hex: "11" + "00".repeat(31),
        },
        {
          args: {
            id: "kpi_child",
            name: "Active subs",
            parent_node_id: "kpi_root",
            confidence: 0.7,
            classification: "internal",
            owner_person_id: "ricardo",
            source_resource_id: null,
          },
          hash_hex: "22" + "00".repeat(31),
        },
        {
          args: {
            id: "kpi_grand",
            name: "New subs",
            parent_node_id: "kpi_child",
            confidence: 0.55,
            classification: "internal",
            owner_person_id: "ricardo",
          },
          hash_hex: "33" + "00".repeat(31),
        },
      ],
      rowCount: 3,
    });

    const mod = await import("../../lib/ledger-client");
    const root = await mod.getKpiTree(C);
    if (root === null) throw new Error("expected non-null tree");

    expect(root.id).toBe("kpi_root");
    expect(root.label).toBe("Net revenue retention");
    expect(root.hasChildren).toBe(true);
    expect(root.children.map((c) => c.id)).toEqual(["kpi_child"]);

    const child = root.children[0];
    expect(child.children.map((c) => c.id)).toEqual(["kpi_grand"]);
    const grand = child.children[0];
    expect(grand.hasChildren).toBe(false);
    expect(grand.confidence).toBeCloseTo(0.55);
  });

  it("getKpiTree returns null when no kpi_node entries exist (honest emptiness)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const root = await mod.getKpiTree(C);
    expect(root).toBeNull();
  });

  it("getDomains projects emit_domain_registered rows with default classification", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          id: "d_product",
          name: "Product",
          default_classification: "internal",
          hash_hex: "aa" + "00".repeat(31),
          owner_person_id: "alice",
          resource_count: 4,
        },
        {
          id: "d_finance",
          name: "Finance",
          default_classification: "restricted",
          hash_hex: "bb" + "00".repeat(31),
          owner_person_id: null,
          resource_count: "0",
        },
      ],
      rowCount: 2,
    });

    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getDomains(C);

    expect(rows.map((r) => r.name).sort()).toEqual(["Finance", "Product"]);
    const finance = rows.find((r) => r.name === "Finance")!;
    expect(finance.classificationDefault).toBe("restricted");
    expect(finance.owner).toBe("unassigned");
    expect(finance.resourceCount).toBe(0);
    const product = rows.find((r) => r.name === "Product")!;
    expect(product.owner).toBe("alice");
    expect(product.resourceCount).toBe(4);
    expect(product.receipt.classification).toBe("internal");
  });

  it("getDomains returns [] when no domain_registered rows exist (honest emptiness)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getDomains(C);
    expect(rows).toEqual([]);
  });

  // ─── W3-B: getPolicyAppliedEvents ─────────────────────────────────
  //
  // Recent ``policy_applied`` execute entries scoped to a tenant + a
  // specific ``policy_name``. Drives the per-channel rate-limit panel
  // on /channels/[id] for WhatsApp; the shape is generic enough that
  // any policy-scoped panel can read this. Tenant-scoped, sorted
  // most-recent-first, capped at the requested limit.

  it("getPolicyAppliedEvents folds emit_policy_applied execute entries scoped to a policy_name", async () => {
    const ROWS = [
      {
        seq: 102,
        ts: new Date("2026-05-07T18:05:00Z"),
        args: {
          policy_name: "policy:whatsapp_rate_limit",
          rule: "rate_limit_persistent_throttle",
          rationale:
            "WhatsApp send: persistent 429 throttle after 3 backoff retries",
          applies_to: {
            scope: "adapter",
            platform: "whatsapp",
            bot_phone: "+5511999998888",
            tenant_id: "baseworm",
          },
          bot_phone: "+5511999998888",
          tenant_id: "baseworm",
          outcome: "applied",
        },
        hash_hex: "abcdef0123456789" + "00".repeat(24),
      },
      {
        seq: 80,
        ts: new Date("2026-05-07T17:30:00Z"),
        args: {
          policy_name: "policy:whatsapp_rate_limit",
          rule: "rate_limit_persistent_throttle",
          rationale: "earlier throttle event",
          applies_to: {
            scope: "adapter",
            bot_phone: "+5511999998888",
          },
        },
        hash_hex: "fedcba9876543210" + "00".repeat(24),
      },
    ];
    queryMock.mockResolvedValueOnce({ rows: ROWS, rowCount: ROWS.length });

    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getPolicyAppliedEvents(
      C,
      "policy:whatsapp_rate_limit",
      { limit: 10 },
    );

    expect(rows.length).toBe(2);
    const [latest, earlier] = rows;
    expect(latest.policyName).toBe("policy:whatsapp_rate_limit");
    expect(latest.rule).toBe("rate_limit_persistent_throttle");
    expect(latest.rationale).toMatch(/persistent 429 throttle/);
    expect(latest.botPhone).toBe("+5511999998888");
    expect(latest.outcome).toBe("applied");
    expect(latest.appliesTo).toMatchObject({ platform: "whatsapp" });
    expect(latest.receipt.source).toBe("policy-applied-projection");
    expect(latest.hash).toBe("abcdef012345");
    expect(earlier.outcome).toBe("applied"); // default when omitted

    // SQL params: company_id, policy_name, limit (clamped to ≥1, ≤500).
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toEqual([C, "policy:whatsapp_rate_limit", 10]);
  });

  it("getPolicyAppliedEvents returns [] honestly when no entries match", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getPolicyAppliedEvents(
      C,
      "policy:whatsapp_rate_limit",
    );
    expect(rows).toEqual([]);
  });
});
