/**
 * TS-side mirrors of the Pydantic ledger models in
 * `packages/ledger/src/wormbase_ledger/entries.py`.
 *
 * The QA agent owns contract tests in parallel; this file is the
 * source-of-truth on the dashboard side. Keep field names + enum literals in
 * sync with KIND_REGISTRY in the Python package.
 *
 * Every record returned by the ledger client surfaces a Receipt tuple — that's
 * a hard PRD §4.4 requirement: "Receipts (hash + source + owner + classification)
 * are a first-class visual unit rendered consistently across every surface."
 */

export type Classification =
  | "public"
  | "internal"
  | "pii"
  | "restricted"
  | string;

export interface Receipt {
  hash: string;
  source: string;
  owner: string;
  classification: Classification;
}

export type RampAxisKey =
  | "ontology"
  | "schema"
  | "business_definitions"
  | "kpi_relational"
  | "conversational"
  | "operational";

export interface RampGaugeRow {
  axis: RampAxisKey;
  label: string;
  value: number;
  hint: string;
  receipt: Receipt;
  updatedAt: string;
}

/**
 * Knowledge-ramp counter gauges (Demo-day P2).
 *
 * Three integer-counted gauges separate from the six-axis
 * percentage-shaped ``RampGaugeRow``. Mirrors
 * ``apps/worm-core/src/wormbase_core/projections/knowledge_ramp.py``;
 * the dashboard's ``getKnowledgeRampGauges`` accessor folds the same
 * row stream and produces the same shape.
 */
export type KnowledgeRampAxis = "ontology" | "conversational" | "relational";

export interface KnowledgeRampGaugeRow {
  axis: KnowledgeRampAxis;
  label: string;
  count: number;
  sparkline: number[];
  emptyHint: string;
  populatedHint: string;
  traceFilter: string;
  lastSeq: number;
  lastTs: string | null;
}

export interface KnowledgeRampGaugesPayload {
  computedAt: string;
  windowSeconds: number;
  gauges: KnowledgeRampGaugeRow[];
}

export interface KpiNodeRow {
  id: string;
  label: string;
  owner: string;
  classification: Classification;
  confidence: number;
  hasChildren: boolean;
  children: KpiNodeRow[];
  receipt: Receipt;
}

export type LedgerEntryKind =
  | "concept_proposed"
  | "concept_confirmed"
  | "concept_rejected"
  | "source_proposed"
  | "source_confirmed"
  | "source_connected"
  | "source_profiled"
  | "policy_applied"
  | "policy_violated"
  | "domain_assigned"
  | "kpi_proposed"
  | "kpi_resolved"
  | "ramp_recompute"
  | "gate_fired"
  | "channel_message";

export type LedgerQuadrant = "propose" | "execute" | "verify" | "resolve";

export interface TraceEntryRow {
  id: string;
  ts: string;
  kind: LedgerEntryKind | string;
  quadrant: LedgerQuadrant;
  hash: string;
  prevHash: string | null;
  payload: Record<string, unknown>;
  receipt: Receipt;
}

/**
 * PersonIdentity entry for a Person — one row per (platform, platform_user_id).
 *
 * Folded from `emit_person_proposed` (initial identity) +
 * `emit_identity_linked` (added later) − `emit_identity_unlinked` (removed).
 *
 * `proposedBy` carries the original `emit_person_proposed.proposed_by`
 * (or `emit_identity_linked.linked_by`) attribution string verbatim — e.g.
 * `"worm:whatsapp_organic_discovery"` (B2's encoding), `"worm:slack_roster"`,
 * `"admin_invite"`, or a real admin Person UUID. Optional for back-compat
 * with pre-D2 callers and entries written before `proposed_by` was on the
 * payload.
 *
 * `addedAt` is the ledger ts of the entry that introduced this identity —
 * used for relative-time provenance ("2 minutes ago") on the proposals
 * surface (W4-D).
 */
export interface PersonIdentityRow {
  platform: string;
  platformUserId: string;
  proposedBy?: string | null;
  addedAt?: string | null;
}

/**
 * Tenancy role enum — mirrors `_TENANCY_ROLES` in
 * `packages/ledger/src/wormbase_ledger/entries.py`.
 */
export type TenancyRole = "installer" | "admin" | "member" | "observer";

/**
 * PersonRow surfaced by `getPeople` / `getPersonById`.
 *
 * Production shape (post-A3): folded from the A1 + A2 ledger writes.
 *   - Identity: emit_person_proposed (+ emit_identity_linked / unlinked)
 *   - Status: emit_person_confirmed → "active", emit_person_archived → "archived"
 *   - Tenancy role: latest unrevoked emit_role_assigned (priority installer > admin > member > observer)
 *   - Grants: counts of emit_domain_role_assigned + emit_resource_role_assigned
 *
 * Back-compat fields (`roles`, `ownedDomains`, `ownedResources`) still exist
 * for the existing `<PersonRow>` table component; they are derived flatly from
 * the new shape so the surface stays receipted while A5 (production /people
 * page) is in flight.
 */
export interface PersonRow {
  personId: string;
  displayName: string;
  email: string | null;
  position: string | null;
  status: "proposed" | "active" | "archived";
  tenancyRole: TenancyRole | null;
  identities: PersonIdentityRow[];
  domainGrantCount: number;
  resourceGrantCount: number;
  // Legacy fields kept for back-compat with the existing PersonRow component
  // and /domains owner dropdown. Will be re-derived from the new shape.
  roles: string[];
  ownedDomains: string[];
  ownedResources: string[];
  receipt: Receipt;
}

