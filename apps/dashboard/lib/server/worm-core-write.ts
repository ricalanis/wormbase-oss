/**
 * Server-side fetch helper for the worm-core HTTP write API.
 *
 * A3.5 of `docs/superpowers/plans/2026-04-26-production-dashboard.md`.
 *
 * This module replaces the dashboard's previous demo-seam writes
 * (`INSERT INTO ledger ...` straight from `lib/ledger-client.ts`) with
 * a typed client over worm-core's bearer-token-authed write endpoints.
 * Every write goes through the canonical PEVR cycle via `write_primitive`
 * — hash-chained, audit-trailed, atomic, multi-tenant safe.
 *
 * Used only from Next.js server contexts (route handlers, RSC actions).
 * The bearer token is a server-side env var; never sent to the browser.
 *
 * Errors:
 * - 4xx from worm-core (validation / auth / tenant) → throws an Error
 *   with the response body as the message; the route handler maps to
 *   the appropriate HTTP status for the dashboard client.
 * - 5xx from worm-core → throws as well; the route handler maps to 502.
 * - Network failures → throws; route handler maps to 502.
 */

const DEFAULT_BASE = "http://worm-core:8910";

export interface WriteResultEnvelope {
  entry_ids: string[];
}

export interface ProposePersonResult extends WriteResultEnvelope {
  person_id: string;
}

export interface ProposePersonArgs {
  tenantSlug: string;
  name: string;
  email?: string | null;
  platform: string;
  platformUserId: string;
  position?: string | null;
  proposedBy?: string;
}

export interface ConfirmPersonArgs {
  tenantSlug: string;
  confirmedBy: string;
}

export interface ArchivePersonArgs {
  tenantSlug: string;
  archivedBy: string;
  reason: string;
}

export interface LinkIdentityArgs {
  tenantSlug: string;
  platform: string;
  platformUserId: string;
  linkedBy: string;
}

export interface UnlinkIdentityArgs {
  tenantSlug: string;
  unlinkedBy: string;
}

export type RoleFacet = "tenancy" | "domain" | "resource";

export interface GrantRoleArgs {
  tenantSlug: string;
  facet: RoleFacet;
  role: string;
  scopeId?: string | null;
  scopeType?: string | null;
  grantedBy: string;
}

export interface RevokeRoleArgs {
  tenantSlug: string;
  role: string;
  revokedBy: string;
}

export interface MergePersonsArgs {
  tenantSlug: string;
  keeperId: string;
  mergeeId: string;
  mergedBy: string;
}

export interface BulkConfirmPersonsArgs {
  tenantSlug: string;
  personIds: string[];
  confirmedBy: string;
}

export interface BulkConfirmPersonsResult {
  confirmed_count: number;
  person_ids: string[];
  entry_ids: string[];
}

export interface MergePersonsResult extends WriteResultEnvelope {
  keeper_id: string;
  mergee_id: string;
  identities_moved: number;
}

export interface SplitIdentityArg {
  platform: string;
  platformUserId: string;
}

export interface SplitPersonArgs {
  tenantSlug: string;
  newPersonName: string;
  newPersonEmail?: string | null;
  newPersonPosition?: string | null;
  identitiesToMove: SplitIdentityArg[];
  splitBy: string;
}

export interface SplitPersonResult extends WriteResultEnvelope {
  source_person_id: string;
  new_person_id: string;
  identities_moved: number;
}

function readBase(): string {
  return (process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE).replace(/\/+$/, "");
}

function readToken(): string {
  const raw = process.env.WORMBASE_LEDGER_API_TOKEN ?? "";
  const trimmed = raw.trim();
  if (!trimmed) {
    throw new Error(
      "WORMBASE_LEDGER_API_TOKEN is not set; refusing to call the worm-core HTTP write API",
    );
  }
  return trimmed;
}

interface RequestOptions {
  method: "GET" | "POST" | "DELETE";
  path: string;
  tenantSlug: string;
  body: Record<string, unknown> | null;
}

