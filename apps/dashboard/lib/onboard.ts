/**
 * Onboarding Sub-wave B (2026-05-30) — server-side accessors for the
 * unified ``/onboard`` route.
 *
 * Each tab on ``/onboard`` reads a small read-only summary plus the
 * rows it renders. The accessors here are thin composition over the
 * existing ledger-client accessors (``getInstalls``, ``getSources``,
 * ``getDomains``, ``getPeople``, ``getPolicies``, ``getConnectorCatalog``)
 * and the ``platform-status`` / ``lake-surfaces-catalog`` static
 * descriptors.
 *
 * This module deliberately does NOT add new entry kinds, projection
 * tables, or worm-core endpoints. Sub-wave C will graduate the
 * pack-picker writes; Sub-wave D will wire connector probes. Everything
 * here renders against what already lands.
 *
 * Status conventions across the institutional ontology:
 *
 *   * Channel adapter   → mirrors ``platform-status.PLATFORMS``:
 *                          production / preview / coming_soon
 *   * Data source       → mirrors ``lake-surfaces-catalog.CONNECTOR_CATALOG``:
 *                          production / preview / coming_soon
 *   * Domain            → packs not yet seeded → "unknown" (Sub-wave C
 *                          populates the pack registry)
 *   * Person            → "production" once the Person is confirmed,
 *                          "preview" while proposed
 *   * Policy            → "production" when the gate_impl is wired and
 *                          a fire history exists; "preview" when the
 *                          gate is declared but unfired in the last 7d
 *   * Agent / Subscription → navigation-only stubs — accessors return
 *                          existence counts only.
 */

import {
  getDomains,
  getInstalls,
  getPeople,
  getPolicies,
  getSources,
} from "./ledger-client";
import type {
  DomainRow,
  InstallRow,
  PersonRow,
  PolicyRow,
  SourceRow,
} from "./ledger-client.types";
import { getConnectorCatalog } from "./connectors";
import type { ConnectorCatalog, ConnectorCatalogRow } from "./connectors";
import { PLATFORMS, type PlatformDescriptor } from "./platform-status";

// ─── Tab summary types ─────────────────────────────────────────────────────

export interface OnboardTabSummary {
  /** Tab id used in the path (``chat`` / ``source`` / …). */
  tab: string;
  /** User-facing label. */
  label: string;
  /** Total rows visible on the tab. */
  total: number;
  /** Rows considered "ready" (production-connected / confirmed). */
  ready: number;
  /** Rows still pending action (preview, proposed, coming_soon). */
  pending: number;
  /** Honest one-liner — names the next action the operator can take. */
  hint: string;
}

export interface OnboardLandingSnapshot {
  tabs: OnboardTabSummary[];
}

// ─── /onboard/chat ─────────────────────────────────────────────────────────

export interface OnboardChatRow {
  platform: string;
  label: string;
  status: PlatformDescriptor["status"];
  statusNote: string;
  capabilities: string[];
  envHint: string | null;
  /** True iff at least one active install exists for this platform. */
  connected: boolean;
  /** Active installs of this platform, when ``connected``. */
  installCount: number;
}

export interface OnboardChatView {
  rows: OnboardChatRow[];
  installs: InstallRow[];
}

export async function getOnboardChat(
  companyId: string,
): Promise<OnboardChatView> {
  const installs = await getInstalls(companyId).catch(() => [] as InstallRow[]);
  const byPlatform = new Map<string, number>();
  for (const i of installs) {
    if (i.status === "active") {
      byPlatform.set(i.platform, (byPlatform.get(i.platform) ?? 0) + 1);
    }
  }
  const rows: OnboardChatRow[] = PLATFORMS.map((p) => ({
    platform: p.platform,
    label: p.label,
    status: p.status,
    statusNote: p.statusNote,
    capabilities: p.capabilities ?? [],
    envHint: p.envHint ?? null,
    connected: (byPlatform.get(p.platform) ?? 0) > 0,
    installCount: byPlatform.get(p.platform) ?? 0,
  }));
  return { rows, installs };
}

// ─── /onboard/source ───────────────────────────────────────────────────────

export interface OnboardSourceView {
  catalog: ConnectorCatalog;
  sources: SourceRow[];
}