/**
 * Per-identity record returned by `getIdentitiesForPerson`.
 *
 * Carries display metadata (added_at, display_name) the bare
 * `PersonIdentityRow` (used inside `PersonRow.identities`) doesn't.
 *
 * `proposedBy` carries the original `emit_person_proposed.proposed_by`
 * attribution when the identity was seeded by the person-propose event;
 * later `emit_identity_linked` rows surface their `linked_by` attribution
 * here too. Used by D2's /people surface to group identities by source
 * ("Worm (organic from WhatsApp)", "Worm (Slack roster)", "Admin manual").
 * Optional for back-compat with pre-D2 callers.
 */
export interface PersonIdentityDetailRow {
  platform: string;
  platformUserId: string;
  displayName: string | null;
  addedAt: string;
  proposedBy?: string | null;
}

/**
 * Role grant facet — three independent facets per Block A2 of the
 * production-dashboard PRD.
 *
 *   - "tenancy"  : installer | admin | member | observer (no scope)
 *   - "domain"   : owner | contributor (scopeId = domain_id)
 *   - "resource" : maintainer | contributor (scopeId = resource_id, scopeType = resource_type)
 */
export type RoleFacet = "tenancy" | "domain" | "resource";

export interface PersonRoleGrant {
  facet: RoleFacet;
  role: string;
  scopeId: string | null;
  scopeType: string | null;
  grantedBy: string | null;
  grantedAt: string;
  /** Always null in the GET endpoints — `getRolesForPerson` filters revoked. */
  revokedAt: string | null;
}

export interface DomainRow {
  domainId: string;
  name: string;
  owner: string;
  classificationDefault: Classification;
  resourceCount: number;
  receipt: Receipt;
}

export type SourceFlow =
  | "drop_and_profile"
  | "credential_offered_in_dm"
  | "mentioned_in_conversation"
  | "dashboard_form"
  | "kpi_gap_triggered"
  | "lake_discovery"
  | "provisioned_at_install";

export interface SourceRow {
  sourceId: string;
  uri: string;
  kind: string;
  addedByPerson: string;
  addedAt: string;
  addedViaFlow: SourceFlow;
  addedInResponseTo: string | null;
  rowCount: number;
  lastProfileTs: string | null;
  receipt: Receipt;
  /**
   * Medallion-cascade status flags. True when the corresponding ledger
   * entry has been written for this source. See Step 2 of the canonical
   * product arc (`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`).
   * Optional so existing fixtures (and pre-medallion ledgers) keep loading.
   */
  bronzed?: boolean;
  silvered?: boolean;
  golded?: boolean;
  /**
   * Maintainer Person — folded from
   *   emit_resource_role_assigned (resource_type=source, role=maintainer)
   * filtered to this source_id. Latest unrevoked grant wins. Null until
   * any maintainer grant lands. Surfaced by /sources (D5).
   */
  maintainerPersonId?: string | null;
  maintainerName?: string | null;
  /**
   * Owner domain — derived from the source's domain assignment. Null
   * until a domain link is established. /sources (D5) renders as a
   * drill-through to /domains.
   */
  ownerDomain?: string | null;
  /**
   * Classification (mirror of receipt.classification, surfaced as a
   * dedicated column in /sources for color-coded badges per PRD §5.5).
   */
  classification?: Classification;
  /**
   * Lake-freshness state — Phase 3 Task 3D (validation gap P2.8).
   *
   * `lastSeen` is the most-recent moment the lake-maintainer observed
   * the source — read from `projection_sources.last_seen` (Wave G's
   * `v003_source_last_seen` migration). Null until the maintainer has
   * fired against this source at least once.
   *
   * `driftDetected` reflects the most-recent
   * `emit_source_drift_detected` for this source. `driftReason` carries
   * the human-readable reason from the latest drift signal. Both null
   * until the drift detector has fired.
   *
   * `maintenanceSignals` is a 30-day window of every
   * `emit_source_*_signaled` / `emit_source_*_detected` /
   * `emit_source_*_refreshed` for this source — newest first. Used by
   * the dashboard's freshness timeline to make the lake-maintainer's
   * autonomous activity visible.
   */
  lastSeen?: string | null;
  driftDetected?: boolean;
  driftReason?: string | null;
  maintenanceSignals?: MaintenanceSignal[];
}

/**
 * One lake-maintainer signal entry surfaced on /sources. Each entry maps
 * 1:1 to a ledger `emit_source_*` row written by the lake-maintainer
 * Reactivities (`packages/lake-maintainer/src/wormbase_lake_maintainer/reactivities.py`).
 *
 * Read-only — the dashboard never writes these.
 */
export type MaintenanceSignalKind =
  | "staleness"
  | "drift"
  | "classification_refresh"
  | "lineage_break";

export interface MaintenanceSignal {
  kind: MaintenanceSignalKind;
  ts: string;
  /** Tool name as it appears on the ledger (`emit_source_*`). */
  tool: string;
  /** Short human-readable summary. May be null when the underlying
   *  entry doesn't carry a reason field. */
  reason: string | null;
}

export interface PolicyRow {
  policyId: string;
  name: string;
  plainLanguage: string;
  gateImpl: string;
  scope: string;
  firesLast7d: number;
  receipt: Receipt;
}

/**
 * W3-B (2026-05-07) — one ``policy_applied`` execute entry, surfaced as
 * a row in the per-channel rate-limit status panel (and any other panel
 * that wants to read recent gate emissions for a specific policy).
 *
 * Folded by ``getPolicyAppliedEvents(companyId, policyName)`` from
 * ``emit_policy_applied`` execute entries whose ``args.policy_name``
 * matches. Carries the structured ``rule`` and ``rationale`` that the
 * rate limiter (and other gates) emits, plus the bot-phone scope
 * identifier so the UI can attribute the event to a specific bot when
 * multiple bots share a tenant.
 *
 * No new ledger entry kinds — this reads the existing ``policy_applied``
 * kind that's already wired through ``with_whatsapp_rate_limit`` (Wave E2)
 * and the warmup/PII/relevance gates. Schema-evolution doctrine: additive
 * type, no kind growth.
 */
