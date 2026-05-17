# WormBase Semantic Layer + Agent Gateway — Design Spec

> **Date:** 2026-05-10
> **Status:** Design (pre-spike). No implementation until Phase 0 GO/NO-GO.
> **Provenance:** ASML conversation surfaced demand for "a semantic layer on top of data sources for agents to query, with governance in that layer." This spec converts that ask into a durable WormBase capability rather than a one-off integration.
> **Inputs read:** `Projects/wormbase/CLAUDE.md` (architectural commitments §§1–11), `docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md` (§2 Connector, §3 ChannelAdapter, §5 Roles), `docs/superpowers/specs/2026-04-27-mcp-integration.md` (MCP wire framing), `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` (additive-only entry kinds, Wave F Addendum 1), `docs/superpowers/notes/2026-05-02-lake-maintainer-phase-0-spike.md` (lake-maintainer Protocol split + W5a composition), `packages/inference-router/src/wormbase_inference/protocol.py` (existing `Router` Protocol), `packages/connectors/src/wormbase_connectors/base.py`, memory entries on Protocol-first design and research-then-empirically-validate.

---

## §0. Headline framing

**Two new building blocks. One dissolved seam.**

WormBase does not yet serve customers who already have a data lake. Today the worm builds its own lake (the 5 trigger flows + lake-maintainer); enterprise customers like ASML aren't going to migrate to WormBase's substrate. They want WormBase to be a **layer over** what they already have.

This spec adds two packages — `wormbase-catalog-mirror` (data plane) and `wormbase-agent-gateway` (control plane) — that together let WormBase deploy in **overlay mode** against an existing lake (Snowflake / Databricks / dbt / Iceberg / OpenMetadata / DataHub / etc.) without forking the SaaS-mode codebase. The 4 existing durable Protocols (`Connector` / `ChannelAdapter` / `MaintainableSource` / `Router`) gain two siblings (`CatalogSource` / `CredentialBroker`); the existing `Router` is extended to cover external models. No code is rewritten; no abstraction is duplicated.

The dissolved seam: external agents calling WormBase via MCP go through the **same** `Router` Protocol that internal worms (chat-presence, process-extractor, voice-agent) already use. The same `inference_served` ledger entry audits both. The same `CredentialBroker` holds both data-access service accounts (Snowflake JWTs) and model-access keys (Anthropic, Kimi, Gemma). One identity model, one audit chain, one credential vault, two routing surfaces (data + inference).

This is on-thesis with the institutional-AI rubric (C1, C3, C6, C7) and with the Karpathy "compounding state" anchor: every agent query, every drift signal, every model invocation enriches the same ledger. Switching cost compounds in one substrate, not three.

---

## §1. The thesis — what changes, what stays

### §1.1. The four locked design decisions (from brainstorming 2026-05-10)

| Decision | Choice | Why |
|---|---|---|
| Deployment topology | **Dual-mode** (overlay + SaaS) | ASML overlay is the demo target; SaaS path stays alive without forking |
| Query model | **Hybrid** (broker + federate, policy-chosen) | Sensitive / cross-domain → broker (in-path governance); trusted single-source → federate (lower latency, scoped tokens) |
| Import scope | **Catalog + lineage + policy + semantic-layer** | Maps ASML's literal ask; this is where the institutional-AI moat lives |
| Architecture | **Two packages, Protocol-first** | Matches `CLAUDE.md §1.5` decomposition doctrine; pluggable backends across the board |

### §1.2. The compartmentalization fix (the design upgrade after first draft)

**First draft** (rejected): `agent-gateway` would own LLM invocation for external agents (Claude Desktop calling MCP tools), parallel to the existing `Router` that handles internal LLM (Kimi/Gemma).

**Final design**: `agent-gateway` is a **thin MCP wire**. It records the agent-query boundary and routes data queries (broker / federate). When an MCP tool needs LLM internally (e.g., natural-language query understanding), it calls `Router.call()` exactly the way `chat-presence` does for Slack replies. Same audit (`inference_served`), same routing (Kimi / Gemma / Claude / OpenAI as backends), same credential broker, same governance gates.

Result: one Router, four backends (was two), one credential vault covering data + model creds, one identity model that lets the existing internal worms and the new external agents share the same `requested_by: AgentID` field on every LLM call.

---

## §2. Two new packages

```
packages/
├── wormbase-catalog-mirror/         # NEW — data plane
│   ├── src/wormbase_catalog_mirror/
│   │   ├── protocol.py              # CatalogSource Protocol + CatalogSnapshot / LineageGraph / ExternalPolicy / MetricDefinition
│   │   ├── implementations/
│   │   │   ├── dbt_manifest.py      # v1 reference impl
│   │   │   └── snowflake_native.py  # v1 reference impl (Phase 0 GO from S2)
│   │   ├── reactivities.py          # make_catalog_mirror_reactivities (W5a-composed drift detector)
│   │   ├── wires.py                 # wire_catalog_for_install
│   │   └── projections.py           # external_catalog, external_lineage, external_policy, external_metric
│   └── tests/
│
└── wormbase-agent-gateway/          # NEW — control plane
    ├── src/wormbase_agent_gateway/
    │   ├── mcp_server.py            # FastMCP, extends 2026-04-27 MCP integration spec
    │   ├── credential_broker/
    │   │   ├── protocol.py          # CredentialBroker Protocol (unified data + model)
    │   │   ├── vault.py             # HashiCorp Vault impl
    │   │   ├── aws_sm.py            # AWS Secrets Manager impl
    │   │   ├── customer_kms.py      # bring-your-own KMS adapter
    │   │   └── env.py               # local dev / fixture impl
    │   ├── identity.py              # Agent (Person sub-type), agent_grant model
    │   ├── router.py                # broker vs federate routing for DATA queries (not LLM — that's inference-router)
    │   ├── audit.py                 # agent_query PEVR helper
    │   ├── governance.py            # composes governance package gates inline
    │   └── wires.py                 # wire_agent_gateway_for_install
    └── tests/
```

Existing packages touched (no rewrites, additive only):

- `packages/inference-router/` — add `ClaudeClient` + `OpenAIClient` backends; promote `requested_by: str` → `requested_by: AgentID`; add `governance_context: GovernanceContext | None`.
- `packages/lake-maintainer/` — add `source_mode: "wormbase_owned" | "upstream_mirror"` flag on `Source`; route 4 maintenance methods through catalog-mirror reads in overlay mode.
- `packages/governance/` — add `AgentAccessGate` (composes into `agent_query` path).
- `packages/ledger/` — 9 new entry kinds (§6).
- `apps/worm-core/` — boot path gains `wire_catalog_for_install` + `wire_agent_gateway_for_install` (becomes 6 wires; governance still no-wire by design).

---

## §3. The Protocols (existing + new)

### §3.1. Existing Protocols (unchanged in shape)