export async function getOnboardSource(
  companyId: string,
): Promise<OnboardSourceView> {
  const [catalog, sources] = await Promise.all([
    getConnectorCatalog(companyId).catch(() => ({
      production: [] as ConnectorCatalogRow[],
      preview: [] as ConnectorCatalogRow[],
      comingSoon: [] as ConnectorCatalogRow[],
      registryUnreachable: true,
      registryError: "accessor threw",
      upstreamUrl: "",
    })),
    getSources(companyId).catch(() => [] as SourceRow[]),
  ]);
  return { catalog, sources };
}

// ─── /onboard/domain ───────────────────────────────────────────────────────

/**
 * Domain pack descriptor — Sub-wave C (2026-05-30).
 *
 * The 4 packs (generic / saas / marketplace / fintech) ship as YAML
 * in ``apps/worm-core/src/wormbase_core/onboarding/packs/``. The
 * dashboard mirrors the surface contract statically here (label,
 * description, domain count, pack version) so the picker stays
 * deterministic + zero-round-trip on every render.
 *
 * Future packs land by extending this constant in lockstep with the
 * server-side YAML drop — the bundle is small enough that drift
 * detection ships as a server-action contract test, not a runtime
 * fetch.
 */
export interface DomainPackDescriptor {
  packId: string;
  packVersion: string;
  label: string;
  description: string;
  domainCount: number;
}

const DOMAIN_PACK_CATALOG: readonly DomainPackDescriptor[] = [
  {
    packId: "generic",
    packVersion: "v1.0",
    label: "Generic Org",
    description:
      "Minimal pack for orgs without a clear vertical match. One general domain plus conservative retention + PII defaults.",
    domainCount: 1,
  },
  {
    packId: "saas",
    packVersion: "v1.0",
    label: "SaaS",
    description:
      "B2B SaaS pack: product, growth, finance, support. Adds payment classification + per-domain owner role hints.",
    domainCount: 4,
  },
  {
    packId: "marketplace",
    packVersion: "v1.0",
    label: "Marketplace",
    description:
      "Two-sided marketplace pack: buyer, seller, ops, trust-safety, finance. Splits transactional vs identity vs financial data classification.",
    domainCount: 5,
  },
  {
    packId: "fintech",
    packVersion: "v1.0",
    label: "Fintech",
    description:
      "Regulated fintech pack: ledger, treasury, compliance, customer. Strict regulated classifications + masking + access policies pre-seeded for SOC-2 / PCI / KYC baseline.",
    domainCount: 4,
  },
];

export interface OnboardDomainView {
  packs: DomainPackDescriptor[];
  domains: DomainRow[];
  packsAvailable: boolean;
}

export async function getOnboardDomain(
  companyId: string,
): Promise<OnboardDomainView> {
  const domains = await getDomains(companyId).catch(() => [] as DomainRow[]);
  return {
    packs: [...DOMAIN_PACK_CATALOG],
    domains,
    packsAvailable: true,
  };
}

// ─── /onboard/person ───────────────────────────────────────────────────────

export interface OnboardPersonView {
  people: PersonRow[];
  proposedCount: number;
  confirmedCount: number;
}

export async function getOnboardPerson(
  companyId: string,
): Promise<OnboardPersonView> {
  const people = await getPeople(companyId).catch(() => [] as PersonRow[]);
  let proposedCount = 0;
  let confirmedCount = 0;
  for (const p of people) {
    if (p.status === "active") confirmedCount += 1;
    else if (p.status === "proposed") proposedCount += 1;
  }
  return { people, proposedCount, confirmedCount };
}

// ─── /onboard/policy ───────────────────────────────────────────────────────

export interface OnboardPolicyView {
  policies: PolicyRow[];
  firedRecently: number;
}

export async function getOnboardPolicy(
  companyId: string,
): Promise<OnboardPolicyView> {
  const policies = await getPolicies(companyId).catch(() => [] as PolicyRow[]);
  let firedRecently = 0;
  for (const p of policies) {
    if (p.firesLast7d > 0) firedRecently += 1;
  }
  return { policies, firedRecently };
}

// ─── Landing snapshot ──────────────────────────────────────────────────────

