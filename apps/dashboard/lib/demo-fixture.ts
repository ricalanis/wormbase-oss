/**
 * Demo fixture — deterministic ledger data for the Thursday demo.
 *
 * The dashboard's ledger client (`ledger-client.ts`) tries Postgres first; when
 * the projection tables are not yet populated (or the DB is offline in dev), it
 * falls back to this fixture. Every row carries a real-looking SHA-ish hash and
 * a Receipt — surfaces stay receipted regardless of the data path.
 *
 * Data shape mirrors `ledger-client.types.ts` and the Pydantic source-of-truth
 * in `packages/ledger/src/wormbase_ledger/entries.py`.
 *
 * The fixture deliberately seeds:
 *   - 3 people (carla-bot, ricardo-bot, alice-bot)
 *   - 2 domains (Product, Finance)
 *   - 3 sources across all 5 provenance flows (≥3 distinct flows)
 *   - 1 KPI tree with 7 nodes
 *   - 5 policies (including the 3 PRD §4.6 must-haves)
 *   - ~30 ledger entries chained by prev_hash
 *   - 6 ramp gauge values at install-day levels
 *   - ≥8 channels with talkativeness defaults
 */

import type {
  BusinessDefProposal,
  ChannelRow,
  ConversationMessage,
  DomainRow,
  InsightCard,
  KpiNodeRow,
  OntologySeed,
  PersonRow,
  PiiPattern,
  PolicyRow,
  RampGaugeRow,
  SourceRow,
  TaskRow,
  TraceEntryRow,
} from "./ledger-client.types";

/** Deterministic baseworm UUID per the cross-workstream resolution.
 *
 * Aligned with `WORMBASE_TENANT_NAMESPACE` in
 * `apps/channel-adapter/src/wormbase_channel_adapter/tenant.py` and
 * `apps/worm-core/src/wormbase_core/service.py` —
 * `uuid5(UUID("6f7c4b1d-…"), "baseworm")`. All three services derive
 * the same company_id for the baseworm slug so the dashboard can
 * read what the worm-core poller and channel-adapter write. */
export const BASEWORM_COMPANY_UUID = "a8989ece-b38a-5811-9625-327a79a65f90";

/** Stable demo timestamp anchor — Thursday demo day. */
const T0 = "2026-04-30T09:00:00Z";

const recipt = (
  hash: string,
  source: string,
  owner: string,
  classification: string
) => ({ hash, source, owner, classification });

export const RAMP_GAUGES: RampGaugeRow[] = [
  {
    axis: "ontology",
    label: "Ontology",
    value: 38,
    hint: "19 of 50 seed concepts confirmed",
    receipt: recipt(
      "a7f3c9e4d2b1",
      "ontology-seed/saas",
      "system",
      "internal"
    ),
    updatedAt: T0,
  },
  {
    axis: "schema",
    label: "Schema",
    value: 42,
    hint: "tables profiled / tables declared",
    receipt: recipt(
      "b8e02c39f4ad",
      "subscriptions × accounts",
      "ricardo-bot",
      "internal"
    ),
    updatedAt: T0,
  },
  {
    axis: "business_definitions",
    label: "Business Definitions",
    value: 31,
    hint: "tier-2 confirmations / templates",
    receipt: recipt(
      "c92f4e0a78d2",
      "onboarding · tier 2",
      "ricardo",
      "internal"
    ),
    updatedAt: T0,
  },
  {
    axis: "kpi_relational",
    label: "KPI Relational",
    value: 47,
    hint: "tree nodes resolved / leaves required",
    receipt: recipt(
      "d05ae6b4c81f",
      "kpi-tree-v1",
      "alice-bot",
      "internal"
    ),
    updatedAt: T0,
  },
  {
    axis: "conversational",
    label: "Conversational",
    value: 58,
    hint: "channel listen coverage",
    receipt: recipt(
      "e16fd47c92aa",
      "#general · #data · #ops",
      "carla-bot",
      "public"
    ),
    updatedAt: T0,
  },
  {
    axis: "operational",
    label: "Operational",
    value: 24,
    hint: "policies active / policies templated",
    receipt: recipt(
      "f238ae09b4c5",
      "policy-pack-v1",
      "system",
      "internal"
    ),
    updatedAt: T0,
  },
];