| Protocol | Purpose | Implementations today |
|---|---|---|
| `Connector` | Live data acquisition (auth / discover / profile / sample / watch) | csv_local, postgres, snowflake, bigquery, s3_csv, stripe, salesforce, hubspot, gsheets, http_csv, linear, notion, mcp |
| `ChannelAdapter` | Chat platform wire normalization | slack, whatsapp (preview), discord (stub), teams (stub) |
| `MaintainableSource` | Lake maintenance (detect_drift / refresh_classification / staleness_signal / lineage_health) | external, filedrop, conversation, evidence |

> **Correction (Phase 0 §7 finding, 2026-05-11):** `MaintainableSource` lives at `wormbase_lake_maintainer.protocols` (**plural** module name; earlier drafts referenced `.protocol` singular). The four methods return **typed dataclasses** — `DriftReport`, `ClassificationUpdate`, `StalenessReport`, `LineageReport` (from `wormbase_lake_maintainer.types`) — NOT `dict | None` as one earlier prose passage implied. `MaintainableSource` is `@runtime_checkable` (verified S5).
| `Router` (inference-router) | LLM invocation entry point — every WormBase consumer depends on this | Kimi (cloud), Gemma (private VLAN); cached + ledger-aware |

### §3.2. NEW: `CatalogSource` Protocol

```python
# packages/wormbase-catalog-mirror/src/wormbase_catalog_mirror/protocol.py

from typing import Protocol, AsyncIterator

CatalogCapability = Literal["schema", "lineage", "policy", "semantic_layer", "quality"]

class CatalogSource(Protocol):
    """Mirrors structure (not data) from an upstream lake.

    Day-one implementations: dbt_manifest, snowflake_native.
    Future: databricks_uc, openmetadata, datahub, openlineage, iceberg_rest, atlas, glue.

    Same extensibility story as Connector + ChannelAdapter: adding a new upstream
    is a class + registry entry, never a core-code change.
    """

    kind: str                              # "dbt" | "snowflake" | "databricks_uc" | ...
    capability: set[CatalogCapability]

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle: ...

    async def discover_catalog(self, handle: AuthHandle) -> CatalogSnapshot:
        """Schema + table/column descriptions + tags + ownership.

        Returns a deterministic snapshot; the same upstream state at time T
        produces the same snapshot bytes (drift detection depends on this).
        """

    async def discover_lineage(self, handle: AuthHandle, resource_id: str) -> LineageGraph:
        """Upstream lineage — column-level if available, else table-level."""

    async def discover_policies(self, handle: AuthHandle, resource_id: str) -> list[ExternalPolicy]:
        """Mirror upstream masking / row-access / ABAC policies. Read-only."""

    async def discover_metrics(self, handle: AuthHandle) -> list[MetricDefinition]:
        """Semantic-layer metric defs (dbt MetricFlow, Cube, Malloy, LookML)."""

    async def watch_changes(self, handle: AuthHandle) -> AsyncIterator[CatalogDelta]:
        """Optional; falls back to periodic discover_catalog + diff if not implemented."""
```

`CatalogSnapshot`, `LineageGraph`, `ExternalPolicy`, `MetricDefinition` are pydantic models with stable schemas (no implementation-specific fields leak). Each carries an upstream-stable `external_id` so re-import is idempotent.

### §3.3. NEW: `CredentialBroker` Protocol — unified for data AND model

```python
# packages/wormbase-agent-gateway/src/wormbase_agent_gateway/credential_broker/protocol.py

class CredentialBroker(Protocol):
    """Single credential + token-issuance surface for data AND model access.

    Implementations: vault (HashiCorp), aws_sm, customer_kms, env (dev only).
    Per-Install backend choice; one customer can run agent-gateway against their
    own Vault while WormBase-the-SaaS-tenant runs against AWS Secrets Manager.
    """

    kind: str

    # ---- DATA access (lake queries via agent-gateway) ----

    async def hold_data_account(
        self,
        install_id: InstallID,
        upstream_kind: str,          # "snowflake" | "databricks" | "postgres" | ...
    ) -> DataAccountHandle:
        """Long-lived service account credentials for broker-mode queries."""

    async def issue_data_token(
        self,
        agent_id: AgentID,
        resource_id: ResourceID,
        ttl_s: int,
    ) -> ScopedDataToken:
        """Short-lived scoped token for federate-mode queries.
        Wraps Snowflake OAuth / Databricks SCIM / AWS STS / Postgres role assumption / etc.
        """

    # ---- MODEL access (Router clients fetch via this; replaces direct env reads) ----

    async def hold_model_account(
        self,
        install_id: InstallID,
        model_kind: str,             # "kimi" | "gemma" | "claude" | "openai"
    ) -> ModelAccountHandle:
        """Long-lived API key / endpoint URL for the Router's backend clients."""

    async def issue_model_token(
        self,
        agent_id: AgentID,
        model_kind: str,
        ttl_s: int,
        budget_remaining_usd: Decimal,
    ) -> ScopedModelToken:
        """Short-lived scoped token (budget-bounded) for federate model calls.
        Today only Anthropic + OpenAI support OAuth-shaped scoping; others fall
        back to a budget-limited proxy (issue-then-track rather than issue-then-enforce).
        """

    async def revoke(self, token_id: TokenID) -> None: ...
```

**Why unified, not split**: ASML's existing Vault holds both Snowflake JWTs and Anthropic API keys. Forcing two abstractions duplicates rotation logic, doubles audit surface, and hides the design fact that data creds and model creds have the same lifecycle (issue, scope, budget, revoke, audit).

### §3.4. EXTENDED: `Router` Protocol (existing in `packages/inference-router/`)

**Amendment 2026-05-10:** an earlier draft proposed adding `ClaudeClient` and `OpenAIClient` as Router backends. That was wrong — it re-introduced the very compartmentalization §1.2 dissolves. **External agents (Claude Desktop / ChatGPT / any MCP client) bring their own model and never route through WormBase's Router.** WormBase's Router stays Kimi/Gemma-only, served via the existing Ollama Cloud transport (`packages/inference-router/src/wormbase_inference/clients.py` already routes `KimiClient` → `https://ollama.com` with `kimi-k2.6:cloud`). The dissolved seam is among the three **internal** LLM consumers (chat-presence Slack reply, process-extractor summarization, MCP-tool internal NL→metric translation) — all use Router → Kimi/Gemma via Ollama Cloud and audit identically via `inference_served`.

Three additions to the existing Protocol. Backwards-compatible; existing callers keep working. No new backend clients.

```python
# packages/inference-router/src/wormbase_inference/protocol.py

# CHANGE 1: ServedBy unchanged — Kimi + Gemma (both via Ollama Cloud / own-VLAN) + cache
ServedBy = Literal["kimi", "gemma", "cache"]
# (Earlier draft added "claude" and "openai" — removed per amendment above.)

# CHANGE 2: requested_by promoted from free string to AgentID
@dataclass(frozen=True, slots=True)
class RouteRequest:
    call_type: CallType
    messages: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    system: str | None = None
    backend_hint: BackendHint = "auto"
    temperature: float = 0.0
    max_tokens: int | None = None
    requested_by: AgentID                   # was: str = "unknown" — now mandatory + typed
    governance_context: GovernanceContext | None = None  # NEW — composes inline gates
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)

# Backwards-compat note (Phase 0 §7 finding, 2026-05-11): production RouteRequest is
# `frozen=True, slots=True` which BLOCKS __post_init__ AgentID coercion. The Wave 2
# implementation does NOT retype the dataclass field directly — it converts at the
# Router boundary (str at the wire; AgentID inside Router.call() before emitting
# inference_served). This avoids touching every existing internal call-site at once
# (chat-presence / process-extractor / voice-agent each have 2-5 callsites). Tracks
# Risk #7 in §9.

# CHANGE 3: GovernanceContext — composes existing governance gates
@dataclass(frozen=True, slots=True)
class GovernanceContext:
    domain_id: DomainID | None = None
    classification_ceiling: Classification = "internal"
    cost_budget_usd: Decimal | None = None
    pii_redaction: bool = True
```