export interface PolicyAppliedEvent {
  /** Hash-prefix of the underlying execute entry; stable React key. */
  hash: string;
  /** ISO-8601 ``ledger.ts`` for the entry. */
  ts: string;
  /**
   * Canonical policy name. For WhatsApp throttle audit this is
   * ``policy:whatsapp_rate_limit``. The accessor filters by this value.
   */
  policyName: string;
  /**
   * Rule that fired. For the rate limiter:
   * ``rate_limit_persistent_throttle``. Other policies may carry their
   * own rule names.
   */
  rule: string;
  /**
   * Whatever the gate's ``rationale`` arg carried — typically a
   * human-readable line. May be empty when the gate didn't supply one.
   */
  rationale: string;
  /** Where the gate applied (scope/platform/bot_phone/tenant_id, etc.). */
  appliesTo: Record<string, unknown>;
  /** Bot phone (when scoped to a single bot, e.g. WhatsApp) — pulled out
   *  of args for convenience. */
  botPhone: string | null;
  /** Outcome label (default ``applied``); future-proofs against gates
   *  that emit ``deferred`` / ``waived`` / etc. */
  outcome: string;
  receipt: Receipt;
}

/**
 * Channel-platform install record. One row per (tenant, platform), folded
 * from `emit_install_completed` and `emit_install_revoked`. Surfaced by
 * `/channels` (D3) — the Connected Platforms section.
 */
export interface InstallRow {
  installId: string;
  platform: string;
  installerPersonId: string | null;
  installerName: string | null;
  installedAt: string;
  status: "active" | "revoked";
  scopes: string[];
  botUserId: string | null;
  oauthGrantRef: string;
  /**
   * Block G — setup mode chosen for this tenant. ``null`` until the user
   * picks wizard or bot in /onboarding/setup-mode/choose. The redirect
   * guard in (app)/layout.tsx routes onboarding traffic accordingly.
   */
  setupMode: "wizard" | "bot" | null;
  /** Block G — set when emit_setup_completed lands. */
  setupCompletedAt: string | null;
  /**
   * Phase D1 (WhatsApp first-class) — per-platform pairing/connection state.
   *
   * For Slack: derived from the OAuth grant — ``connected`` when active,
   * ``disconnected`` when revoked.
   *
   * For WhatsApp: derived from the Baileys pairing lifecycle. ``paired``
   * when an active install entry exists (the adapter wrote it on first
   * ``connection_open`` after QR scan — see Wave B3 of the WhatsApp plan).
   * ``expired`` when the install was revoked. ``disconnected`` is the
   * default when no install row exists. ``awaiting`` is reserved for the
   * "login command issued, no QR scan yet" state — surfaced when a
   * pairing-intent ledger entry lands without a matching install yet
   * (placeholder until the pairing-intent emit lands; today the projection
   * never returns ``awaiting`` and the dashboard's empty-state handles
   * the "no install" case explicitly).
   *
   * Additive, defaulted by the projection so existing fixtures and
   * pre-Phase-D1 ledgers parse cleanly. Reads only ledger projections.
   */
  pairingStatus?: "connected" | "paired" | "awaiting" | "expired" | "disconnected";
  receipt: Receipt;
}

/**
 * Cross-tenant install summary used by the sign-in (`/login`) tenant picker.
 *
 * Each `InstallSummary` is one Install row stamped with the tenant it belongs
 * to, plus a denormalized installer email + display name and the most recent
 * activity timestamp. Folded by `getAllInstalls()` from every tenant's ledger
 * via `listKnownTenantsSync()`. There is no fixture fallback: when no tenant
 * has any installs the picker renders an honest empty state and points the
 * user at `/onboarding`.
 */
export interface InstallSummary {
  installId: string;
  tenantSlug: string;
  tenantDisplayName: string;
  companyId: string;
  platform: string;
  installerPersonId: string | null;
  installerName: string | null;
  installerEmail: string | null;
  installedAt: string;
  /** Most recent ledger ts seen for this tenant (any kind). Falls back to
   *  `installedAt` if no later activity has been folded yet. */
  lastActivityAt: string;
  status: "active" | "revoked";
  scopes: string[];
  receipt: Receipt;
}

export type Talkativeness = "lurker" | "responsive" | "proactive";

export interface ChannelRow {
  channelId: string;
  name: string;
  talkativeness: Talkativeness;
  lastPolicyHash: string;
  /**
   * Phase D1 (WhatsApp first-class) — platform tag inferred at projection
   * time. Slack `channel_id`s start with `C` (channel) or `D` (DM); WhatsApp
   * jids end in `@s.whatsapp.net` (DMs) or `@g.us` (groups). The /channels
   * surface uses this to render platform-specific affordances (display name
   * shape, badges). Optional + back-compat: pre-Phase-D1 fixtures and
   * existing tests omit it; the renderer falls back to channel_id.
   */
  platform?: string;
  /**
   * Phase D1 (WhatsApp first-class) — most recent `chat_received` ts seen
   * for this channel. Optional + back-compat. Surfaced as "last seen" in
   * the WhatsApp render branch (CLAUDE.md §3 capability honesty —
   * production-paired channels should show liveness signal).
   */
  lastSeenAt?: string | null;
  receipt: Receipt;
}