/**
 * Aggregate snapshot driving the ``/onboard`` landing tab navigation.
 *
 * The snapshot calls every per-tab accessor and folds the result into a
 * single per-tab summary card with ``ready/pending/total`` counts and an
 * honest hint line. Cheap enough to compute on every page render — each
 * accessor is a single Postgres fold or static descriptor read.
 */
export async function getOnboardLandingSnapshot(
  companyId: string,
): Promise<OnboardLandingSnapshot> {
  const [chat, source, domain, person, policy] = await Promise.all([
    getOnboardChat(companyId),
    getOnboardSource(companyId),
    getOnboardDomain(companyId),
    getOnboardPerson(companyId),
    getOnboardPolicy(companyId),
  ]);

  const chatReady = chat.rows.filter((r) => r.connected).length;
  const chatPending = chat.rows.filter(
    (r) => !r.connected && r.status !== "coming_soon",
  ).length;

  const productionSources =
    source.catalog.production.length + source.catalog.preview.length;
  const connectedSources = source.sources.length;

  const tabs: OnboardTabSummary[] = [
    {
      tab: "chat",
      label: "Chat",
      total: chat.rows.length,
      ready: chatReady,
      pending: chatPending,
      hint:
        chatReady === 0
          ? "Connect your first chat platform to start ingesting conversation."
          : `${chatReady} of ${chat.rows.length} platforms connected.`,
    },
    {
      tab: "source",
      label: "Source",
      total: productionSources,
      ready: connectedSources,
      pending: Math.max(0, productionSources - connectedSources),
      hint:
        connectedSources === 0
          ? "No data sources yet. Connect one or drop a file in a worm-watched channel."
          : `${connectedSources} active source${connectedSources === 1 ? "" : "s"}.`,
    },
    {
      tab: "domain",
      label: "Domain",
      total: domain.domains.length,
      ready: domain.domains.filter((d) => d.owner !== "unassigned").length,
      pending: domain.domains.filter((d) => d.owner === "unassigned").length,
      hint: domain.packsAvailable
        ? `${domain.packs.length} domain pack${domain.packs.length === 1 ? "" : "s"} available — pick one to seed the governance baseline.`
        : "Pack catalog unavailable — worm-core bundle may be missing packs/.",
    },
    {
      tab: "person",
      label: "Person",
      total: person.people.length,
      ready: person.confirmedCount,
      pending: person.proposedCount,
      hint:
        person.proposedCount === 0
          ? `${person.confirmedCount} confirmed Person${person.confirmedCount === 1 ? "" : "s"}.`
          : `${person.proposedCount} proposed identity-link${person.proposedCount === 1 ? "" : "s"} await admin confirmation.`,
    },
    {
      tab: "policy",
      label: "Policy",
      total: policy.policies.length,
      ready: policy.firedRecently,
      pending: Math.max(0, policy.policies.length - policy.firedRecently),
      hint:
        policy.policies.length === 0
          ? "No policies registered yet. Pack-seeded policies land in Sub-wave C."
          : `${policy.firedRecently} policies fired in the last 7 days.`,
    },
    {
      tab: "agent",
      label: "Agent",
      total: 0,
      ready: 0,
      pending: 0,
      hint: "Use the existing /people/agents/new flow to register an agent.",
    },
    {
      tab: "subscription",
      label: "Subscription",
      total: 0,
      ready: 0,
      pending: 0,
      hint: "Subscriptions are managed on each agent's detail page.",
    },
  ];

  return { tabs };
}

// ─── /status + /logs accessors ─────────────────────────────────────────────

export type StatusKind =
  | "connector"
  | "channel"
  | "domain"
  | "person"
  | "policy"
  | "agent"
  | "subscription";

export type StatusState =
  | "works"
  | "degraded"
  | "failed"
  | "unknown";

export interface ObjectStatus {
  kind: StatusKind;
  objectId: string;
  state: StatusState;
  /** Human-facing line explaining why the state is what it is. */
  summary: string;
  /** Optional recovery hint when state ∈ {degraded, failed}. */
  recoveryHint: string | null;
  /** Capabilities declared by the object (when available). */
  capabilities: string[];
  /** Optional label resolved from existing accessors — render-friendly. */
  label: string;
  /** Whether probes are wired for this kind (Sub-wave D for connectors;
   *  the rest stay ledger-derived for now). */
  probeImplemented: boolean;
}