The existing `_DEFAULT_ROUTING` table gets one new entry for the MCP-tool internal-reasoning lane (routed to Kimi like every other reasoning call):

```python
_DEFAULT_ROUTING: dict[str, Literal["kimi", "gemma"]] = {
    "reasoning": "kimi",                # unchanged
    "affirm": "kimi",                   # unchanged
    "classify": "gemma",                # unchanged
    "summarize": "gemma",               # unchanged
    "voice_turn": "kimi",               # unchanged
    "agent_tool_reasoning": "kimi",     # NEW — MCP tools needing LLM internally route to Kimi (Ollama Cloud)
    "embed_query": "gemma",             # NEW (was implicit)
}
```

All existing internal callers (chat-presence, process-extractor, voice-agent) get a small refactor: pass `requested_by=<their_internal_agent_id>` (the worm-internal pseudo-agent identities — `worm:chat_presence`, `worm:process_extractor`, etc.). Audit clarity payoff is large; surface change is small.

---

### §3.5. NEW: `QuerySpec` Protocol — agent-facing primitive (amendment 2026-05-10 from research synthesis)

The 2026-05-10 research synthesis (`docs/superpowers/notes/2026-05-10-semantic-layer-best-practices-synthesis.md`) confirmed two empirical facts that shape the agent-gateway surface:

1. **Text-to-SQL accuracy collapses on real enterprise data** — 85% benchmark → 10.8% production (per @CollateData on X, corroborated by multiple academic papers). LLM SQL alone is unsafe at the boundary.
2. **The catalog-as-source-of-truth + agent-writes-QuerySpec pattern is converging across industry and academia** — @zygisSS22's verbatim prescription, OmniQuery / Dynamic-SQL / ExeSQL / MAGIC self-correction loops, dbt + Cube + Palantir Ontology positioning.

The fix: **agents submit structured `QuerySpec` to the agent-gateway, not raw SQL.** Backend (catalog-mirror) validates against the metric registry, compiles to upstream-specific SQL, executes via CredentialBroker. Raw SQL is still accepted in **federate mode** for trusted callers (per spec §4.3) but it's the escape hatch, not the front door.

```python
@dataclass(frozen=True)
class QuerySpec:
    """Structured query intent — agents submit this, NOT SQL.

    Per @zygisSS22's prescription: catalog is source of truth, agent writes
    QuerySpec, backend validates / plans / compiles / executes. Two modes:
    (a) metric-named (preferred): {metric: "revenue_q3", filter: {region: "EMEA"}}
    (b) ad-hoc structured: {dimensions: ["region"], measures: ["sum(revenue)"], ...}
    """
    # Mode (a) — named metric from catalog
    metric: str | None = None

    # Mode (b) — ad-hoc structured query
    dimensions: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()

    # Both modes
    filter: dict[str, Any] | None = None       # WHERE-shaped, validated against catalog
    time_grain: TimeGrain | None = None        # day | week | month | quarter | year
    time_range: tuple[str, str] | None = None  # ISO timestamps
    limit: int = 1000

    def validate(self) -> None:
        """Either `metric` OR (`dimensions` ∪ `measures`) must be non-empty."""
        if not self.metric and not (self.dimensions or self.measures):
            raise QuerySpecError("must supply either `metric` or `dimensions+measures`")
```

**Backend pipeline** (`catalog-mirror` → `agent-gateway`):
1. `validate(spec)` — schema check + reference check against metric / dimension / measure registry
2. `plan(spec)` — pick upstream (Snowflake / dbt model / etc.), pick join graph from lineage
3. `compile(spec)` — emit upstream-specific SQL with masking-policy composition
4. `execute(sql, scoped_token)` — broker mode via CredentialBroker
5. `verify(result)` — row count + hash + schema-shape check
6. `resolve(result)` — return to agent + emit `agent_query` PEVR

The pipeline shape mirrors PEVR exactly. Each step can fail and trigger a corrective loop (§4.5).

## §4. Data flows

### §4.1. Catalog import flow (overlay-mode bootstrap)

```
Admin: "@worm import dbt at github.com/acme/analytics"
  ↓
chat-presence parses intent → calls write_actions.import_catalog(kind="dbt", uri=...)
  ↓
worm-core resolves CatalogSource.kind="dbt" → DbtManifestCatalogSource()
  ↓
CatalogSource.authenticate(secrets) → handle
  ↓
CatalogSource.discover_catalog(handle) → CatalogSnapshot
  ↓
ledger.write(propose=external_catalog_imported, execute_fn=..., verify_fn=hash_check, resolve_fn=keep)
  ↓
projection_external_catalog populated; dashboard /lake/catalog renders
  ↓
W5a Reactivity registers per-source: CatalogDriftReactivity (polls watch_changes or periodic re-discover)
```

Lineage / policy / metric imports follow the same shape with their respective entry kinds.

### §4.2. Agent query — broker mode (sensitive / cross-domain / aggregated)

```
Claude Desktop → MCP call: lake.semantic.metric("revenue_q3", filter={region: "EMEA"})
  ↓
agent-gateway.mcp_server: agent_query (propose phase) — caller=claude_research_agent
  ↓
governance gates inline:
  ├─ AgentAccessGate: claude_research has grant on domain.finance + resource.revenue_q3? ✓
  ├─ Classification gate: revenue_q3 is "confidential", agent's ceiling allows it ✓
  ├─ PII redaction: prompt scanned, no PII detected ✓
  └─ Cost gate: under budget ✓
  ↓
agent-gateway.router: chose BROKER (revenue_q3 has upstream policy "no_direct_select")
  ↓
catalog-mirror lookup: MetricDefinition(name=revenue_q3) → SQL template + lineage + upstream policy refs
  ↓
CredentialBroker.hold_data_account(install_id, "snowflake") → service account JWT
  ↓
SQL execution against Snowflake (compose upstream + WormBase mask policy)
  ↓
ledger.write(execute_fn) → agent_query (execute phase) with row_count, hash, cost
  ↓
ledger.write(verify_fn) → agent_query (verify phase) — row hash matches expected schema
  ↓
ledger.write(resolve_fn) → agent_query (resolve phase) — kept, delivered
  ↓
return rows + audit_trail_id to Claude
```

### §4.3. Agent query — federate mode (trusted single-source, lower latency)