/**
 * Phase D3 (WhatsApp first-class) — one row per `conversation_sync` PEVR
 * cycle. Folded from `channel_adapter.emit_conversation_sync` execute
 * entries. Drives the per-channel sync history panel under
 * `/channels/<channel_id>` and the parent /channels "Recent syncs"
 * mini-panel.
 *
 * One sync row corresponds to one platform reconnect / initial-connect /
 * channel-join event. Per-message `chat_received` entries from the same
 * session reference it via `history_sync_id == sync_id`.
 *
 * `channelIds` lists every channel the sync touched (a multi-channel
 * Slack reconnect can include multiple ids). The panel filters by membership
 * when surfacing per-channel history.
 */
export type ConversationSyncTrigger =
  | "initial_connect"
  | "reconnect"
  | "channel_join";

export type ConversationSyncStatus =
  | "in_progress"
  | "completed"
  | "interrupted";

export interface ConversationSyncRow {
  syncId: string;
  platform: string;
  installId: string | null;
  channelIds: string[];
  trigger: ConversationSyncTrigger;
  startedAt: string;
  completedAt: string | null;
  messageCount: number;
  earliestTs: string | null;
  latestTs: string | null;
  status: ConversationSyncStatus;
  receipt: Receipt;
}

export interface BusinessDefProposal {
  term: string;
  proposedDefinition: string;
  sourceHash: string;
}

export interface OntologySeed {
  concept: string;
  aliases: string[];
  classificationDefault: Classification;
  enabled: boolean;
}

export interface PiiPattern {
  patternId: string;
  label: string;
  regex: string;
  enabled: boolean;
}

export interface ConversationMessage {
  ts: string;
  channel: string;
  author: string;
  text: string;
  receipt: Receipt;
}

export interface InsightCard {
  insightId: string;
  title: string;
  summary: string;
  kind: "process" | "schema" | "policy" | "kpi";
  receipt: Receipt;
}

export interface TaskRow {
  taskId: string;
  kind: "propose" | "resolve";
  description: string;
  due: string | null;
  receipt: Receipt;
}

export interface TraceCursor {
  cursor?: string | null;
  limit?: number;
  forSourceId?: string;
  forKpiId?: string;
  quadrant?: LedgerQuadrant;
  /**
   * W2.A10 — /trace search filters. URL-encoded by `TraceFilterBar`; the
   * server page reads them off `searchParams` and threads them down. All
   * filters are applied as AND; absent fields = no constraint.
   *
   * - `kind`        — substring match against the derived `TraceEntryRow.kind`
   *                    (e.g. `source_proposed`, `chat_received`). Substring
   *                    rather than equality so installers can scan loosely.
   * - `personId`    — match against `payload.actor`, `payload.args.added_by_person`,
   *                   `payload.args.confirmed_by_person`, or `payload.args.person_id`.
   * - `channelId`   — match against `payload.args.channel_id`.
   * - `tsFrom`      — ISO8601; entries with `ts < tsFrom` are dropped.
   * - `tsTo`        — ISO8601; entries with `ts > tsTo` are dropped.
   */
  kind?: string;
  personId?: string;
  channelId?: string;
  tsFrom?: string;
  tsTo?: string;
}

export interface TracePage {
  entries: TraceEntryRow[];
  nextCursor: string | null;
}

// ─── Step 3c: process retrieval ──────────────────────────────────────────
//
// Mirrors the four payloads in
// `packages/ledger/src/wormbase_ledger/entries.py` (search for
// "Step 3c: process retrieval"). Read by the /decisions, /processes, and
// /system-map dashboard surfaces.

export interface DecisionRow {
  decisionId: string;
  decisionText: string;
  decisionAt: string;
  channelId: string;
  decidedByPersons: string[];
  evidenceMessageIds: string[];
  confidence: number;
  receipt: Receipt;
}

export interface ProcessStep {
  order: number;
  actor: string;
  action: string;
  sourceMessageId: string;
}

export interface ProcessMapRow {
  processId: string;
  processName: string;
  steps: ProcessStep[];
  domain: string;
  confidence: number;
  proposedAt: string;
  receipt: Receipt;
}

export interface SystemMapEdge {
  kind: string;
  targetId: string;
  weight: number;
}

export interface SystemMapNode {
  nodeKind: "person" | "channel" | "role";
  nodeId: string;
  edges: SystemMapEdge[];
  receipt: Receipt;
}

export interface SystemMapPayload {
  nodes: SystemMapNode[];
  generatedAt: string | null;
}

export interface RecurringQuestionRow {
  questionId: string;
  normalizedQuestion: string;
  askedByPersons: string[];
  occurrences: number;
  firstSeenAt: string;
  lastSeenAt: string;
  suggestedAutomation: string | null;
  receipt: Receipt;
}

// ─── W5.A2 — resource conversations (statement-to-owner) ───────────────────
//
// Mirrors the three resource_conversation_* payloads in
// `packages/ledger/src/wormbase_ledger/entries.py`. A resource conversation
// is the artifact written when StatementToOwnerReactivity fires: the worm
// has heard a statement that references a resource owned by a Person and
// has DM'd them with the statement plus pinned resources. The dashboard's
// /people/<id> "Resource Conversations" card (W5.A5) reads these.

export type ResourceConversationOutcome =
  | "decision"
  | "process_update"
  | "no_action"
  | "muted";

export interface ResourceConversationTopic {
  kind: "kpi" | "source" | "domain" | "process";
  id: string;
  label: string;
  /** Optional in the dashboard surface (always populated by W5.A2 writes;
   *  omittable in tests / hand-rolled fixtures). */
  confidence?: number;
  domainId?: string | null;
  /** Free-form pass-through — the topic dict round-trips through the
   *  ledger payload and carries any future fields the worm appends. */
  [key: string]: unknown;
}

export interface ResourceConversationKpi {
  kpiId: string;
  label: string;
  formula: string;
  unit: string;
  domainId: string | null;
}

export interface ResourceConversationSource {
  sourceId: string;
  label: string;
  status: string;
  domainId: string | null;
}