const KIND_LABELS: Record<StatusKind, string> = {
  connector: "Data source",
  channel: "Channel adapter",
  domain: "Domain",
  person: "Person",
  policy: "Policy",
  agent: "Agent",
  subscription: "Subscription",
};

export function isStatusKind(value: string): value is StatusKind {
  return value in KIND_LABELS;
}

/**
 * Build an ``ObjectStatus`` for the given (kind, id) by reading the
 * existing ledger projections. No real probe calls in this sub-wave —
 * Sub-wave D wires those for connectors. Until then, status state is
 * derived from "what does the projection say about this object's
 * current shape": confirmed/active → ``works``; revoked / failed-write
 * → ``failed``; nothing observed → ``unknown``.
 */
export async function getObjectStatus(
  companyId: string,
  kind: StatusKind,
  objectId: string,
): Promise<ObjectStatus> {
  switch (kind) {
    case "channel":
      return statusForChannel(companyId, objectId);
    case "connector":
      return statusForConnector(companyId, objectId);
    case "domain":
      return statusForDomain(companyId, objectId);
    case "person":
      return statusForPerson(companyId, objectId);
    case "policy":
      return statusForPolicy(companyId, objectId);
    case "agent":
    case "subscription":
      return {
        kind,
        objectId,
        state: "unknown",
        summary:
          "Status probe not yet wired for this object kind — managed via the existing /people/agents surface.",
        recoveryHint:
          "Visit /people/agents to see the live agent registry and per-agent audit.",
        capabilities: [],
        label: KIND_LABELS[kind],
        probeImplemented: false,
      };
  }
}

async function statusForChannel(
  companyId: string,
  installId: string,
): Promise<ObjectStatus> {
  const installs = await getInstalls(companyId).catch(
    () => [] as InstallRow[],
  );
  const row = installs.find((i) => i.installId === installId);
  if (!row) {
    return {
      kind: "channel",
      objectId: installId,
      state: "unknown",
      summary: `No install found for id ${installId}.`,
      recoveryHint:
        "Verify the install id against /channels. Installs land as emit_install_completed entries.",
      capabilities: [],
      label: KIND_LABELS.channel,
      probeImplemented: false,
    };
  }
  const desc = PLATFORMS.find((p) => p.platform === row.platform);
  const capabilities = desc?.capabilities ?? [];
  if (row.status === "revoked") {
    return {
      kind: "channel",
      objectId: installId,
      state: "failed",
      summary: `${row.platform} install was revoked.`,
      recoveryHint:
        "Re-run the OAuth flow on /channels to reinstate the install.",
      capabilities,
      label: `${KIND_LABELS.channel} · ${row.platform}`,
      probeImplemented: false,
    };
  }
  return {
    kind: "channel",
    objectId: installId,
    state: "works",
    summary: `${row.platform} install is active${row.installerName ? `, installed by ${row.installerName}` : ""}.`,
    recoveryHint: null,
    capabilities,
    label: `${KIND_LABELS.channel} · ${row.platform}`,
    probeImplemented: false,
  };
}

async function statusForConnector(
  companyId: string,
  sourceId: string,
): Promise<ObjectStatus> {
  const sources = await getSources(companyId).catch(() => [] as SourceRow[]);
  const row = sources.find((s) => s.sourceId === sourceId);
  if (!row) {
    return {
      kind: "connector",
      objectId: sourceId,
      state: "unknown",
      summary: `No data source found for id ${sourceId}.`,
      recoveryHint:
        "Check /sources for the active list. Real probes land in Sub-wave D.",
      capabilities: [],
      label: KIND_LABELS.connector,
      probeImplemented: false,
    };
  }
  return {
    kind: "connector",
    objectId: sourceId,
    state: "works",
    summary: `${row.kind} source ${row.uri.slice(0, 80)} is registered.`,
    recoveryHint: null,
    capabilities: [],
    label: `${KIND_LABELS.connector} · ${row.kind}`,
    probeImplemented: false,
  };
}