export const PEOPLE: PersonRow[] = [
  {
    personId: "p_carla",
    displayName: "carla-bot",
    email: null,
    position: null,
    status: "active",
    tenancyRole: null,
    identities: [],
    domainGrantCount: 1,
    resourceGrantCount: 2,
    roles: ["data-engineer"],
    ownedDomains: ["Product"],
    ownedResources: ["events × users", "feature_flags"],
    receipt: recipt(
      "9a4cef21",
      "people-projection",
      "carla-bot",
      "internal"
    ),
  },
  {
    personId: "p_ricardo",
    displayName: "ricardo-bot",
    email: null,
    position: null,
    status: "active",
    tenancyRole: null,
    identities: [],
    domainGrantCount: 1,
    resourceGrantCount: 3,
    roles: ["analytics-lead"],
    ownedDomains: ["Finance"],
    ownedResources: [
      "subscriptions.csv",
      "subscriptions × accounts",
      "stripe_invoices",
    ],
    receipt: recipt(
      "8b5dfa30",
      "people-projection",
      "ricardo-bot",
      "internal"
    ),
  },
  {
    personId: "p_alice",
    displayName: "alice-bot",
    email: null,
    position: null,
    status: "active",
    tenancyRole: null,
    identities: [],
    domainGrantCount: 1,
    resourceGrantCount: 1,
    roles: ["product-manager"],
    ownedDomains: ["Product"],
    ownedResources: ["onboarding_funnel"],
    receipt: recipt(
      "7c6e0b41",
      "people-projection",
      "alice-bot",
      "internal"
    ),
  },
];

export const DOMAINS: DomainRow[] = [
  {
    domainId: "d_product",
    name: "Product",
    owner: "alice-bot",
    classificationDefault: "internal",
    resourceCount: 4,
    receipt: recipt(
      "1f2a3b4c",
      "domains-projection",
      "alice-bot",
      "internal"
    ),
  },
  {
    domainId: "d_finance",
    name: "Finance",
    owner: "ricardo-bot",
    classificationDefault: "restricted",
    resourceCount: 3,
    receipt: recipt(
      "5d6e7f80",
      "domains-projection",
      "ricardo-bot",
      "restricted"
    ),
  },
];

export const SOURCES: SourceRow[] = [
  {
    sourceId: "src_subscriptions",
    uri: "snowflake://analytics.subscriptions",
    kind: "table",
    addedByPerson: "carla-bot",
    addedAt: "2026-04-23T14:02:00Z",
    addedViaFlow: "drop_and_profile",
    addedInResponseTo: "#data file drop",
    rowCount: 184_321,
    lastProfileTs: "2026-04-23T14:04:11Z",
    receipt: recipt(
      "f31abe24",
      "snowflake://analytics.subscriptions",
      "ricardo-bot",
      "internal"
    ),
  },
  {
    sourceId: "src_stripe_invoices",
    uri: "stripe://invoices",
    kind: "api",
    addedByPerson: "ricardo-bot",
    addedAt: "2026-04-24T10:11:00Z",
    addedViaFlow: "credential_offered_in_dm",
    addedInResponseTo: "DM: 'here is the stripe key'",
    rowCount: 48_201,
    lastProfileTs: "2026-04-24T10:14:42Z",
    receipt: recipt(
      "8c4def01",
      "stripe://invoices",
      "ricardo-bot",
      "restricted"
    ),
  },
  {
    sourceId: "src_events_users",
    uri: "snowflake://product.events_users",
    kind: "view",
    addedByPerson: "alice-bot",
    addedAt: "2026-04-25T16:32:00Z",
    addedViaFlow: "mentioned_in_conversation",
    addedInResponseTo: "#product 'we should look at events × users'",
    rowCount: 2_104_882,
    lastProfileTs: "2026-04-25T16:34:00Z",
    receipt: recipt(
      "2e9f0aaa",
      "snowflake://product.events_users",
      "alice-bot",
      "internal"
    ),
  },
  {
    sourceId: "src_feature_flags",
    uri: "launchdarkly://flags",
    kind: "api",
    addedByPerson: "alice-bot",
    addedAt: "2026-04-26T09:01:00Z",
    addedViaFlow: "dashboard_form",
    addedInResponseTo: null,
    rowCount: 137,
    lastProfileTs: "2026-04-26T09:02:30Z",
    receipt: recipt(
      "4ab1cc73",
      "launchdarkly://flags",
      "alice-bot",
      "internal"
    ),
  },
  {
    sourceId: "src_onboarding_funnel",
    uri: "snowflake://product.onboarding_funnel",
    kind: "view",
    addedByPerson: "carla-bot",
    addedAt: "2026-04-27T11:44:00Z",
    addedViaFlow: "kpi_gap_triggered",
    addedInResponseTo: "KPI 'activation rate' missing source",
    rowCount: 421_009,
    lastProfileTs: "2026-04-27T11:48:09Z",
    receipt: recipt(
      "6f7d2210",
      "snowflake://product.onboarding_funnel",
      "alice-bot",
      "internal"
    ),
  },
];