```
Claude Desktop → MCP call: lake.query("SELECT count(*) FROM internal.events WHERE day='2026-05-01'")
  ↓
agent-gateway.mcp_server: agent_query (propose phase)
  ↓
governance gates: agent has read on internal.events ✓
  ↓
agent-gateway.router: chose FEDERATE (single-source, internal classification, upstream IAM strong)
  ↓
CredentialBroker.issue_data_token(agent_id=claude_research, resource_id="internal.events", ttl_s=300)
  → ledger.write: credential (issue, status=active, ttl_expires_at=...)
  → ScopedDataToken (Snowflake OAuth JWT, scoped to row-policy on internal.events, 5 min TTL)
  ↓
return (governed_query_plan, scoped_jwt, callback_url) to Claude
  ↓
Claude executes against Snowflake DIRECTLY with the JWT — upstream IAM enforces row/column policy
  ↓
Claude callbacks WormBase with result hash + row count
  ↓
ledger.write(verify_fn) → agent_query (verify phase) — hash matches Claude's reported execution
  ↓
ledger.write(resolve_fn) → agent_query (resolve phase)
```

### §4.4. The dissolved seam — LLM invocation chain (the architectural payoff)

When an MCP tool needs LLM internally (e.g., `lake.semantic.search` does NL → metric translation):

```
Claude Desktop → MCP call: lake.semantic.search("revenue trends in Europe last quarter")
  ↓
agent-gateway: agent_query (propose) — caller=claude_research
  ↓
tool needs LLM to interpret query — calls Router.call(
    call_type="agent_tool_reasoning",
    requested_by=claude_research,        # AgentID, not free string
    governance_context=GovernanceContext(
        domain_id=finance, classification_ceiling="confidential",
        cost_budget_usd=0.05, pii_redaction=True
    ),
    messages=...
)
  ↓
Router (existing CachedRouter from inference-router):
  ├─ checks cache by RouteRequest hash ✗ miss
  ├─ default backend for "agent_tool_reasoning" → claude (via _DEFAULT_ROUTING)
  ├─ ClaudeClient.fetch_key() via CredentialBroker.hold_model_account(install_id, "claude")
  ├─ invokes Claude API with PII-redacted prompt
  ├─ ledger.write: inference_served (existing entry kind) — served_by=claude, requested_by=claude_research, cost=$0.013
  └─ returns RouteResponse(text="metric: revenue_q3, filter: region=EMEA", served_by="claude", ...)
  ↓
tool now has structured query → executes broker path (§4.2) → returns to agent-gateway
  ↓
agent_query resolved
```

The audit chain is: `agent_query` (the MCP boundary) `caused_by` `inference_served` (the LLM call) `caused_by` `agent_query` (the downstream broker query). Every leg has full PEVR, full identity, full cost, full classification. **Three different LLM-touching flows (channel-driven Slack reply, internal process-extractor summarization, external Claude tool call) all use the SAME Router and produce the SAME `inference_served` audit shape.** That's the dissolved seam.

---

### §4.5. The compounding query layer (amendment 2026-05-10 from research synthesis)

Industry zeitgeist (Palantir OAG, Cube AI API, dbt Semantic Layer MCP) and academic state-of-the-art (OmniQuery 94.2% multi-table accuracy via execution-feedback self-correction; Dynamic-SQL with multi-path fusion; ExeSQL self-training) converge on **the same loop shape**: propose → execute → reflect-on-feedback → retry → record-outcome → improve.

**WormBase's PEVR primitive (`propose → execute → verify → resolve`) IS this loop.** No new orchestrator code; we name what already exists and add the outcome-recording + template-promotion edges.

```
Agent (NL question)
  │
  ├─► lake.semantic.search(nl_question) — semantic match over catalog + metric defs + prior outcomes
  │       └─► returns ranked match + confidence
  │
  ├─► IF no_match (confidence < threshold):
  │       └─► lake.semantic.gap(nl_question, "no_match")
  │            └─► ledger: semantic_gap_proposed → admin metric-proposal workflow
  │
  ├─► lake.semantic.query_spec(spec) — agent_query (propose) starts here
  │       │
  │       ├─► governance gates inline (per §4.2)
  │       ├─► catalog-mirror validates + plans + compiles
  │       ├─► CredentialBroker issues scoped token
  │       ├─► execute against upstream
  │       │
  │       └─► IF error/empty:
  │            ├─► lake.query.suggest_correction(query_id, error)
  │            │    │
  │            │    └─► Router.call(call_type="agent_tool_reasoning", requested_by=agent_id, …)
  │            │         — Kimi reflects on execution feedback (per Dynamic-SQL / MAGIC pattern)
  │            │         — proposes refined QuerySpec
  │            │
  │            └─► agent retries up to N times (default N=3)
  │
  ├─► result returned to agent — agent_query (verify, resolve) lands
  │
  └─► lake.query.record_outcome(query_id, {used, useful, user_correction})
       └─► ledger: query_outcome_recorded
            │
            ├─► outcome quality score = used * useful * (no_correction ? 1.0 : 0.5)
            │
            └─► W5a Reactivity fires when ≥3 high-score outcomes cluster on same NL intent:
                 └─► ledger: query_template_promoted
                      └─► projection_query_templates row inserted
                           └─► next agent with similar NL question gets fast hit via lake.semantic.search
```

**Compounding properties:**

- **Outcome ledger feeds catalog hit-rate.** `projection_query_outcomes` includes embeddings of (nl_question, query_spec). `lake.semantic.search` searches it alongside the catalog.
- **Template promotion is autonomous.** Reactivity fires per the W5a runner pattern; no admin intervention required for high-confidence template promotion. Admin reviews flagged-low-quality outcomes.
- **Governance applies at every iteration.** Self-correction loops do NOT bypass governance gates — every retry is a fresh `agent_query` PEVR with full inline governance.
- **The audit trail is the model's reasoning trail.** Every retry, every correction, every outcome chains via `caused_by`. `/trace/agent_query/<id>` shows the full self-improvement journey.

**Two new projection tables** (Wave 2 schema):

```sql
projection_query_outcomes (
    id UUID PRIMARY KEY,
    agent_query_id UUID,             -- caused_by chain to the agent_query PEVR
    nl_question TEXT,
    final_query_spec JSONB,
    result_summary JSONB,            -- row count + top-N preview hash + latency
    used BOOL,                       -- did the agent use the result?
    useful BOOL,                     -- did the user accept the synthesis?
    user_correction TEXT NULL,       -- verbatim correction if user provided
    quality_score NUMERIC,           -- derived
    embedding VECTOR(1536),          -- for semantic search over prior outcomes
    recorded_at TIMESTAMPTZ
)

projection_query_templates (
    id UUID PRIMARY KEY,
    domain_id UUID,
    nl_intent TEXT,                  -- canonical NL form
    query_spec JSONB,                -- the spec that consistently works
    promoted_from_outcome_ids UUID[],-- provenance
    quality_score NUMERIC,
    hit_count INT,
    embedding VECTOR(1536),
    promoted_at TIMESTAMPTZ
)
```