async function statusForDomain(
  companyId: string,
  domainId: string,
): Promise<ObjectStatus> {
  const domains = await getDomains(companyId).catch(() => [] as DomainRow[]);
  const row = domains.find((d) => d.domainId === domainId);
  if (!row) {
    return {
      kind: "domain",
      objectId: domainId,
      state: "unknown",
      summary: `No domain registered for id ${domainId}.`,
      recoveryHint:
        "Pick a domain pack on /onboard/domain (Sub-wave C wires real pack writes).",
      capabilities: [],
      label: KIND_LABELS.domain,
      probeImplemented: false,
    };
  }
  if (row.owner === "unassigned") {
    return {
      kind: "domain",
      objectId: domainId,
      state: "degraded",
      summary: `Domain ${row.name} is registered but has no owner.`,
      recoveryHint:
        "Assign an owner via /domains so resources in this domain have an accountable Person.",
      capabilities: [],
      label: `${KIND_LABELS.domain} · ${row.name}`,
      probeImplemented: false,
    };
  }
  return {
    kind: "domain",
    objectId: domainId,
    state: "works",
    summary: `Domain ${row.name} (owner ${row.owner.slice(0, 8)}) — ${row.resourceCount} resource${row.resourceCount === 1 ? "" : "s"}.`,
    recoveryHint: null,
    capabilities: [],
    label: `${KIND_LABELS.domain} · ${row.name}`,
    probeImplemented: false,
  };
}

async function statusForPerson(
  companyId: string,
  personId: string,
): Promise<ObjectStatus> {
  const people = await getPeople(companyId).catch(() => [] as PersonRow[]);
  const row = people.find((p) => p.personId === personId);
  if (!row) {
    return {
      kind: "person",
      objectId: personId,
      state: "unknown",
      summary: `No Person folded for id ${personId}.`,
      recoveryHint:
        "Discovery proposes new Persons from wire traffic; visit /people for the pending list.",
      capabilities: [],
      label: KIND_LABELS.person,
      probeImplemented: false,
    };
  }
  if (row.status === "archived") {
    return {
      kind: "person",
      objectId: personId,
      state: "failed",
      summary: `Person ${row.displayName} is archived.`,
      recoveryHint:
        "Reinstate via /people; archived Persons stop receiving role grants but stay in the audit log.",
      capabilities: [],
      label: `${KIND_LABELS.person} · ${row.displayName}`,
      probeImplemented: false,
    };
  }
  if (row.status === "proposed") {
    return {
      kind: "person",
      objectId: personId,
      state: "degraded",
      summary: `Person ${row.displayName} is proposed — admin confirmation pending.`,
      recoveryHint:
        "Confirm on /people. Until confirmed, no role grants attach and ramp gauges don't move.",
      capabilities: [],
      label: `${KIND_LABELS.person} · ${row.displayName}`,
      probeImplemented: false,
    };
  }
  return {
    kind: "person",
    objectId: personId,
    state: "works",
    summary: `Person ${row.displayName}${row.position ? ` (${row.position})` : ""} confirmed.`,
    recoveryHint: null,
    capabilities: [],
    label: `${KIND_LABELS.person} · ${row.displayName}`,
    probeImplemented: false,
  };
}

async function statusForPolicy(
  companyId: string,
  policyId: string,
): Promise<ObjectStatus> {
  const policies = await getPolicies(companyId).catch(() => [] as PolicyRow[]);
  const row = policies.find(
    (p) => p.policyId === policyId || p.name === policyId,
  );
  if (!row) {
    return {
      kind: "policy",
      objectId: policyId,
      state: "unknown",
      summary: `No policy folded for id ${policyId}.`,
      recoveryHint:
        "Policy pack seed lands in Sub-wave C. Until then, /policies shows whatever the pack-policy projection has.",
      capabilities: [],
      label: KIND_LABELS.policy,
      probeImplemented: false,
    };
  }
  return {
    kind: "policy",
    objectId: policyId,
    state: row.firesLast7d > 0 ? "works" : "degraded",
    summary:
      row.firesLast7d > 0
        ? `Policy ${row.name} fired ${row.firesLast7d}× in the last 7 days.`
        : `Policy ${row.name} is registered but hasn't fired in the last 7 days.`,
    recoveryHint:
      row.firesLast7d > 0
        ? null
        : "Unfired policies may indicate the relevant flow isn't running, or the gate threshold is too loose.",
    capabilities: [],
    label: `${KIND_LABELS.policy} · ${row.name}`,
    probeImplemented: false,
  };
}