export interface ResourceConversationDecision {
  decisionId: string;
  decisionText: string;
  decisionAt: string;
  channelId: string;
}

export interface ResourceConversationProcess {
  processId: string;
  processName: string;
  stepCount: number;
  domain: string;
}

export interface ResourceConversationDataProduct {
  dataProductId: string;
  name: string;
  kind: string;
  domainId: string | null;
}

/** The fully-typed resources bundle as W5.A2's writer emits it. */
export interface ResourceConversationResourcesTyped {
  kpis: ResourceConversationKpi[];
  sources: ResourceConversationSource[];
  decisions: ResourceConversationDecision[];
  processes: ResourceConversationProcess[];
  dataProducts: ResourceConversationDataProduct[];
}

/** Loose pass-through for the resources bundle.
 *
 * The wire format passes the dict through unchanged; the dashboard
 * surface accepts the loose shape so test fixtures and downstream
 * mappers don't have to provide every typed object on every render.
 */
export type ResourceConversationResources =
  | ResourceConversationResourcesTyped
  | Record<string, unknown>;

export interface ResourceConversationReply {
  replierId: string;
  content: string;
  seq: number;
  /** Optional ISO timestamp of the reply (when known). */
  ts?: string;
}

export interface ResourceConversationResolution {
  outcome: ResourceConversationOutcome;
  resolvedBy: string;
  decisionSeq: number | null;
}

export interface ResourceConversation {
  conversationId: string;
  topic: ResourceConversationTopic;
  ownerId: string;
  resources: ResourceConversationResources;
  statementSeq: number;
  /** The chat statement text that triggered the conversation, when
   *  available alongside the seq pointer. */
  statement?: string;
  channel: string;
  proposedAt: string;
  replies: ResourceConversationReply[];
  /** Most recent replies (UI convenience; usually the last 3 by seq desc).
   *  Always populated by accessors; defaults to ``[]``. */
  recentReplies: ResourceConversationReply[];
  /** Total reply count (UI convenience over ``replies.length``). */
  replyCount: number;
  /** Source ledger seq the conversation_proposed entry has. */
  seq?: number;
  resolution: ResourceConversationResolution | null;
  receipt: Receipt;
}

// ─── Step 2 (proactivity hook): time-to-aha gauge ───────────────────────────
//
// Six canonical milestones the worm hits on a fresh tenant. Each one is
// derived from a SINGLE ledger MIN(ts) query (no fixture fallback — this
// surface is live-only because it's a live-data demo of the worm's first
// minutes). See ``apps/dashboard/lib/ledger-client.ts`` →
// ``getOnboardingMilestones``.
export interface OnboardingMilestones {
  /** T+0 — the worm joined: first ``company_warmup_completed`` entry. */
  installAt: string | null;
  /** T+5 — first ``emit_source_proposed`` (drop / mention / discovery). */
  firstSourceAt: string | null;
  /** T+15 — first ``emit_concept_confirmed`` (column class / domain owner). */
  firstConceptAt: string | null;
  /** T+30 — first ``emit_kpi_proposed`` or ``emit_source_golded``. */
  firstGoldAt: string | null;
  /** T+24h — first ``emit_process_map_proposed`` or
   *  ``emit_recurring_question``. */
  firstProcessMapAt: string | null;
  /** T+24h — first ``emit_heuristic_experiment``. */
  firstExperimentAt: string | null;
}

// ─── Step 5: user structure + per-user autoresearch ─────────────────────
//
// Mirrors the eight new payloads in
// `packages/ledger/src/wormbase_ledger/entries.py` (search for "Step 5").
// Read by the /research dashboard tab and (later) the per-user research
// log embedded in /dashboard.

export type ExperimentOutcome = "keep" | "discard";

export interface PositionRegistryRow {
  /** Person UUID. */
  personId: string;
  /** Display name (falls back to email or person UUID). */
  displayName: string;
  /** Position id from the canonical registry (cfo / data_engineer / ...). */
  position: string;
  /** Email address if captured during onboarding. */
  email: string | null;
  /** Tenant role: admin / owner / member / observer. */
  role: string;
  /** When the position was assigned. */
  assignedAt: string;
  receipt: Receipt;
}

export interface ExperimentRow {
  experimentId: string;
  forPersonId: string;
  position: string;
  headlineMetric: string;
  proposedChange: Record<string, unknown>;
  expectedDelta: number;
  proposedAt: string;
  /** Run log (mock or real). null until the run lands. */
  runLog: Record<string, unknown> | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** Outcome: keep / discard / null while in flight. */
  outcome: ExperimentOutcome | null;
  observedDelta: number | null;
  rationale: string | null;
  resolvedAt: string | null;
  receipt: Receipt;
}

export interface MetricSamplePoint {
  observedAt: string;
  value: number;
}

export interface HeadlineMetricSeries {
  position: string;
  metricId: string;
  /** Time-ordered samples (oldest first). */
  points: MetricSamplePoint[];
}

export interface PositionMover {
  position: string;
  metricId: string;
  delta: number;
  experimentsKept: number;
  experimentsDiscarded: number;
}

export interface ResearchOverview {
  totalExperiments: number;
  totalKept: number;
  totalDiscarded: number;
  /** keep / total — null when total is 0. */
  winRate: number | null;
  topMovers: PositionMover[];
  latestExperiments: ExperimentRow[];
}

// ---------------------------------------------------------------------------
// Composite score + per-scope keep-rate (Demo-day P1).
//
// Mirrors `apps/worm-core/src/wormbase_core/projections/composite_score.py`
// and `apps/worm-core/src/wormbase_core/projections/keep_rate.py`.
// ---------------------------------------------------------------------------