**One new W5a Reactivity** (`OutcomeToTemplatePromotion`) — predicate: ≥3 outcomes with quality_score ≥ 0.9 cluster within embedding-distance threshold on same `domain_id`. Action: emit `query_template_promoted`. Composes with existing W5a runner.

**Positioning vs Palantir Ontology + Cube + dbt Semantic Layer:**

Those are **static**: admins / engineers define metrics; agents consume what's defined. WormBase is **compounding**: the layer learns from agent usage. By month 6, an agent's first query lands a metric template that didn't exist on day 1 — derived autonomously from prior agents' validated queries. **This is the institutional-AI moat the X zeitgeist is pricing into Palantir** (per Microsoft Foundry IQ, Databricks public concession, Dremio → SAP acquisition).

## §5. Lake-maintainer dual-mode composition (the load-bearing claim)

`Source` gains a single flag:

```python
@dataclass
class Source:
    id: SourceID
    kind: str
    domain_id: DomainID
    source_mode: Literal["wormbase_owned", "upstream_mirror"]   # NEW
    # ... existing fields
```

The 4 `MaintainableSource` methods route by `source_mode`:

| Method | wormbase_owned (existing) | upstream_mirror (NEW path) |
|---|---|---|
| `detect_drift` | bronze schema_hash vs prior baseline | external_catalog snapshot diff (baseline = last `external_catalog_imported`) |
| `refresh_classification` | classifier on sampled bronze rows | mirror upstream tags (read from external_policy projections), compose with WormBase classifier on top |
| `staleness_signal` | bronze last-write timestamp vs threshold | INFORMATION_SCHEMA last_altered / dbt manifest exposures freshness |
| `lineage_health` | walk projection_sources → silver → gold → KPI | walk imported lineage (from external_lineage projections) + WormBase-side consumption (decisions, agent queries) |

**Same Protocol, two implementations of each method.** Lake-maintainer doesn't need to know which mode it's in — the `Source` instance routes the call. W5a Reactivities (`make_lake_maintainer_reactivities`) already iterate the union of `Source` instances; they continue to work without modification.

This is the architectural test for whether dual-mode is real: if any of the 4 methods needs new code OUTSIDE the Source's own implementation to support upstream_mirror, the abstraction has leaked. Phase 0 spike S5 validates this empirically.

---

## §6. Ledger entry kinds (additive — 13 new, KIND_REGISTRY 83 → 96)

> **Amendment 2026-05-10:** the original 9 kinds (catalog-mirror 5 + agent-gateway 4) gain 4 more from the compounding-query-layer addition (§4.5): `query_outcome_recorded`, `query_correction_suggested`, `semantic_gap_proposed`, `query_template_promoted`. Total **13 new kinds**; KIND_REGISTRY 83 → **96**. The freeze-pause review per Wave F Addendum 1 must fire **BEFORE Wave 2** rather than as a Wave 1-side concern (was 92, comfortably under 100; now 96, at the doorstep). Risk #10 in §9 records this.

Per `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`: kinds are forever, additive-only, governed by Wave F Addendum 1.

### §6.1. New kinds

| # | Kind | Source package | Notes |
|---|---|---|---|
| 1 | `external_catalog_imported` | catalog-mirror | Initial mirror or refresh; `import_mode` field carries new/refresh; `snapshot_hash` for drift baseline |
| 2 | `external_catalog_drift_detected` | catalog-mirror | Signal — emitted when watch_changes / periodic discover_catalog detects schema/structure delta |
| 3 | `external_lineage_imported` | catalog-mirror | Lineage graph snapshot; column-level if available, else table-level |
| 4 | `external_policy_imported` | catalog-mirror | Upstream masking / row-access / ABAC policy mirror; read-only |
| 5 | `external_metric_imported` | catalog-mirror | Semantic-layer metric definition (dbt MetricFlow / Cube / Malloy / LookML) |
| 6 | `agent_registered` | agent-gateway | New Agent (Person sub-type with `kind=agent`); carries `external_agent_provider` (claude / gpt / kimi / internal-worm) |
| 7 | `agent_grant` | agent-gateway | Status field handles assign/revoke; covers BOTH data grants (domain/resource) AND model grants (which models, with budget); single entry kind avoids `agent_grant_revoked` duplication |
| 8 | `agent_query` | agent-gateway | PEVR cycle for the MCP boundary; written via `Ledger.write(propose=..., execute_fn=..., verify_fn=..., resolve_fn=...)`; one kind, four phases |
| 9 | `credential` | agent-gateway | Status field handles issue/revoke; covers BOTH data tokens (Snowflake/etc.) AND model tokens (Anthropic/OpenAI scoped); one kind, two capability axes |
| 10 | `query_outcome_recorded` | agent-gateway | Agent's post-query outcome (used / useful / user_correction); chains via `caused_by` to `agent_query`; feeds `projection_query_outcomes` for future semantic search and template promotion (per §4.5) |
| 11 | `query_correction_suggested` | agent-gateway | Backend's reflective suggestion for a failed query; emitted by `lake.query.suggest_correction` MCP tool; chains via `caused_by` to the failed `agent_query` |
| 12 | `semantic_gap_proposed` | agent-gateway | Agent-reported gap (no matching metric for an NL question); emitted by `lake.semantic.gap` MCP tool; populates the admin metric-proposal queue at `/lake/metrics-proposed` |
| 13 | `query_template_promoted` | agent-gateway | Cluster of high-quality outcomes promoted to a durable query template; emitted by the `OutcomeToTemplatePromotion` W5a Reactivity; feeds `projection_query_templates` |

**Reuses existing kinds**:

- `inference_served` — every LLM call lands here, internal or external. No new kind needed (this is the architectural payoff of §4.4).
- `chat_received` / `chat_reply_sent` — channel-driven flows unchanged.
- `source_proposed` / `source_confirmed` / `source_connected` / `source_profiled` — overlay-mode catalog imports MAY also write a `source_*` PEVR cycle if the customer wants the imported catalog tables to be queryable WormBase Sources; default behaviour is import-only (no Source rows), with `--auto-promote` flag to write Source PEVR for selected tables.

### §6.2. Doctrine compliance

- **Additive-only**: ✓ no kinds removed, no fields removed.
- **Status-field consolidation**: `agent_grant` and `credential` both use status fields rather than separate `_revoked` kinds — matches the consolidation pattern flagged in Wave F Addendum 1.
- **PEVR-for-observation**: `external_catalog_drift_detected` is a signal emission; emits one full PEVR cycle per signal (verify_fn always passes, resolve_fn always keeps) — matches lake-maintainer canonical reference.
- **KIND_REGISTRY threshold**: 83 → 92, comfortably under the raised ~100 ceiling. **Trigger the freeze-pause review per Wave F Addendum 1 BEFORE this implementation begins.** Non-blocking but explicit.

### §6.3. Projections

New projection tables (read-side materialization of the new kinds):