// ─── /logs accessor ────────────────────────────────────────────────────────

export interface ObjectLogEntry {
  /** Hash-prefix of the ledger entry; stable React key. */
  hash: string;
  ts: string;
  /** Derived entry-kind name (e.g. ``source_proposed``). */
  kind: string;
  quadrant: "propose" | "execute" | "verify" | "resolve";
  /** Truncated payload preview — JSON-encoded, ≤ 200 chars. */
  summary: string;
}

export interface ObjectLogsPage {
  entries: ObjectLogEntry[];
  total: number;
  nextOffset: number | null;
  /** When true, the kind has no first-class log filter yet — entries
   *  are scanned by id-match in payload args. */
  scanned: boolean;
}

const DEFAULT_LIMIT = 25;
const MAX_LIMIT = 100;
const SCAN_CAP = 500;

/**
 * Fetch ledger entries relevant to a given (kind, id). Reuses
 * ``getTraceEntries`` and filters in-memory by id-match against
 * payload keys typical for the object kind. ``limit + offset`` give
 * pagination; ``offset`` is index-based against the filtered list.
 *
 * No real probes — this is a read-only ledger scan, the same shape
 * v2.A's subscription audit panel used.
 */
export async function getObjectLogs(
  companyId: string,
  kind: StatusKind,
  objectId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<ObjectLogsPage> {
  const limit = Math.min(Math.max(opts.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);
  const offset = Math.max(opts.offset ?? 0, 0);

  const { getTraceEntries } = await import("./ledger-client");

  // Pull a generous window from the ledger and filter in-memory. We
  // don't have per-id projection tables for every object kind, so a
  // shallow scan over recent entries is the pragmatic floor.
  const page = await getTraceEntries(companyId, { limit: SCAN_CAP });
  const matched = page.entries.filter((e) => matchesObject(e.payload, kind, objectId));

  const total = matched.length;
  const slice = matched.slice(offset, offset + limit);
  const nextOffset = offset + limit < total ? offset + limit : null;

  return {
    entries: slice.map((e) => ({
      hash: e.hash.slice(0, 12),
      ts: e.ts,
      kind: e.kind,
      quadrant: e.quadrant,
      summary: summarizePayload(e.payload),
    })),
    total,
    nextOffset,
    scanned: true,
  };
}

const ID_KEYS_BY_KIND: Record<StatusKind, string[]> = {
  connector: ["source_id", "kind", "source_kind"],
  channel: ["install_id", "platform", "channel_id"],
  domain: ["domain_id", "id"],
  person: ["person_id", "added_by_person", "confirmed_by_person", "actor"],
  policy: ["policy_id", "policy_name", "gate"],
  agent: ["agent_id"],
  subscription: ["subscription_id", "agent_id"],
};

function matchesObject(
  payload: Record<string, unknown>,
  kind: StatusKind,
  objectId: string,
): boolean {
  const keys = ID_KEYS_BY_KIND[kind] ?? [];
  const args = (payload.args ?? {}) as Record<string, unknown>;
  for (const k of keys) {
    if (args[k] === objectId) return true;
    if (payload[k] === objectId) return true;
  }
  // Fallback: deep substring match — catches entries where the object
  // id is buried in a nested struct (e.g. applies_to.policy_id).
  try {
    const blob = JSON.stringify(payload);
    return blob.includes(objectId);
  } catch {
    return false;
  }
}

function summarizePayload(payload: Record<string, unknown>): string {
  try {
    const compact = JSON.stringify(payload);
    return compact.length > 200 ? `${compact.slice(0, 197)}…` : compact;
  } catch {
    return "[unserializable payload]";
  }
}

// ─── Test hooks ───────────────────────────────────────────────────────────

export const __test__ = {
  matchesObject,
  summarizePayload,
  ID_KEYS_BY_KIND,
};