export interface CompositeScorePoint {
  ledgerHeight: number;
  ts: string; // ISO-8601 UTC
  /** Composite score in [0, 1]. The chart renders 1 - score as a loss curve. */
  score: number;
  components: {
    gate_precision: number;
    propose_keep_ratio: number;
    ramp_delta: number;
    reactivity_confirm_rate: number;
  };
  /**
   * The reactivity_id that fired most often within this point's
   * contributing seq range. Empty string when no reactivities fired.
   */
  topContributorReactivityId: string;
  contributingSeqLo: number;
  contributingSeqHi: number;
}

export interface CompositeScoreSeries {
  tenantId: string;
  points: CompositeScorePoint[];
  windowDays: number;
  weights: {
    gate_precision: number;
    propose_keep_ratio: number;
    ramp_delta: number;
    reactivity_confirm_rate: number;
  };
}

/** Per-scope keep-rate sample for the /research baseline chart. */
export type KeepRateScope = "person" | "team" | "company";

export interface KeepRateSample {
  scope: KeepRateScope;
  /** ISO-8601 date YYYY-MM-DD (UTC bucket). */
  day: string;
  kept: number;
  total: number;
  ratio: number;
  /**
   * True when the day's resolution count is below the minimum-baseline
   * threshold. The dashboard renders a "synthetic baseline" tag in this
   * case so the chart never lies about its sample size.
   */
  synthetic: boolean;
}

// ---------------------------------------------------------------------------
// Data products + notebooks (Block F of the production-dashboard PRD).
// ---------------------------------------------------------------------------

export type DataProductKind =
  | "chart"
  | "table"
  | "report"
  /** Conversation→process_map gold artifact (P10). Carries
   * nodes/edges/window/confidence in ``parameters`` rather than
   * ``contents_uri`` because the payload is small and renderable
   * inline by /system-map's process-map lens. */
  | "process_map";
export type DataProductStatus = "proposed" | "generated" | "archived";

/** Shape of the parameters payload for a ``process_map`` data product.
 *
 * Matches the spec in `docs/superpowers/specs/2026-04-29-demo-day-prd.md`
 * §7 P10 — produced by ``RecurringQuestionProcessMapperReactivity`` when
 * an ``(asker, askee, topic)`` triplet recurs ≥3 times in a trailing
 * 14-day window. */
export interface ProcessMapPayload {
  nodes: ProcessMapNode[];
  edges: ProcessMapEdge[];
  windowStart: string;
  windowEnd: string;
  confidence: number;
}

export interface ProcessMapNode {
  actorPersonId: string;
  /** "asker" | "askee" | "asker_and_askee" — bidirectional participants
   * carry the combined role so the graph view can render them as a
   * distinct node shape. */
  roleInMap: string;
}

export interface ProcessMapEdge {
  fromPersonId: string;
  toPersonId: string;
  topic: string;
  frequency: number;
  firstSeen: string;
  lastSeen: string;
}

export interface ProcessMapDataProductRow {
  dataProductId: string;
  tenantId: string;
  name: string;
  status: string;
  domainId: string | null;
  proposedAt: string | null;
  payload: ProcessMapPayload;
  receipt: Receipt;
}
export type DataProductSurface = "dashboard" | "chat" | "voice" | "export";
export type NotebookKernel = "python_local" | "python_pandas" | "sql_postgres";
export type NotebookStatus = "proposed" | "run" | "published" | "archived";
export type NotebookRunStatus = "ok" | "error";

export interface DataProductRow {
  dataProductId: string;
  tenantId: string;
  name: string;
  kind: DataProductKind | string;
  status: DataProductStatus | string;
  requestedByPersonId: string;
  domainId: string | null;
  generatedAt: string | null;
  contentHash: string | null;
  contentsUri: string | null;
  receipt: Receipt;
}

export interface DataProductRunRow {
  runId: string;
  dataProductId: string;
  tenantId: string;
  generatedBy: string;
  ts: string;
  sourceHashes: string[];
  contentHash: string;
  durationMs: number;
}

export interface DataProductConsumptionRow {
  consumptionId: string;
  dataProductId: string;
  tenantId: string;
  personId: string;
  surface: DataProductSurface | string;
  channel: string | null;
  ts: string;
}

export interface NotebookRow {
  notebookId: string;
  tenantId: string;
  name: string;
  kernel: NotebookKernel | string;
  status: NotebookStatus | string;
  ownerPersonId: string | null;
  domainId: string | null;
  latestRunId: string | null;
  latestPublishedRunId: string | null;
  version: string | null;
  cells: NotebookCell[];
  receipt: Receipt;
}

export interface NotebookCell {
  kind: "code" | "markdown" | "sql";
  source: string;
  language?: string;
}

export interface NotebookRunRow {
  runId: string;
  notebookId: string;
  tenantId: string;
  status: NotebookRunStatus | string;
  ts: string;
  runBy: string;
  kernelStateHash: string;
  durationMs: number;
  cellOutputs?: Array<Record<string, unknown>>;
  cellHashes?: string[];
}

// ---------------------------------------------------------------------------
// MCP integration (Block J of the production-dashboard PRD).
// ---------------------------------------------------------------------------

export type McpCallOutcome = "ok" | "error" | "denied" | "timeout" | string;

/**
 * One row of ``projection_mcp_calls`` — written by ``record_mcp_call``
 * (apps/worm-core/src/wormbase_core/write_actions.py). Each call to
 * the worm-core MCP server records exactly one row. ``args_hash`` is
 * the sha256 hex of the call arguments — the raw args never persist
 * (privacy nuance of §8.3 in the MCP integration spec).
 */