- `projection_external_catalog (id, source_id, snapshot_hash, schema_json, imported_at)`
- `projection_external_lineage (id, source_id, edges_json, imported_at)`
- `projection_external_policy (id, source_id, policy_kind, policy_json, imported_at)`
- `projection_external_metric (id, source_id, name, definition_json, imported_at)`
- `projection_agents (id, person_id, external_provider, registered_at, status)`
- `projection_agent_grants (id, agent_id, grant_kind, grant_target, status, budget_remaining_usd, granted_by, granted_at)`
- `projection_agent_queries (id, agent_id, mcp_tool, route_mode, status, cost_usd, latency_ms, caused_by, started_at)`
- `projection_credentials (id, agent_id, kind, target, ttl_expires_at, status, issued_at)`
- `projection_query_outcomes (id, agent_query_id, nl_question, final_query_spec, result_summary, used, useful, user_correction, quality_score, embedding, recorded_at)` — see §4.5
- `projection_query_templates (id, domain_id, nl_intent, query_spec, promoted_from_outcome_ids, quality_score, hit_count, embedding, promoted_at)` — see §4.5

Migrations: 10 new tables (was 8; +2 from the §4.5 amendment). Numbered v005..v014 in `packages/ledger/migrations/`. The two new tables require a vector extension (pgvector ≥0.6 in production; in-memory fallback in tests).

---

## §7. ASML demo arc (~3 minutes, 7/8 of the C1-C8 institutional-AI rubric)

Real Snowflake (or DuckDB-mocked-as-Snowflake for demo isolation) + real dbt project (`dbt-labs/jaffle_shop`) + WormBase deployed in overlay mode.

| Beat | Action | Wall-clock | Ledger writes | Rubric criteria |
|---|---|---|---|---|
| 1 | Admin in Slack: `@worm import dbt at github.com/dbt-labs/jaffle_shop` | ~30s | ~50 `external_catalog_imported` (one per model), ~30 `external_lineage_imported`, ~10 `external_metric_imported` | C1 (unprompted thereafter), C3 (compounding) |
| 2 | Dashboard `/lake/catalog` renders the imported schema; admin browses tables, sees descriptions, lineage, classifications mirrored from upstream | ~30s | (read-only) | C7 (domain specialized) |
| 3 | Admin: `Register agent claude_research with grants: domain.read(finance), model.access(claude, $5/day)` | ~15s | `agent_registered`, 2× `agent_grant` | C7 (domain ontology), C8 (prompted depth) |
| 4 | **Hero beat** — Claude Desktop with WormBase MCP server connected. User asks Claude: "What was Q3 EMEA revenue, and which decision drove the +12% spike?" → Claude calls `lake.semantic.metric("revenue_q3", region="EMEA")` (broker), `lake.lineage("revenue_q3", upstream)`, `worm.decisions.search("Q3 EMEA revenue")`, then synthesizes | ~60s | 3× `agent_query` PEVR, 2× `inference_served` (Claude API for synthesis), 1× `credential` (Snowflake JWT for broker query) | C2 (deterministic — same query, same hash on replay), C6 (auditable per-step) |
| 5 | Open `/trace/agent_query/<id>` — every step: tool call, gate fire, credential issuance, row hash, LLM call, cost. SOC-2-credibility view | ~30s | (read-only) | C6 (auditable) |
| 6 | **Governance proof** — admin revokes `domain.read(finance)` for claude_research. User asks the same question. Blocked at `AgentAccessGate`. Trace shows the block with reason. | ~30s | `agent_grant` (status=revoked), `agent_query` (resolved=denied, reason=missing_grant) | C6 (governance), C8 (auditability under-revocation) |

**Rubric coverage**: C1 ✓ C2 ✓ C3 ✓ C4 ✓ (drift detection runs autonomously in background), C6 ✓ C7 ✓ C8 ✓. C5 (metric-governed self-improvement) is not exercised by this arc — that's research-loop's domain, orthogonal to semantic-layer.

---

## §8. Phase 0 spike — empirical validation before full implementation

Per `feedback_research_then_empirically_validate.md`: never dispatch implementation without empirical GO. Spike output: `docs/superpowers/notes/2026-05-10-semantic-layer-phase-0-spike.md` with per-element GO/NO-GO decision.

| # | Validation | Subagent | Wall-clock | GO criteria |
|---|---|---|---|---|
| S1 | Parse a real dbt manifest (jaffle_shop) → `external_catalog_imported` entries with full schema + lineage + descriptions | general-purpose + Bash | 30 min | manifest.json fields → CatalogSnapshot schema lossless; round-trip test passes; lineage graph reconstructs |
| S2 | Read Snowflake INFORMATION_SCHEMA + ACCOUNT_USAGE + tags + masking-policies on a trial account | general-purpose + Bash | 45 min | column-level metadata mirrored; ≥1 masking policy mirrored as ExternalPolicy; OAuth token-issuance flow validated |
| S3 | In-process MCP client (`mcp` SDK) → FastMCP server tool round-trip + ledger PEVR assertion | general-purpose + Bash | 20 min | (a) tool advertised with correct schema, (b) tool call lands in WormBase, (c) `agent_query` PEVR (4 entries) appears in ledger with the test agent's AgentID, (d) `inference_served` PEVR appears chained to the `agent_query` (proves audit chain works end-to-end) |
| S4 | CredentialBroker Vault backend: hold + issue + revoke for BOTH data and model creds against same Vault instance | general-purpose + Bash | 30 min | `hold_data_account("snowflake")` + `hold_model_account("claude")` both return valid handles from one Vault instance; `issue_data_token` and `issue_model_token` both produce time-bounded tokens; revocation is observable |
| S5 | Lake-maintainer dual-mode toggle: `MaintainableSource` Protocol works for `upstream_mirror` without code changes outside the Source impl | Explore + Bash | 20 min | one test where 4 maintenance methods route to catalog-mirror reads; `make_lake_maintainer_reactivities` registers `upstream_mirror` Sources without modification; W5a Runner dispatches them identically to wormbase_owned |
| S6 | `Router` extension: add `ClaudeClient`, route an `agent_tool_reasoning` call to Claude, verify `inference_served` payload has `served_by="claude"` and `requested_by` carries AgentID | general-purpose + Bash | 20 min | Router accepts `requested_by: AgentID`, `governance_context: GovernanceContext`; `_DEFAULT_ROUTING["agent_tool_reasoning"] == "claude"`; `inference_served` payload includes the new fields; existing internal callers still work (backwards-compat test) |

**Total**: ~2 hrs 45 min subagent wall-clock. Fully autonomous (no human-in-the-loop config steps). S2 and S6 require API trial accounts (Snowflake trial, Anthropic API key) — these are credentials WormBase already has for development.

**Spike-to-implementation gate**: ALL six must return GO. Any NO-GO triggers a re-design round before any plan-writing. (Hermes spike 2026-04-27 is canonical: research said proceed-with-caveats, spike returned NO-GO, plan was reshaped.)

---

## §9. Risks + open questions