const KPI_LEAF = (
  id: string,
  label: string,
  owner: string,
  classification: string,
  confidence: number,
  source: string,
  hash: string
): KpiNodeRow => ({
  id,
  label,
  owner,
  classification,
  confidence,
  hasChildren: false,
  children: [],
  receipt: recipt(hash, source, owner, classification),
});

export const KPI_TREE: KpiNodeRow = {
  id: "kpi_north_star",
  label: "Net revenue retention",
  owner: "ricardo-bot",
  classification: "internal",
  confidence: 0.92,
  hasChildren: true,
  receipt: recipt("11aa22bb", "subscriptions × accounts", "ricardo-bot", "internal"),
  children: [
    {
      id: "kpi_active_subs",
      label: "Active subscriptions",
      owner: "ricardo-bot",
      classification: "internal",
      confidence: 0.88,
      hasChildren: true,
      receipt: recipt("33cc44dd", "subscriptions", "ricardo-bot", "internal"),
      children: [
        KPI_LEAF(
          "kpi_new_subs",
          "New subscriptions",
          "ricardo-bot",
          "internal",
          0.86,
          "subscriptions",
          "55ee66ff"
        ),
        KPI_LEAF(
          "kpi_churned_subs",
          "Churned subscriptions",
          "ricardo-bot",
          "internal",
          0.71,
          "subscriptions",
          "77ff8800"
        ),
      ],
    },
    {
      id: "kpi_arpu",
      label: "ARPU",
      owner: "ricardo-bot",
      classification: "restricted",
      confidence: 0.62,
      hasChildren: true,
      receipt: recipt("99001122", "stripe://invoices", "ricardo-bot", "restricted"),
      children: [
        KPI_LEAF(
          "kpi_invoice_total",
          "Invoice total · 30d",
          "ricardo-bot",
          "restricted",
          0.55,
          "stripe://invoices",
          "aabbccdd"
        ),
      ],
    },
    KPI_LEAF(
      "kpi_activation",
      "Activation rate",
      "alice-bot",
      "internal",
      0.34,
      "onboarding_funnel",
      "eeff0011"
    ),
  ],
};

export const POLICIES: PolicyRow[] = [
  {
    policyId: "pii_redaction",
    name: "PII redaction",
    plainLanguage:
      "Email and phone columns are redacted in any answer that surfaces in a public channel.",
    gateImpl: "packages/governance/src/wormbase_governance/gates/pii_redact.py",
    scope: "global",
    firesLast7d: 12,
    receipt: recipt("e1e2e3e4", "policy-pack-v1", "system", "internal"),
  },
  {
    policyId: "warmup_required",
    name: "Warmup required",
    plainLanguage:
      "The worm waits for ramp axes to cross threshold before posting unsolicited insights.",
    gateImpl: "packages/governance/src/wormbase_governance/gates/warmup.py",
    scope: "global",
    firesLast7d: 4,
    receipt: recipt("d2d3d4d5", "policy-pack-v1", "system", "internal"),
  },
  {
    policyId: "interjection_budget",
    name: "Interjection budget",
    plainLanguage:
      "At most 3 unsolicited messages per channel per day; weekly digest otherwise.",
    gateImpl:
      "packages/governance/src/wormbase_governance/gates/interjection.py",
    scope: "per-channel",
    firesLast7d: 2,
    receipt: recipt("c3c4c5c6", "policy-pack-v1", "system", "internal"),
  },
  {
    policyId: "dm_routing_v1",
    name: "DM routing allowlist",
    plainLanguage: "Only allowlisted operators may DM the worm.",
    gateImpl: "packages/governance/src/wormbase_governance/gates/dm_routing.py",
    scope: "global",
    firesLast7d: 0,
    receipt: recipt("b4b5b6b7", "policy-pack-v1", "system", "internal"),
  },
  {
    policyId: "channel_talkativeness_v1",
    name: "Channel talkativeness",
    plainLanguage:
      "Each channel has a lurker / responsive / proactive disposition.",
    gateImpl: "packages/governance/src/wormbase_governance/gates/talkativeness.py",
    scope: "per-channel",
    firesLast7d: 5,
    receipt: recipt("a5a6a7a8", "policy-pack-v1", "system", "internal"),
  },
];