async function request<T>(opts: RequestOptions): Promise<T> {
  const base = readBase();
  const token = readToken();
  const url = `${base}${opts.path}`;
  const init: RequestInit = {
    method: opts.method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Tenant-Slug": opts.tenantSlug,
    },
    cache: "no-store",
  };
  if (opts.body !== null) {
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} failed: ${(err as Error).message}`,
    );
  }
  const text = await res.text();
  if (!res.ok) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} returned ${res.status}: ${text}`,
    );
  }
  if (text.length === 0) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch (err) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} returned non-JSON: ${(err as Error).message}`,
    );
  }
}

export async function proposePerson(
  args: ProposePersonArgs,
): Promise<ProposePersonResult> {
  return request<ProposePersonResult>({
    method: "POST",
    path: "/api/v1/people",
    tenantSlug: args.tenantSlug,
    body: {
      name: args.name,
      email: args.email ?? null,
      platform: args.platform,
      platform_user_id: args.platformUserId,
      position: args.position ?? null,
      proposed_by: args.proposedBy ?? "dashboard-admin",
    },
  });
}

export async function confirmPerson(
  personId: string,
  args: ConfirmPersonArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/confirm`,
    tenantSlug: args.tenantSlug,
    body: { confirmed_by: args.confirmedBy },
  });
}

export async function archivePerson(
  personId: string,
  args: ArchivePersonArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/archive`,
    tenantSlug: args.tenantSlug,
    body: { archived_by: args.archivedBy, reason: args.reason },
  });
}

export async function linkIdentity(
  personId: string,
  args: LinkIdentityArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/identities`,
    tenantSlug: args.tenantSlug,
    body: {
      platform: args.platform,
      platform_user_id: args.platformUserId,
      linked_by: args.linkedBy,
    },
  });
}

export async function unlinkIdentity(
  personId: string,
  platform: string,
  platformUserId: string,
  args: UnlinkIdentityArgs,
): Promise<WriteResultEnvelope> {
  const path =
    `/api/v1/people/${encodeURIComponent(personId)}` +
    `/identities/${encodeURIComponent(platform)}` +
    `/${encodeURIComponent(platformUserId)}`;
  return request<WriteResultEnvelope>({
    method: "DELETE",
    path,
    tenantSlug: args.tenantSlug,
    body: { unlinked_by: args.unlinkedBy },
  });
}

export async function grantRole(
  personId: string,
  args: GrantRoleArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/roles`,
    tenantSlug: args.tenantSlug,
    body: {
      facet: args.facet,
      role: args.role,
      scope_id: args.scopeId ?? null,
      scope_type: args.scopeType ?? null,
      granted_by: args.grantedBy,
    },
  });
}

export async function revokeRole(
  personId: string,
  grantId: string,
  args: RevokeRoleArgs,
): Promise<WriteResultEnvelope> {
  const path =
    `/api/v1/people/${encodeURIComponent(personId)}` +
    `/roles/${encodeURIComponent(grantId)}/revoke`;
  return request<WriteResultEnvelope>({
    method: "POST",
    path,
    tenantSlug: args.tenantSlug,
    body: { revoked_by: args.revokedBy, role: args.role },
  });
}

/**
 * Merge two Persons into one keeper. Writes a *sequence* of independent
 * PEVR cycles via worm-core — one unlink/link per identity moved + one
 * archive_person on the mergee. See `write_actions.merge_persons` for
 * rationale (A6 of the production-dashboard plan).
 */
export async function mergePersons(
  args: MergePersonsArgs,
): Promise<MergePersonsResult> {
  return request<MergePersonsResult>({
    method: "POST",
    path: "/api/v1/people/merge",
    tenantSlug: args.tenantSlug,
    body: {
      keeper_id: args.keeperId,
      mergee_id: args.mergeeId,
      merged_by: args.mergedBy,
    },
  });
}

/**
 * Bulk-confirm a batch of proposed Persons. W2.A6 — one wire request,
 * one independent PEVR cycle per Person on worm-core's side. The
 * dashboard's BulkConfirmDrawer surfaces the response either as
 * "N confirmed" or as the partial-batch error.
 */
export async function bulkConfirmPersons(
  args: BulkConfirmPersonsArgs,
): Promise<BulkConfirmPersonsResult> {
  return request<BulkConfirmPersonsResult>({
    method: "POST",
    path: "/api/v1/people/bulk-confirm",
    tenantSlug: args.tenantSlug,
    body: {
      person_ids: args.personIds,
      confirmed_by: args.confirmedBy,
    },
  });
}

/**
 * Split a Person — extract a subset of identities into a new Person.
 * Returns the new person's id; identities_to_move[0] becomes the seed
 * for the new propose_person entry.
 */
export async function splitPerson(
  sourcePersonId: string,
  args: SplitPersonArgs,
): Promise<SplitPersonResult> {
  return request<SplitPersonResult>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(sourcePersonId)}/split`,
    tenantSlug: args.tenantSlug,
    body: {
      new_person_name: args.newPersonName,
      new_person_email: args.newPersonEmail ?? null,
      new_person_position: args.newPersonPosition ?? null,
      identities_to_move: args.identitiesToMove.map((i) => ({
        platform: i.platform,
        platform_user_id: i.platformUserId,
      })),
      split_by: args.splitBy,
    },
  });
}