| # | Risk | Mitigation |
|---|---|---|
| 1 | KIND_REGISTRY 83 → 92, edge of raised threshold | Trigger freeze-pause review (Wave F Addendum 1 Option C) BEFORE implementation. Non-blocking but explicit; review may collapse other deferred kinds (Wave B.5's +2) into this batch. |
| 2 | Multi-tenant MCP — explicit gap in MCP spec | v1 ships single-tenant for ASML demo. v2 = subdomain routing or token-encoded tenancy (per 2026-04-27 MCP integration spec §1.7). |
| 3 | ASML stack assumption (dbt + Snowflake + Databricks) | Pre-demo: confirm with ASML contact what they actually run. Fallback: ship `generic_jdbc` CatalogSource that covers ANY JDBC source via INFORMATION_SCHEMA reads (lossy on lineage + policies but sufficient for catalog-only). |
| 4 | Broker-mode latency (+100-300ms per query) | Federate mode is the escape hatch; per-domain policy chooses. Document the latency budget in `/docs` so customers can pick consciously. |
| 5 | Federate-mode trust boundary | Federate is only safe when upstream IAM is strong (Unity Catalog ABAC, Snowflake row-access policies). For weak upstreams (raw S3, Postgres without RLS), default policy is broker-only; federate requires explicit per-resource opt-in. |
| 6 | OSS / closed-core split | `wormbase-catalog-mirror` is non-differentiated commodity (cataloging is everyone's table-stakes). Candidate for OSS publication. **Strengthened by OSI standard (Jan 2026)** — OSS catalog-mirror that reads/writes OSI is the open-ontology positioning shot vs Palantir's closed Foundry Ontology. `wormbase-agent-gateway` is the institutional-AI moat (audit + governance + identity + the §4.5 compounding loop) and stays closed core. **Decide before code lands** — affects license headers, public API surface, and the "WormBase reads every catalog" OSS narrative. |
| 7 | Existing internal-caller refactor cost (passing `requested_by: AgentID` everywhere) | Surface change is small (~5 callsites in chat-presence, ~3 in process-extractor, ~2 in voice-agent). Audit-clarity payoff is large. Wave 2 includes the refactor; backwards-compat shim accepts `requested_by: str` with deprecation warning for 1 release. |
| 8 | CredentialBroker for non-OAuth upstreams (Postgres, MySQL, etc.) | Federate mode falls back to time-limited proxy-issued credentials (issue, track usage, revoke on TTL). Documented as a separate capability flag on the `CredentialBroker` impl. |
| 9 | Cache key consistency under new `Router` fields | Existing `RouteRequest` is `frozen=True, slots=True` and used directly as cache key. Adding `requested_by: AgentID` and `governance_context: GovernanceContext` to the dataclass changes the cache key. Mitigation: explicit `cache_key_fields` allow-list on `RouteRequest` so the cache identity excludes governance + requester (those don't change the model output). Verify with S6 spike. |
| 10 | KIND_REGISTRY 83 → 96 (was 92 before §4.5 amendment) | At the doorstep of the raised ~100 freeze-pause threshold (Wave F Addendum 1). **Trigger freeze-pause review BEFORE Wave 2.** Consolidation candidates: (a) `query_outcome_recorded` could fold into `agent_query.resolve` phase — REJECT (different temporality: outcome lands AFTER user feedback, hours/days later); (b) `query_template_promoted` could be a status of `external_metric_imported` — REJECT (distinct provenance: WormBase-derived vs upstream-imported). Recommend raising the threshold to ~120 with explicit per-family caps (catalog-mirror ≤8, agent-gateway ≤8) so the doctrine has shape, not just a number. |
| 11 | OSI (Open Semantic Interchange) standard finalized Jan 2026, currently absent from spec | Defer to v1.1: `OSICatalogSource` impl reads OSI manifests; `catalog-mirror.export_osi(domain_id)` exports WormBase semantic layer to OSI-aware consumers. Strengthens OSS positioning for `wormbase-catalog-mirror` (per amended Risk #6). Tracked in §11. |

---

## §10. Implementation phasing (post-spike, post-plan)

Three waves, each ~6 hrs subagent wall-clock at ~3-way parallelism = ~3 calendar days. Per the project's empirical velocity calibration (`agentic_datasci/.claude/CLAUDE.md`).

### Wave 1: catalog-mirror foundation (~6 hrs)

- `CatalogSource` Protocol + types (`CatalogSnapshot`, `LineageGraph`, `ExternalPolicy`, `MetricDefinition`, `CatalogDelta`)
- `dbt_manifest` reference implementation
- `snowflake_native` reference implementation (depends on S2 GO)
- 5 new ledger entry kinds + 4 projection tables + migrations v005..v008
- `wire_catalog_for_install` lifecycle hook (becomes 5th wire in worm-core boot)
- W5a Reactivities for drift detection (`make_catalog_mirror_reactivities`)
- 100-150 tests
- Parallel subagents: (A) Protocol + types + tests, (B) dbt impl + tests, (C) snowflake impl + tests

### Wave 2: agent-gateway core + Router extension (~6 hrs)

- `CredentialBroker` Protocol + Vault impl + env impl (`aws_sm` + `customer_kms` deferred to v1.1)
- `Agent` identity (Person sub-type) + `agent_grant` model + `projection_agents` + `projection_agent_grants`
- `agent_query` PEVR helper (wraps `Ledger.write` with gateway-specific verify_fn / resolve_fn)
- `credential` lifecycle helper
- MCP server (FastMCP, extends 2026-04-27 MCP integration spec) — tools: `lake.catalog.tables`, `lake.semantic.metric`, `lake.lineage`, `lake.query` (federate), **plus the §4.5 compounding-loop tools**: `lake.semantic.search` (semantic match over catalog + outcomes), `lake.semantic.query_spec` (structured QuerySpec entry — primary front door per §3.5), `lake.query.suggest_correction` (reflective LLM call via Router for failed queries), `lake.query.record_outcome` (agent post-query feedback), `lake.semantic.gap` (agent-reported gap → metric-proposal queue)
- **`projection_query_outcomes` + `projection_query_templates`** schemas (require pgvector ≥0.6; in-memory fallback in tests)
- **`OutcomeToTemplatePromotion` W5a Reactivity** — fires when ≥3 high-quality outcomes cluster on same NL intent within embedding distance threshold
- broker/federate router (DATA queries only)
- governance gate composition (`AgentAccessGate`, classification, PII redaction, cost cap)
- **`Router` extension** in `packages/inference-router/`: `requested_by: AgentID`, `governance_context: GovernanceContext`, `_DEFAULT_ROUTING["agent_tool_reasoning"] = "kimi"`, cache key allow-list. **No new backend clients** — Kimi (Ollama Cloud) + Gemma (own VLAN) stay the only routed backends; external agents bring their own model and never route through WormBase Router (per §3.4 amendment 2026-05-10).
- **Existing-caller refactor**: chat-presence, process-extractor, voice-agent pass `requested_by=<their_internal_agent_id>` (backwards-compat shim for 1 release)
- 4 new ledger entry kinds (`agent_registered`, `agent_grant`, `agent_query`, `credential`) + 4 projection tables + migrations v009..v012
- `wire_agent_gateway_for_install` lifecycle hook (becomes 6th wire)
- 100-150 tests
- Parallel subagents: (A) CredentialBroker + Vault, (B) Agent identity + grants + audit, (C) MCP server + router, (D) Router extension + refactor (separate sub-wave because cross-package)

### Wave 3: dashboard + lake-maintainer dual-mode + ASML demo wiring (~6 hrs)

- Lake-maintainer `source_mode` flag + Protocol routing in 4 maintenance methods
- Dashboard surfaces:
  - `/lake/catalog` (browse imported schema, lineage, descriptions)
  - `/lake/governance` (mirrored policies + WormBase policies side-by-side)
  - `/people/agents` (Agent identity, grants, budget remaining)
  - `/trace/agent_query/<id>` (PEVR view of an agent's query with full causation chain to `inference_served` + `credential` + any `query_correction_suggested` retries)
  - **`/lake/query-improvement`** (per §4.5 amendment) — outcome ledger view, template library, retry chain visualization, semantic-gap queue
  - **`/lake/metrics-proposed`** (per §4.5 amendment) — admin queue for `semantic_gap_proposed` entries; admin promotes a gap → confirmed metric definition that flows back into `external_metric_imported`
- ASML demo seed: jaffle_shop dbt manifest fixture + claude_research agent registration + replay tape
- Demo script + recorded `wire-replay` for deterministic re-run
- Integration tests covering all 6 demo beats end-to-end (`tests/integration/test_asml_demo_arc.py`)
- Parallel subagents: (A) lake-maintainer dual-mode + tests, (B) dashboard surfaces, (C) demo seed + integration tests

**Total**: ~18 hrs subagent wall-clock = 3 calendar days. Reviews + integration time on top.

---

## §11. Out of scope (YAGNI)

Explicitly NOT in v1:

- **Multi-tenant MCP routing** (subdomain / token-encoded tenancy) — v2; v1 is single-tenant per ASML demo.
- **`databricks_uc`, `openmetadata`, `datahub`, `openlineage`, `iceberg_rest`, `atlas`, `glue` CatalogSource implementations** — v1 ships dbt + snowflake + the Protocol; community / customer-driven additions thereafter. The Protocol is the v1 deliverable; impls are 1-2 day adds each.
- **`aws_sm`, `customer_kms` CredentialBroker implementations** — v1 ships vault + env; AWS Secrets Manager + customer KMS are 1-day adds in v1.1 when first paying enterprise customer needs them.
- **dbt Semantic Layer / Cube / Malloy / LookML execution** — v1 imports metric DEFINITIONS; runtime metric execution wraps to existing Snowflake / Databricks SQL. Cube/MetricFlow runtime integration is v2.
- **OAuth 2.1 + RFC 9728 Protected Resource Metadata for MCP** — v1 ships Bearer token / API key auth (acceptable for v1 internal/private deployments per MCP integration spec §1.4); spec-compliant remote-server auth is v2 when first non-internal MCP client connects.
- **Agent budget enforcement at the upstream-IAM level** — v1 enforces budget at the WormBase ModelBroker proxy (issue-then-track). True upstream-enforced budget caps require provider-specific OAuth scopes that don't yet exist for most providers.
- **Streaming responses on MCP tools** — v1 ships unary tool calls; streaming is a v2 capability per the existing MCP integration spec.
- **OSI (Open Semantic Interchange) import/export** — per Risk #11. Standard finalized Jan 2026; first-class implementations still landing across vendors. v1.1 ships `OSICatalogSource` (reads OSI manifests) + `export_osi(domain_id)` (publishes WormBase semantic layer in OSI format). Net-new positioning for "WormBase reads/writes the standard."
- **Reinforcement-learning-from-outcomes (the strong form of the compounding loop)** — §4.5 ships outcome recording + template promotion. RL-style fine-tuning of the catalog-search ranker from `projection_query_outcomes` is v1.2 work — needs at least 90 days of accumulated outcomes per tenant before signal is sufficient.

---

## §12. Decision log (this brainstorming session, 2026-05-10)

| Q | Decision |
|---|---|
| Topology? | Dual-mode (overlay + SaaS), overlay-first build order |
| Query model? | Hybrid (broker + federate, per-policy choice) |
| Import scope? | Full mirror — schema + lineage + policy + semantic-layer |
| Architectural shape? | Two packages: catalog-mirror + agent-gateway |
| Catalog import targets v1? | Protocol-first; v1 ships dbt + snowflake reference impls + the `CatalogSource` Protocol; future technologies are class + registry adds |
| Credential model? | `CredentialBroker` Protocol — pluggable backends (vault, aws_sm, customer_kms, env), unified for data + model creds |
| MCP wire spike? | Programmatic — `mcp` SDK client in pytest, no Claude Desktop manual config |
| LLM-pattern compartmentalization? | Dissolved — `agent-gateway` is a thin MCP wire; LLM invocation flows through the existing `Router` Protocol; `CredentialBroker` covers BOTH data and model creds; one identity model, one audit chain (`agent_query` → `inference_served`), two backends (kimi via Ollama Cloud, gemma via own VLAN) — external agents bring their own model and never route through WormBase Router (amendment 2026-05-10 superseded the earlier "four backends" draft) |
| Agent-facing query primitive? | **Amendment 2026-05-10 (research synthesis):** `QuerySpec` Protocol (§3.5) — agents submit structured intent, NOT raw SQL, against the catalog. Raw SQL stays available in federate mode (escape hatch). Per @zygisSS22 verbatim + Cube/dbt/Palantir convergence + 85%→10.8% accuracy collapse on raw text-to-SQL. |
| Self-improving query layer? | **Amendment 2026-05-10 (research synthesis):** §4.5 names PEVR as the academic propose→execute→reflect→retry loop; adds outcome recording + template promotion as the compounding edges. Differentiates from static semantic layers (Palantir / dbt / Cube). Karpathy "compounding state" anchor. +4 entry kinds, +2 projection tables, +1 W5a Reactivity, +5 MCP tools. KIND_REGISTRY 83 → 96. |
| OSI (Open Semantic Interchange)? | **Amendment 2026-05-10:** standard finalized Jan 2026; tracked as v1.1 deliverable (Risk #11 + §11). `OSICatalogSource` impl + `export_osi()` exporter. Strengthens OSS positioning for catalog-mirror. |

---

## §13. References

- `Projects/wormbase/CLAUDE.md` — durable architectural commitments (§§1-11)
- `docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md` — Connector / ChannelAdapter / Roles
- `docs/superpowers/specs/2026-04-27-mcp-integration.md` — MCP wire framing, transport choices, FastMCP, multi-tenant gap
- `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` — Five rules + Wave F Addendum 1 (KIND_REGISTRY threshold)
- `docs/superpowers/notes/2026-05-02-lake-maintainer-phase-0-spike.md` — Protocol split + W5a composition pattern
- `packages/inference-router/src/wormbase_inference/protocol.py` — existing `Router` Protocol (extended in Wave 2)
- `packages/connectors/src/wormbase_connectors/base.py` — `Connector` Protocol (template for `CatalogSource`)
- `packages/lake-maintainer/` — `MaintainableSource` Protocol (extended with source_mode)