export const CHANNELS: ChannelRow[] = [
  {
    channelId: "ch_general",
    name: "#general",
    talkativeness: "lurker",
    lastPolicyHash: "k1l2m3n4",
    receipt: recipt("k1l2m3n4", "channel-policy-v1", "carla-bot", "public"),
  },
  {
    channelId: "ch_data",
    name: "#data",
    talkativeness: "responsive",
    lastPolicyHash: "o5p6q7r8",
    receipt: recipt("o5p6q7r8", "channel-policy-v1", "ricardo-bot", "internal"),
  },
  {
    channelId: "ch_ops",
    name: "#ops",
    talkativeness: "responsive",
    lastPolicyHash: "s9t0u1v2",
    receipt: recipt("s9t0u1v2", "channel-policy-v1", "carla-bot", "internal"),
  },
  {
    channelId: "ch_product",
    name: "#product",
    talkativeness: "responsive",
    lastPolicyHash: "w3x4y5z6",
    receipt: recipt("w3x4y5z6", "channel-policy-v1", "alice-bot", "internal"),
  },
  {
    channelId: "ch_finance",
    name: "#finance",
    talkativeness: "lurker",
    lastPolicyHash: "1a2b3c4d",
    receipt: recipt("1a2b3c4d", "channel-policy-v1", "ricardo-bot", "restricted"),
  },
  {
    channelId: "ch_random",
    name: "#random",
    talkativeness: "lurker",
    lastPolicyHash: "5e6f7g8h",
    receipt: recipt("5e6f7g8h", "channel-policy-v1", "carla-bot", "public"),
  },
  {
    channelId: "ch_growth",
    name: "#growth",
    talkativeness: "proactive",
    lastPolicyHash: "9i0j1k2l",
    receipt: recipt("9i0j1k2l", "channel-policy-v1", "alice-bot", "internal"),
  },
  {
    channelId: "ch_eng",
    name: "#engineering",
    talkativeness: "responsive",
    lastPolicyHash: "3m4n5o6p",
    receipt: recipt("3m4n5o6p", "channel-policy-v1", "carla-bot", "internal"),
  },
];