// ---------------------------------------------------------------------------
// Position review queue (Wave H Phase 2 Task 2C)
// ---------------------------------------------------------------------------


export interface PositionProposalRow {
  person_id: string;
  person_name: string;
  position: string;
  confidence: number;
  signals: string[];
  proposed_at: string | null;
  proposed_by: string;
}

export interface ListPositionProposalsResult {
  proposals: PositionProposalRow[];
}

export interface ConfirmPositionArgs {
  tenantSlug: string;
  position: string;
  confirmedBy: string;
}

export interface RejectPositionArgs {
  tenantSlug: string;
  position: string;
  rejectedBy: string;
  reason?: string | null;
}

export async function listPositionProposals(
  tenantSlug: string,
): Promise<ListPositionProposalsResult> {
  return request<ListPositionProposalsResult>({
    method: "GET",
    path: "/api/v1/people/proposals",
    tenantSlug,
    body: null,
  });
}

export async function confirmPositionProposal(
  personId: string,
  args: ConfirmPositionArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/position/confirm`,
    tenantSlug: args.tenantSlug,
    body: {
      position: args.position,
      confirmed_by: args.confirmedBy,
    },
  });
}

export async function rejectPositionProposal(
  personId: string,
  args: RejectPositionArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/people/${encodeURIComponent(personId)}/position/reject`,
    tenantSlug: args.tenantSlug,
    body: {
      position: args.position,
      rejected_by: args.rejectedBy,
      reason: args.reason ?? null,
    },
  });
}


// ---------------------------------------------------------------------------
// Data products + notebooks (Block F)
// ---------------------------------------------------------------------------


export interface ProposeDataProductArgs {
  tenantSlug: string;
  name: string;
  kind: string;
  requestedByPersonId: string;
  sourcesRequired?: string[];
  domainId?: string | null;
  parameters?: Record<string, unknown>;
  promptedByMessageId?: string | null;
  contentsBytesB64?: string | null;
  contentsExt?: string;
}

export interface ProposeDataProductResult extends WriteResultEnvelope {
  data_product_id: string;
}

export async function proposeDataProduct(
  args: ProposeDataProductArgs,
): Promise<ProposeDataProductResult> {
  return request<ProposeDataProductResult>({
    method: "POST",
    path: "/api/v1/data-products",
    tenantSlug: args.tenantSlug,
    body: {
      name: args.name,
      kind: args.kind,
      requested_by_person_id: args.requestedByPersonId,
      sources_required: args.sourcesRequired ?? [],
      domain_id: args.domainId ?? null,
      parameters: args.parameters ?? {},
      prompted_by_message_id: args.promptedByMessageId ?? null,
      contents_bytes_b64: args.contentsBytesB64 ?? null,
      contents_ext: args.contentsExt ?? "html",
    },
  });
}