export interface McpCallRow {
  mcpCallId: string;
  tenantId: string;
  callerPersonId: string | null;
  toolName: string;
  /** sha256 hex of the redacted args; raw args never leave the server. */
  argsHash: string;
  clientUa: string | null;
  startedAt: string;
  outcome: McpCallOutcome;
  latencyMs: number;
  /** Standard receipt for visual chrome consistency. */
  receipt: Receipt;
}

/**
 * Local MCP server catalog — what tools / resources / prompts the
 * tenant's MCP server exposes outbound. Read from a JSON
 * ``/mcp/catalog`` endpoint when the worm-core MCP server is
 * running; otherwise the dashboard renders an honest "MCP server not
 * yet running" empty state.
 */
export interface McpCatalogEntry {
  /** ``"tool"`` | ``"resource"`` | ``"prompt"``. */
  kind: "tool" | "resource" | "prompt";
  name: string;
  description: string;
  /** Optional tag-style classifications (``"read"``, ``"write"``,
   *  ``"admin-only"``) the catalog endpoint may surface. */
  tags?: string[];
}

export interface McpCatalog {
  /** Server reachable at the catalog endpoint. ``false`` means we
   *  rendered the honest empty state. */
  available: boolean;
  entries: McpCatalogEntry[];
}

// ---------------------------------------------------------------------------
// /ops health payload (W2.A10).
//
// Shape returned by GET /api/v1/ops/health. The dashboard's /ops tab
// polls this URL every 5s via `usePoll` and renders four cards:
// PostgresHealthCard / LedgerThroughputCard / MCPRateLimitCard /
// AgentLoopStatusCard.
//
// Every field is optional on the wire so the dashboard renders a partial
// view honestly when worm-core only knows part of the picture
// (e.g. Postgres down, but the worm-core process itself is responding).
// ---------------------------------------------------------------------------

export type HealthStatus = "ok" | "degraded" | "down" | "unknown";

export interface PostgresHealth {
  status: HealthStatus;
  /** Latency of the `SELECT 1` probe in milliseconds. */
  latencyMs: number | null;
  /** Free-form message — surfaced verbatim in the red banner when down. */
  message: string | null;
  /** Optional version string from `SELECT version()`. */
  version: string | null;
}

export interface LedgerThroughputBucket {
  /** ISO8601, start of the 1-minute bucket (UTC). */
  bucketStart: string;
  /** Entries that landed in this bucket. */
  count: number;
}

export interface LedgerThroughput {
  /** Total entries across the entire `windowMinutes` span. */
  totalLastWindow: number;
  windowMinutes: number;
  /**
   * 1-minute buckets, oldest first. Length is `windowMinutes`. Empty
   * buckets carry `count: 0` rather than being omitted — the sparkline
   * renders them as zero-height marks.
   */
  buckets: LedgerThroughputBucket[];
}

export interface MCPRateLimitTenant {
  /** Tenant slug (e.g. `baseworm`, `democorp`). */
  tenantSlug: string;
  tenantDisplayName: string;
  companyId: string;
  /** Calls counted in the trailing rate-limit window. */
  callsInWindow: number;
  /** Per-minute ceiling. */
  ceilingPerMin: number;
  /** Window in seconds (informational; ceiling is per-minute). */
  windowSeconds: number;
  /** True iff `callsInWindow >= ceilingPerMin`. */
  saturated: boolean;
}

export interface MCPRateLimits {
  enabled: boolean;
  /** Reason `enabled === false` (e.g. `WORMBASE_MCP_ENABLED` unset). */
  disabledReason?: string;
  tenants: MCPRateLimitTenant[];
}

export interface AgentLoopStatus {
  /** Stable id — `worm-core` / `channel-adapter` / `projection-runner`. */
  id: string;
  /** Display label (Title Case). */
  label: string;
  status: HealthStatus;
  /** ISO8601 of the last observed heartbeat / ledger event. */
  lastSeenAt: string | null;
  /** One-line health note. */
  message: string | null;
}

export interface OpsHealthPayload {
  /** Server-side wall-clock when the snapshot was assembled. */
  generatedAt: string;
  postgres: PostgresHealth;
  ledgerThroughput: LedgerThroughput;
  mcpRateLimits: MCPRateLimits;
  agentLoops: AgentLoopStatus[];
}

/**
 * Error envelope returned when the dashboard's /api/v1/ops/health proxy
 * cannot reach worm-core. Surfaced verbatim in the red banner.
 */
export interface OpsHealthError {
  ok: false;
  error: string;
  message?: string;
  status?: number;
}

// ---------------------------------------------------------------------------
// Reactivities (W5.A5).
//
// Mirrors ``ReactivityRegistry`` + the ``emit_reactivity_*`` ledger entries
// (W5.A1) and ``emit_resource_conversation_*`` (W5.A2). The dashboard's
// /reactivities tab folds the registry's bindings + the most-recent fire
// per reactivity into ``Reactivity`` rows; ``ReactivityFire`` is the
// per-fire row surfaced in the per-reactivity drawer + log.
// ---------------------------------------------------------------------------

export type ReactivityScope = "company" | "team" | "domain" | "person" | string;
export type ReactivityState = "proposed" | "active" | "disabled" | string;

/** Sketch returned by the natural-language proposal endpoint.
 *  ``confidence`` is 0..1; the dashboard surfaces it honestly so the
 *  admin can refine the description before confirming. */
export interface ReactivitySketch {
  id: string;
  name: string;
  description: string;
  scope: ReactivityScope;
  predicate_spec: Record<string, unknown>;
  condition_spec: Record<string, unknown>;
  action_spec: Record<string, unknown>;
  confidence: number;
  proposed_by: string;
}