export const TRACE_ENTRIES: TraceEntryRow[] = (() => {
  const kinds: Array<{
    kind: TraceEntryRow["kind"];
    quadrant: TraceEntryRow["quadrant"];
    summary: string;
    classification: string;
    source: string;
    owner: string;
  }> = [
    { kind: "concept_proposed", quadrant: "propose", summary: "Concept proposed: Active Account", classification: "internal", source: "ontology-seed/saas", owner: "system" },
    { kind: "concept_confirmed", quadrant: "execute", summary: "Active Account confirmed by ricardo", classification: "internal", source: "ontology-seed/saas", owner: "ricardo" },
    { kind: "source_proposed", quadrant: "propose", summary: "Source proposed: subscriptions.csv", classification: "internal", source: "subscriptions.csv", owner: "carla-bot" },
    { kind: "source_confirmed", quadrant: "execute", summary: "subscriptions.csv accepted", classification: "internal", source: "subscriptions.csv", owner: "ricardo-bot" },
    { kind: "source_connected", quadrant: "verify", summary: "Connection established to snowflake://analytics.subscriptions", classification: "internal", source: "snowflake://analytics.subscriptions", owner: "ricardo-bot" },
    { kind: "source_profiled", quadrant: "resolve", summary: "Profile complete: 184k rows, 12 cols", classification: "internal", source: "snowflake://analytics.subscriptions", owner: "ricardo-bot" },
    { kind: "policy_applied", quadrant: "execute", summary: "PII redaction enabled on email column", classification: "pii", source: "policy-pack-v1", owner: "system" },
    { kind: "kpi_proposed", quadrant: "propose", summary: "KPI proposed: ARPU under Net revenue retention", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "kpi_resolved", quadrant: "resolve", summary: "ARPU resolved at 0.62 confidence", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "domain_assigned", quadrant: "execute", summary: "@ricardo-bot assigned to Finance", classification: "internal", source: "domains", owner: "ricardo-bot" },
    { kind: "domain_assigned", quadrant: "execute", summary: "@alice-bot assigned to Product", classification: "internal", source: "domains", owner: "alice-bot" },
    { kind: "channel_message", quadrant: "verify", summary: "#data message ingested for context", classification: "public", source: "#data", owner: "carla-bot" },
    { kind: "ramp_recompute", quadrant: "resolve", summary: "Ramp recompute: schema 42%", classification: "internal", source: "ramp-projection", owner: "system" },
    { kind: "policy_applied", quadrant: "execute", summary: "Channel #data set to responsive", classification: "internal", source: "channel-policy-v1", owner: "ricardo" },
    { kind: "concept_proposed", quadrant: "propose", summary: "Concept proposed: MRR cohort", classification: "internal", source: "ontology-seed/saas", owner: "system" },
    { kind: "gate_fired", quadrant: "verify", summary: "PII gate fired on column email in #general", classification: "pii", source: "subscriptions.csv", owner: "system" },
    { kind: "source_proposed", quadrant: "propose", summary: "Source proposed: stripe://invoices", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "source_confirmed", quadrant: "execute", summary: "stripe://invoices accepted", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "source_connected", quadrant: "verify", summary: "Stripe API authenticated", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "source_profiled", quadrant: "resolve", summary: "Profile complete: 48k invoices", classification: "restricted", source: "stripe://invoices", owner: "ricardo-bot" },
    { kind: "concept_confirmed", quadrant: "execute", summary: "MRR cohort confirmed by carla", classification: "internal", source: "ontology-seed/saas", owner: "carla-bot" },
    { kind: "ramp_recompute", quadrant: "resolve", summary: "Ramp recompute: ontology 38%", classification: "internal", source: "ramp-projection", owner: "system" },
    { kind: "kpi_proposed", quadrant: "propose", summary: "KPI proposed: Activation rate", classification: "internal", source: "onboarding_funnel", owner: "alice-bot" },
    { kind: "kpi_resolved", quadrant: "resolve", summary: "Activation rate resolved at 0.34", classification: "internal", source: "onboarding_funnel", owner: "alice-bot" },
    { kind: "policy_applied", quadrant: "execute", summary: "Interjection budget set to 3/day on #general", classification: "internal", source: "channel-policy-v1", owner: "system" },
    { kind: "channel_message", quadrant: "verify", summary: "#product message: 'we should look at events × users'", classification: "public", source: "#product", owner: "alice-bot" },
    { kind: "source_proposed", quadrant: "propose", summary: "Source proposed: events × users (kpi-gap)", classification: "internal", source: "events × users", owner: "alice-bot" },
    { kind: "source_confirmed", quadrant: "execute", summary: "events × users accepted", classification: "internal", source: "events × users", owner: "alice-bot" },
    { kind: "source_connected", quadrant: "verify", summary: "events × users connected", classification: "internal", source: "events × users", owner: "alice-bot" },
    { kind: "source_profiled", quadrant: "resolve", summary: "Profile: 2.1M rows", classification: "internal", source: "events × users", owner: "alice-bot" },
    { kind: "ramp_recompute", quadrant: "resolve", summary: "Ramp recompute: kpi 47%", classification: "internal", source: "ramp-projection", owner: "system" },
  ];
  let prev: string | null = null;
  return kinds.map((k, i) => {
    const id = `e_${(i + 1).toString().padStart(4, "0")}`;
    const hash = mkHash(i);
    const ts = new Date(Date.parse(T0) - (kinds.length - i) * 60_000).toISOString();
    const entry: TraceEntryRow = {
      id,
      ts,
      kind: k.kind,
      quadrant: k.quadrant,
      hash,
      prevHash: prev,
      payload: { summary: k.summary },
      receipt: recipt(hash, k.source, k.owner, k.classification),
    };
    prev = hash;
    return entry;
  });
})();

function mkHash(i: number): string {
  const seed = (i + 1) * 16777619;
  return (seed * 0xdeadbeef).toString(16).padStart(12, "0").slice(-12);
}

export const BUSINESS_DEFS: BusinessDefProposal[] = [
  {
    term: "Active account",
    proposedDefinition:
      "An account with at least one paying subscription whose status = 'active' and last_billed_at within 35 days.",
    sourceHash: "src.subs.f31abe24",
  },
  {
    term: "Churned subscription",
    proposedDefinition:
      "A subscription whose status transitioned to 'canceled' within the last 30 days.",
    sourceHash: "src.subs.f31abe24",
  },
  {
    term: "ARPU",
    proposedDefinition:
      "Net invoice total / count(distinct active accounts) over the trailing 30 days.",
    sourceHash: "src.stripe.8c4def01",
  },
  {
    term: "Activation",
    proposedDefinition:
      "First user in an account completes onboarding step 4 within 14 days of signup.",
    sourceHash: "src.events.2e9f0aaa",
  },
];