export interface RegenerateDataProductArgs {
  tenantSlug: string;
  sourceHashes?: string[];
  contentsBytesB64?: string | null;
  contentsExt?: string;
  generatedBy?: string;
}

export async function regenerateDataProduct(
  dataProductId: string,
  args: RegenerateDataProductArgs,
): Promise<WriteResultEnvelope & { run_id: string; content_hash: string }> {
  return request({
    method: "POST",
    path: `/api/v1/data-products/${encodeURIComponent(dataProductId)}/regenerate`,
    tenantSlug: args.tenantSlug,
    body: {
      source_hashes: args.sourceHashes ?? [],
      contents_bytes_b64: args.contentsBytesB64 ?? null,
      contents_ext: args.contentsExt ?? "html",
      generated_by: args.generatedBy ?? "worm",
    },
  });
}

export interface ConsumeDataProductArgs {
  tenantSlug: string;
  consumedByPersonId: string;
  surface: "dashboard" | "chat" | "voice" | "export";
  channel?: string | null;
}

export async function consumeDataProduct(
  dataProductId: string,
  args: ConsumeDataProductArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/data-products/${encodeURIComponent(dataProductId)}/consume`,
    tenantSlug: args.tenantSlug,
    body: {
      consumed_by_person_id: args.consumedByPersonId,
      surface: args.surface,
      channel: args.channel ?? null,
    },
  });
}

export interface ProposeNotebookArgs {
  tenantSlug: string;
  name: string;
  cells: Array<{ kind: string; source: string; language?: string }>;
  kernel: "python_local" | "python_pandas" | "sql_postgres";
  proposedByPersonId: string;
  domainId?: string | null;
}

export interface ProposeNotebookResult extends WriteResultEnvelope {
  notebook_id: string;
}

export async function proposeNotebook(
  args: ProposeNotebookArgs,
): Promise<ProposeNotebookResult> {
  return request<ProposeNotebookResult>({
    method: "POST",
    path: "/api/v1/notebooks",
    tenantSlug: args.tenantSlug,
    body: {
      name: args.name,
      cells: args.cells,
      kernel: args.kernel,
      proposed_by_person_id: args.proposedByPersonId,
      domain_id: args.domainId ?? null,
    },
  });
}

export interface RunNotebookArgs {
  tenantSlug: string;
  runBy?: string;
  timeoutS?: number;
}

export async function runNotebook(
  notebookId: string,
  args: RunNotebookArgs,
): Promise<
  WriteResultEnvelope & { run_id: string; status: string; duration_ms: number }
> {
  return request({
    method: "POST",
    path: `/api/v1/notebooks/${encodeURIComponent(notebookId)}/run`,
    tenantSlug: args.tenantSlug,
    body: {
      run_by: args.runBy ?? "worm",
      timeout_s: args.timeoutS ?? 30,
    },
  });
}

export interface PublishNotebookArgs {
  tenantSlug: string;
  runId: string;
  ownerPersonId: string;
  version: string;
  publishedBy: string;
  domainId?: string | null;
}

export async function publishNotebook(
  notebookId: string,
  args: PublishNotebookArgs,
): Promise<WriteResultEnvelope> {
  return request<WriteResultEnvelope>({
    method: "POST",
    path: `/api/v1/notebooks/${encodeURIComponent(notebookId)}/publish`,
    tenantSlug: args.tenantSlug,
    body: {
      run_id: args.runId,
      owner_person_id: args.ownerPersonId,
      version: args.version,
      published_by: args.publishedBy,
      domain_id: args.domainId ?? null,
    },
  });
}

// ---------------------------------------------------------------------------
// W2.A8 — Replay + Sign
// ---------------------------------------------------------------------------

export interface ReplayDataProductArgs {
  tenantSlug: string;
  strict?: boolean;
  generatedBy?: string;
}

export interface ReplayDataProductResult extends WriteResultEnvelope {
  data_product_id: string;
  run_id: string;
  content_hash: string;
  expected_content_hash: string;
  matches_original: boolean;
}

/**
 * POST /api/v1/data-products/{id}/replay — strict-replay the artifact
 * against pinned source-hashes. The dashboard's "Replay" button calls
 * this; the response's `matches_original` flag drives the on-screen
 * "bit-identical content_hash" badge.
 */
export async function replayDataProduct(
  dataProductId: string,
  args: ReplayDataProductArgs,
): Promise<ReplayDataProductResult> {
  return request<ReplayDataProductResult>({
    method: "POST",
    path: `/api/v1/data-products/${encodeURIComponent(dataProductId)}/replay`,
    tenantSlug: args.tenantSlug,
    body: {
      strict: args.strict ?? true,
      generated_by: args.generatedBy ?? "replay",
    },
  });
}

export interface SignNotebookArgs {
  tenantSlug: string;
  runId: string;
  ownerPersonId: string;
  version: string;
  signedBy: string;
  domainId?: string | null;
}

export interface SignatureReceipt {
  notebook_id: string;
  run_id: string;
  owner_person_id: string;
  version: string;
  signed_by: string;
  signature_hash: string;
  entry_ids: string[];
}

export interface SignNotebookResult extends WriteResultEnvelope {
  notebook_id: string;
  signature_receipt: SignatureReceipt;
}

/**
 * POST /api/v1/notebooks/{id}/sign — sign (publish) a notebook with a
 * per-Person signature receipt. The receipt's `signature_hash` is
 * deterministic; the dashboard surfaces it as the audit-grade
 * attestation badge on the notebook page.
 */
export async function signNotebook(
  notebookId: string,
  args: SignNotebookArgs,
): Promise<SignNotebookResult> {
  return request<SignNotebookResult>({
    method: "POST",
    path: `/api/v1/notebooks/${encodeURIComponent(notebookId)}/sign`,
    tenantSlug: args.tenantSlug,
    body: {
      run_id: args.runId,
      owner_person_id: args.ownerPersonId,
      version: args.version,
      signed_by: args.signedBy,
      domain_id: args.domainId ?? null,
    },
  });
}


// ---------------------------------------------------------------------------
// W2.A7 — KPI / decision / process primary write actions
// ---------------------------------------------------------------------------


export interface ProposeKpiArgs {
  tenantSlug: string;
  label: string;
  formula?: string;
  unit?: string;
  sourceIds?: string[];
  ownerPosition?: string | null;
  proposedBy?: string;
}

export interface ProposeKpiResult extends WriteResultEnvelope {
  kpi_id: string;
}

/**
 * POST /api/v1/kpis/propose — admin-driven KPI proposal. Writes
 * ``emit_kpi_proposed`` through the canonical PEVR cycle. The gold
 * cascade reader picks up the proposal and threads it into the
 * ``emit_kpi_node`` tree on the next refresh.
 */
export async function proposeKpi(
  args: ProposeKpiArgs,
): Promise<ProposeKpiResult> {
  return request<ProposeKpiResult>({
    method: "POST",
    path: "/api/v1/kpis/propose",
    tenantSlug: args.tenantSlug,
    body: {
      label: args.label,
      formula: args.formula ?? "",
      unit: args.unit ?? "count",
      source_ids: args.sourceIds ?? [],
      owner_position: args.ownerPosition ?? null,
      proposed_by: args.proposedBy ?? "dashboard-admin",
    },
  });
}


export interface RecordDecisionArgs {
  tenantSlug: string;
  decisionText: string;
  channelId: string;
  decidedByPersons?: string[];
  evidenceMessageIds?: string[];
  confidence?: number;
  proposedBy?: string;
}

export interface RecordDecisionResult extends WriteResultEnvelope {
  decision_id: string;
}

/**
 * POST /api/v1/decisions — admin-recorded decision. Decisions normally
 * auto-extract from chat via ``process_extractor``; this is the manual
 * canonicalisation path for decisions the worm hasn't yet caught.
 */
export async function recordDecision(
  args: RecordDecisionArgs,
): Promise<RecordDecisionResult> {
  return request<RecordDecisionResult>({
    method: "POST",
    path: "/api/v1/decisions",
    tenantSlug: args.tenantSlug,
    body: {
      decision_text: args.decisionText,
      channel_id: args.channelId,
      decided_by_persons: args.decidedByPersons ?? [],
      evidence_message_ids: args.evidenceMessageIds ?? [],
      confidence: args.confidence ?? 0.95,
      proposed_by: args.proposedBy ?? "dashboard-admin",
    },
  });
}


export interface ProcessMapStepArg {
  order: number;
  actor: string;
  action: string;
  sourceMessageId?: string;
}

export interface ProposeProcessMapArgs {
  tenantSlug: string;
  processName: string;
  steps: ProcessMapStepArg[];
  domain?: string;
  confidence?: number;
  proposedBy?: string;
}

export interface ProposeProcessMapResult extends WriteResultEnvelope {
  process_id: string;
}

/**
 * POST /api/v1/processes — admin-authored process map. Manual entry
 * point complementing the auto-extraction path in ``process_extractor``.
 */
export async function proposeProcessMap(
  args: ProposeProcessMapArgs,
): Promise<ProposeProcessMapResult> {
  return request<ProposeProcessMapResult>({
    method: "POST",
    path: "/api/v1/processes",
    tenantSlug: args.tenantSlug,
    body: {
      process_name: args.processName,
      steps: args.steps.map((s) => ({
        order: s.order,
        actor: s.actor,
        action: s.action,
        source_message_id: s.sourceMessageId ?? "",
      })),
      domain: args.domain ?? "general",
      confidence: args.confidence ?? 0.95,
      proposed_by: args.proposedBy ?? "dashboard-admin",
    },
  });
}


// ===========================================================================
// === Research approve/reject + MCP token issuance (W2.A9) =================
// ===========================================================================


export type ExperimentResolveOutcome = "keep" | "discard";

export interface ResolveExperimentArgs {
  tenantSlug: string;
  resolvedBy: string;
  rationale?: string;
  observedDelta?: number;
}

export interface ResolveExperimentResult extends WriteResultEnvelope {
  experiment_id: string;
  outcome: ExperimentResolveOutcome;
  rationale: string;
}

/**
 * POST /api/v1/experiments/{id}/approve — write
 * ``emit_experiment_resolved`` with ``outcome=keep``.
 *
 * Used by /research's "approve" button. Latest-wins read in
 * ``getExperimentsForUser`` makes this a true override of any prior
 * resolution the autoresearch loop may have written.
 */
export async function approveExperiment(
  experimentId: string,
  args: ResolveExperimentArgs,
): Promise<ResolveExperimentResult> {
  return request<ResolveExperimentResult>({
    method: "POST",
    path: `/api/v1/experiments/${encodeURIComponent(experimentId)}/approve`,
    tenantSlug: args.tenantSlug,
    body: {
      resolved_by: args.resolvedBy,
      rationale: args.rationale ?? "",
      observed_delta: args.observedDelta ?? 0,
    },
  });
}

/**
 * POST /api/v1/experiments/{id}/reject — write
 * ``emit_experiment_resolved`` with ``outcome=discard``.
 */
export async function rejectExperiment(
  experimentId: string,
  args: ResolveExperimentArgs,
): Promise<ResolveExperimentResult> {
  return request<ResolveExperimentResult>({
    method: "POST",
    path: `/api/v1/experiments/${encodeURIComponent(experimentId)}/reject`,
    tenantSlug: args.tenantSlug,
    body: {
      resolved_by: args.resolvedBy,
      rationale: args.rationale ?? "",
      observed_delta: args.observedDelta ?? 0,
    },
  });
}

export interface IssueMcpTokenArgs {
  tenantSlug: string;
  personId: string;
  ttlSeconds?: number | null;
  label?: string;
}

export interface IssueMcpTokenResult {
  token: string;
  person_id: string;
  tenant_slug: string;
  ttl_seconds: number;
  issued_at: string;
  expires_at: string;
  label: string;
}

/**
 * POST /api/v1/mcp/tokens — mint a Person-scoped compact bearer token.
 *
 * Surfaced by the dashboard's "Connect Claude Desktop" panel as a
 * copy-paste config snippet:
 *
 *   {"mcpServers":{"wormbase":{"transport":"http","url":"...","headers":{"Authorization":"Bearer ..."}}}}
 *
 * The token is the same compact format ``mcp_tools.auth.authorize_caller``
 * already accepts, so a Claude Desktop client uses it as-is.
 */
export async function issueMcpToken(
  args: IssueMcpTokenArgs,
): Promise<IssueMcpTokenResult> {
  return request<IssueMcpTokenResult>({
    method: "POST",
    path: "/api/v1/mcp/tokens",
    tenantSlug: args.tenantSlug,
    body: {
      person_id: args.personId,
      ttl_seconds: args.ttlSeconds ?? null,
      label: args.label ?? "",
    },
  });
}

export interface RegisterMcpPresetArgs {
  tenantSlug: string;
  kind: string;
  serverUrl: string;
  description?: string;
  suggestedDomain?: string;
  suggestedClassification?:
    | "public"
    | "internal"
    | "confidential"
    | "pii"
    | "regulated";
  proposedBy: string;
}

export interface RegisterMcpPresetResult extends WriteResultEnvelope {
  source_id: string;
  source_kind: string;
  uri: string;
  description: string;
}

/**
 * POST /api/v1/mcp/presets — register an inbound MCP preset.
 *
 * Records the operator's intent to wire up an external MCP server (e.g.
 * Notion, Atlassian) as a ledger-tracked ``source_proposed`` entry with
 * ``source_kind=mcp:<kind>``. The actual ``MCPConnector`` preset class
 * lives in ``packages/lake-surfaces`` and self-registers at import; this
 * endpoint surfaces the operator's intent so it's auditable, multi-
 * tenant scoped, and visible alongside native sources in /sources.
 */
export async function registerMcpPreset(
  args: RegisterMcpPresetArgs,
): Promise<RegisterMcpPresetResult> {
  return request<RegisterMcpPresetResult>({
    method: "POST",
    path: "/api/v1/mcp/presets",
    tenantSlug: args.tenantSlug,
    body: {
      kind: args.kind,
      server_url: args.serverUrl,
      description: args.description ?? "",
      suggested_domain: args.suggestedDomain ?? "general",
      suggested_classification: args.suggestedClassification ?? "internal",
      proposed_by: args.proposedBy,
    },
  });
}


// ---------------------------------------------------------------------------
// Phase 3 Task 3B — Ask the Worm
// ---------------------------------------------------------------------------

export interface AskWormArgs {
  tenantSlug: string;
  question: string;
}

export interface AskWormResult {
  ok: boolean;
  answer: string;
  references: Array<{ kind: string; ref: string }>;
  passthrough: boolean;
  channel_id?: string;
  chat_reply_id?: string | null;
  chat_received_seq?: number | null;
}

/**
 * POST /api/v1/worm/ask — dashboard's in-app ask round-trip.
 *
 * Forwards the question to worm-core. The endpoint synthesises a
 * ``chat_received`` PEVR cycle (same shape Slack ingest produces) and
 * fires the production ``MentionResponseReactivity``. The captured
 * worm reply lands in ``answer``; the ledger receives the full
 * propose / execute / verify / resolve trail for both the
 * chat_received and chat_reply cycles. Same code path as production
 * chat — no demo seam.
 *
 * The dashboard's ``/api/ask`` route handler calls this when
 * ``WORMBASE_LEDGER_API_TOKEN`` is set; absent token, the route
 * returns the honest "wiring note" stub.
 */
export async function askWorm(args: AskWormArgs): Promise<AskWormResult> {
  return request<AskWormResult>({
    method: "POST",
    path: "/api/v1/worm/ask",
    tenantSlug: args.tenantSlug,
    body: { question: args.question },
  });
}


// ---------------------------------------------------------------------------
// Onboarding Sub-wave C (2026-05-30) — domain pack + co-admin invite
// ---------------------------------------------------------------------------


export interface SelectDomainPackArgs {
  tenantSlug: string;
  companyId: string;
  packId: string;
  selectedByPersonId: string;
  notes?: string;
}

export interface SelectDomainPackResult {
  pack_id: string;
  pack_version: string;
  already_seeded: boolean;
  domain_ids: string[];
  policy_ids: string[];
}

/**
 * POST /api/v1/write_actions/domain_pack_selected/{pack_id} — Tier 2
 * pack picker. Emits ``domain_pack_selected`` parent + fan-out
 * (per-domain ``emit_domain_registered`` + per-policy
 * ``emit_policy_applied``).
 *
 * Idempotent: a prior pack-selection short-circuits with
 * ``already_seeded=true``. The handler validates ``pack_id`` against
 * the four canonical ids (generic / saas / marketplace / fintech).
 */
export async function selectDomainPack(
  args: SelectDomainPackArgs,
): Promise<SelectDomainPackResult> {
  return request<SelectDomainPackResult>({
    method: "POST",
    path: `/api/v1/write_actions/domain_pack_selected/${encodeURIComponent(args.packId)}`,
    tenantSlug: args.tenantSlug,
    body: {
      company_id: args.companyId,
      selected_by_person_id: args.selectedByPersonId,
      notes: args.notes ?? null,
    },
  });
}


export interface InvitePersonArgs {
  tenantSlug: string;
  companyId: string;
  invitedByPersonId: string;
  inviteeEmail?: string | null;
  inviteePlatformId?: string | null;
  roleIntent?: "admin" | "member" | "observer";
  notes?: string;
}

export interface InvitePersonResult {
  invited: boolean;
  invitee_email: string | null;
  invitee_platform_id: string | null;
  role_intent: string;
}

/**
 * POST /api/v1/write_actions/person_invited — Tier 2 co-admin invite.
 * Emits a ``person_invited`` PEVR cycle.
 *
 * At least one of ``inviteeEmail`` / ``inviteePlatformId`` MUST be
 * supplied; the handler returns 400 if both are absent. The actual
 * ``person_proposed`` → ``person_confirmed`` lifecycle fires when the
 * invitee accepts the signed acceptance URL.
 */
export async function invitePerson(
  args: InvitePersonArgs,
): Promise<InvitePersonResult> {
  return request<InvitePersonResult>({
    method: "POST",
    path: "/api/v1/write_actions/person_invited",
    tenantSlug: args.tenantSlug,
    body: {
      company_id: args.companyId,
      invited_by_person_id: args.invitedByPersonId,
      invitee_email: args.inviteeEmail ?? null,
      invitee_platform_id: args.inviteePlatformId ?? null,
      role_intent: args.roleIntent ?? "member",
      notes: args.notes ?? null,
    },
  });
}


// ---------------------------------------------------------------------------
// Onboarding Sub-wave D (2026-05-30) — confirmBusinessDef graduation
// ---------------------------------------------------------------------------


export interface ConfirmConceptArgs {
  tenantSlug: string;
  companyId: string;
  term: string;
  confirmedByPersonId: string;
}

export interface ConfirmConceptResult {
  term: string;
  concept_id: string;
  entry_ids: string[];
}

/**
 * POST /api/v1/write_actions/concept_confirmed/{term} — Tier 2
 * confirmBusinessDef graduation.
 *
 * Replaces the synthetic-receipt fallback wired in Sub-wave A. The
 * worm-core handler resolves ``term → concept_id`` from prior
 * ``concept_proposed`` ledger entries (latest match wins; case-
 * insensitive + whitespace-trimmed). 404 when no proposal matches —
 * the caller surfaces "Worm hasn't proposed this concept yet"
 * honestly rather than writing an orphan confirmation.
 *
 * No new KIND_REGISTRY entry — reuses the existing
 * ``concept_confirmed`` kind.
 */
export async function confirmConcept(
  args: ConfirmConceptArgs,
): Promise<ConfirmConceptResult> {
  return request<ConfirmConceptResult>({
    method: "POST",
    path:
      `/api/v1/write_actions/concept_confirmed/` +
      `${encodeURIComponent(args.term)}`,
    tenantSlug: args.tenantSlug,
    body: {
      company_id: args.companyId,
      confirmed_by_person_id: args.confirmedByPersonId,
    },
  });
}