export interface Reactivity {
  id: string;
  name: string;
  description: string;
  scope: ReactivityScope;
  state: ReactivityState;
  proposedBy: string | null;
  confirmedBy: string | null;
  disabledBy: string | null;
  disableReason: string | null;
  /** ISO8601 of the most recent ``emit_reactivity_fired`` for this id;
   *  null when never fired. */
  lastFiredAt: string | null;
  /** Spec dicts the registry persists with the propose / confirm. */
  predicateSpec: Record<string, unknown>;
  conditionSpec: Record<string, unknown>;
  actionSpec: Record<string, unknown>;
}

export interface ReactivityFire {
  /** Ledger seq of the ``emit_reactivity_fired`` execute entry. */
  seq: number;
  /** ISO8601. */
  ts: string;
  /** Seq of the ledger entry that triggered the fire. */
  sourceSeq: number;
  /** Reactivity-supplied novelty key (may be empty). */
  noveltyKey: string;
  /** Seqs of the PEVR cycle(s) the fire emitted. */
  actionSeqs: number[];
  /** Per-axis budget consumption: ``{per_owner: 1, per_domain: 1, …}``. */
  budgetUsed: Record<string, number>;
}

// (W5.A2 owns the canonical ``ResourceConversation`` + reply / resolution
// types — see the "W5.A2 — resource conversations" block above. This
// section previously held A5's placeholder version; the canonical block
// supersedes it.)

// ---------------------------------------------------------------------------
// /research audience scopes (W5.A4 + W5.A5).
//
// AutoresearchExperiments now carry an ``audience`` field
// (``person:<uuid>`` | ``team:<domain_uuid>`` | ``company``). The
// /research tab surfaces three filtered views via the AudienceTabs
// component; this enum names them.
// ---------------------------------------------------------------------------

export type ResearchAudience = "mine" | "team" | "company";

// ---------------------------------------------------------------------------
// /research Lessons card (Demo-day P9 — autoresearch learn step).
//
// Each ``experiment_lesson`` ledger entry materialises here. The card on
// /research renders the last 5 per scope; clicking through opens /trace
// filtered to that lesson's prior_keep_id (the kept experiment it learned
// from). LessonScope mirrors the autoresearch audience scopes.
// ---------------------------------------------------------------------------

export type LessonScope = "person" | "team" | "company";

export interface ExperimentLessonRow {
  /** prior_keep_id — the kept experiment (uuid5) this lesson was extracted from. */
  priorKeepId: string;
  scope: LessonScope;
  lessonText: string;
  lessonFeatures: Record<string, string>;
  appliedToProposer: string;
  /**
   * Ledger height (seq) of the first ``experiment_proposed`` that consumed
   * this lesson. ``null`` until first applied — closes the loop empirically.
   */
  appliedAt: number | null;
  proposedBy: string;
  /** ISO-8601 timestamp of the extraction write. */
  extractedAt: string;
  /**
   * Ledger seq of the most recent ``experiment_lesson`` row carrying this
   * prior_keep_id (every applied_at stamp re-writes the lesson). The /trace
   * deep link uses this to locate the row exactly.
   */
  ledgerSeq: number;
  receipt: Receipt;
}

// ---------------------------------------------------------------------------
// /research First-Knowing tab (Demo-day P12 — un-confirmed worm-detected
// phenomena). Altman Q1: "What does the worm know that the org's CDO doesn't,
// with the ledger entry where it knew it first?"
//
// Each row is a phenomenon detected by the worm whose corresponding
// ``*_confirmed`` ledger entry has not yet landed. Rows surface from two
// streams:
//   * canonical ``phenomenon_gap_detected`` execute rows (richest — carry
//     ``referenced_in_seq``, ``confidence``, and ``novelty_key``)
//   * raw ``person_proposed`` / ``reactivity_proposed`` propose rows whose
//     ``proposed_by`` is a worm/agent identity
// ---------------------------------------------------------------------------

export type FirstKnowingPhenomenonKind =
  | "kpi_gap"
  | "domain_gap"
  | "process_gap"
  | "reactivity_gap"
  | "person_gap";

export type FirstKnowingScope = "mine" | "team" | "company";
export type FirstKnowingRecency = "1h" | "24h" | "7d" | "all";

export interface FirstKnowingChatRow {
  /** Ledger seq of the chat_received row. */
  seq: number;
  /** ISO-8601 UTC timestamp. */
  ts: string;
  channelId: string;
  senderPerson: string;
  text: string;
  /** True for the chat_received row whose seq matches ``referenced_in_seq``. */
  isAnchor: boolean;
}

export interface FirstKnowingRow {
  kind: FirstKnowingPhenomenonKind;
  /** One-line, human-readable summary surfaced in the row body. */
  summary: string;
  /** Ledger seq of the originating propose / detection row. */
  firstDetectedSeq: number;
  /** ISO-8601 UTC of the propose / detection row. */
  firstDetectedTs: string;
  /** Natural key of the proposed entity (kpi_id / person_id / phenomenon_gap:novelty_key). */
  refId: string;
  /**
   * Ledger seq of the ``chat_received`` row that triggered the detection.
   * ``0`` when no chat triggered the detection (raw proposes).
   */
  referencedInSeq: number;
  /** Detector confidence in [0, 1]; ``null`` for raw proposes. */
  confidence: number | null;
  /** De-dup key from the phenomenon-gap detector; ``""`` for raw proposes. */
  noveltyKey: string;
  /** The agent/worm identity that proposed it. */
  proposedBy: string;
  /** target_kind from the propose payload (e.g. ``person_proposed``). */
  targetKind: string;
  scope: FirstKnowingScope;
  /**
   * The chat_received rows ±3 around ``referencedInSeq`` (in ascending seq
   * order). Empty when there is no chat anchor or the seq is not in the
   * tenant's chat stream.
   */
  chatterContext: FirstKnowingChatRow[];
  receipt: Receipt;
}