export const ONTOLOGY_SEEDS: OntologySeed[] = [
  { concept: "Customer", aliases: ["account", "tenant"], classificationDefault: "internal", enabled: true },
  { concept: "Subscription", aliases: ["plan", "contract"], classificationDefault: "internal", enabled: true },
  { concept: "Invoice", aliases: ["bill"], classificationDefault: "restricted", enabled: true },
  { concept: "Event", aliases: ["activity"], classificationDefault: "internal", enabled: true },
  { concept: "Lead", aliases: ["prospect"], classificationDefault: "internal", enabled: false },
];

export const PII_PATTERNS: PiiPattern[] = [
  { patternId: "pii_email", label: "Email", regex: "[\\w.+-]+@[\\w-]+\\.[\\w.-]+", enabled: true },
  { patternId: "pii_phone", label: "Phone (E.164)", regex: "\\+?[1-9]\\d{6,14}", enabled: true },
  { patternId: "pii_ssn", label: "SSN", regex: "\\d{3}-\\d{2}-\\d{4}", enabled: false },
  { patternId: "pii_card", label: "Credit card", regex: "(?:\\d[ -]*?){13,19}", enabled: false },
];

export const CONVERSATIONS: ConversationMessage[] = [
  {
    ts: "2026-04-29T13:02:00Z",
    channel: "#data",
    author: "carla-bot",
    text: "I'm seeing a 12% bump in churn this week — anyone want me to dig in?",
    receipt: recipt("conv0001", "#data", "carla-bot", "public"),
  },
  {
    ts: "2026-04-29T13:04:00Z",
    channel: "#data",
    author: "ricardo-bot",
    text: "Yes — focus on the SMB tier. Worm, can you correlate with feature_flags rollout?",
    receipt: recipt("conv0002", "#data", "ricardo-bot", "internal"),
  },
  {
    ts: "2026-04-29T13:05:00Z",
    channel: "#data",
    author: "@wormbase",
    text: "Looking at subscriptions × accounts × feature_flags. I'll post a digest in 5m.",
    receipt: recipt("conv0003", "#data", "system", "internal"),
  },
  {
    ts: "2026-04-29T16:48:00Z",
    channel: "#product",
    author: "alice-bot",
    text: "We should look at events × users for activation drop-off.",
    receipt: recipt("conv0004", "#product", "alice-bot", "public"),
  },
  {
    ts: "2026-04-29T16:50:00Z",
    channel: "#product",
    author: "@wormbase",
    text: "Source proposed: events × users. Owner @alice-bot, classification internal.",
    receipt: recipt("conv0005", "#product", "system", "internal"),
  },
];

export const TASKS: TaskRow[] = [
  {
    taskId: "t_1",
    kind: "propose",
    description: "Confirm or reject proposed business def: Activation",
    due: "2026-04-30T17:00:00Z",
    receipt: recipt("task0001", "onboarding · tier 2", "ricardo", "internal"),
  },
  {
    taskId: "t_2",
    kind: "resolve",
    description: "Approve adding launchdarkly://flags as a source",
    due: null,
    receipt: recipt("task0002", "dashboard_form", "alice", "internal"),
  },
  {
    taskId: "t_3",
    kind: "propose",
    description: "Decide channel #finance talkativeness (currently lurker)",
    due: null,
    receipt: recipt("task0003", "channel-policy-v1", "ricardo", "restricted"),
  },
];

export const INSIGHTS: InsightCard[] = [
  {
    insightId: "ins_1",
    title: "Churn correlated with feature_flag 'enterprise_export'",
    summary:
      "Among accounts that were exposed to 'enterprise_export' for ≥7 days, churn dropped 38%. Suggest GA rollout.",
    kind: "process",
    receipt: recipt("ins00001", "subscriptions × feature_flags", "carla-bot", "internal"),
  },
  {
    insightId: "ins_2",
    title: "Activation funnel: step 4 is the cliff",
    summary:
      "62% of users who reach step 3 never complete step 4 within 14 days. Target onboarding redesign here.",
    kind: "kpi",
    receipt: recipt("ins00002", "onboarding_funnel", "alice-bot", "internal"),
  },
  {
    insightId: "ins_3",
    title: "Stripe invoices missing tax_id for 14% of EU accounts",
    summary:
      "Schema gap detected. The worm proposes a backfill via the stripe API; classification: restricted.",
    kind: "schema",
    receipt: recipt("ins00003", "stripe://invoices", "ricardo-bot", "restricted"),
  },
];
