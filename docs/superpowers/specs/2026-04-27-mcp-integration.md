# WormBase × MCP Integration — Strategic Research + Phased Spec

> **Author:** Claude (research subagent, 1M context).
> **Date:** 2026-04-27.
> **Frame requested:** thorough research + a research-grade spec for a **bidirectional** MCP integration layer.
> **Inputs read:** `Projects/wormbase/CLAUDE.md`, `docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md` (§2 Connector, §5 Roles), `docs/superpowers/notes/2026-04-27-business-audit.md`, `docs/superpowers/notes/2026-04-27-product-validation-gaps.md`, user memory notes (`feedback_data_products_first_class.md`, `feedback_research_then_empirically_validate.md`), `packages/connectors/src/wormbase_connectors/base.py`, `packages/channel-adapters/src/wormbase_channel_adapters/base.py`.
> **Output discipline:** spec only. No code edits. No task-level breakdown. Phase outlines only. Empirical-spike flags called out per `feedback_research_then_empirically_validate.md` — the user wants research depth AND a clear "what would I have to verify on a workbench before committing engineering hours" answer per phase.
> **Length target:** ~600-700 lines.

---

## §0. Headline framing

**The thesis:** WormBase already speaks the MCP grammar at the architectural level — it just doesn't speak the MCP wire protocol. The Connector Protocol (`authenticate / discover / profile / sample / watch`) is essentially a domain-specialized superset of MCP's `list_resources / read_resource`. The ChannelAdapter Protocol (`authenticate / install / listen / send`) is essentially MCP-without-tools-because-Slack-isn't-a-tool. Adding MCP is therefore a **wire-protocol adapter, not an architectural rewrite** — and that's the cheapest leverage in the codebase.

The strategic prize is bigger than the engineering cost. MCP-native institutional AI is an unclaimed wedge: every other "AI for the data function" vendor (Atlan, Glean, Hex, Monte Carlo, dbt Cloud) has shipped an MCP **server** in the last 6 months — but none of them ship an MCP **server + audited ledger of every external query** as one product. WormBase already has the ledger; making it the audit trail for every AI agent that ever touched org data is a 1-2 week build with a 5-year defensibility window.

This spec maps the territory in 10 dimensions, then proposes a 5-phase adoption plan starting with a 1-day spike to verify the round-trip works.

---

## §1. MCP fundamentals (April 2026 state)

### §1.1. Protocol version + maturity

The current spec is **2025-03-26**, with a draft for the next revision in active development under the **2026 MCP Roadmap** published March 2026. JSON-RPC 2.0 over one of three transports. Anthropic published v0.1 in November 2024; the protocol entered API freeze (v0.1) at registry level in October 2025 and has matured to first-class support across most major AI clients through 2026.

### §1.2. Transports

| Transport | Status (Apr 2026) | When to use |
|---|---|---|
| **stdio** | Stable, default for local | Local-process servers; CLI agents; Claude Desktop add-ins |
| **Streamable HTTP** | **Recommended for remote** (replaced HTTP+SSE) | Production multi-tenant servers; horizontal scaling behind load balancers |
| HTTP+SSE | **Deprecated** | Legacy compatibility only |

The 2026 roadmap explicitly evolves Streamable HTTP for **stateless** operation across multiple server instances, with session creation/resumption/migration during scale-out and standardized **MCP Server Cards** for metadata discovery. This matters for WormBase: a hosted multi-tenant MCP server fits the Streamable HTTP statelessness model directly; deferring stdio entirely is reasonable for a v1.

### §1.3. Three primitives

| Primitive | Control | Purpose |
|---|---|---|
| **Tools** | Model-controlled (LLM picks) | Executable actions — query, propose, write |
| **Resources** | Application-controlled (host attaches) | Read-only context — files, records, streams |
| **Prompts** | User-controlled (user invokes) | Reusable templates that combine tool calls + resources into a workflow |

Distinction matters for governance: **resources are passively included**, **tools are actively invoked**, **prompts are user-curated workflows**. WormBase's audit story differs across all three (a resource read is implicitly logged; a tool call is explicitly logged; a prompt invocation is logged at the prompt-template level + per tool call).

### §1.4. Authn/authz model

- **Spec-mandated for remote HTTP servers:** OAuth 2.1 with PKCE + RFC 9728 Protected Resource Metadata + RFC 8707 Resource Indicators.
- **Spec-mandated for local (stdio):** none — process-level trust.
- **Bearer-token / API-key** is widely used in practice but is technically out-of-spec for public remote servers (acceptable for v1 internal/private deployments).
- **Multi-tenant story:** **explicit gap in the spec.** The 2026 roadmap calls for an Enterprise Working Group to address this; today, multi-tenancy is DIY (subdomain routing, token-encoded tenant IDs, path-encoded tenancy, or gateway-level tenancy translation).

### §1.5. SDK coverage

- **TypeScript:** `@modelcontextprotocol/sdk` (npm), official, stable.
- **Python:** `mcp` (PyPI), official, **FastMCP 3.0** released January 2026 brings component versioning, authorization controls, and OpenTelemetry integration.
- **Go, Rust, Java, C#:** community / experimental.

For WormBase, the FastMCP path is the obvious match — Python first, TypeScript SDK if a future Next.js dashboard tab needs to act as an MCP client.

### §1.6. Rate-limiting + observability

- **Rate-limiting:** **NOT in the spec.** Implementation pattern in production servers: token bucket / sliding window per-client, per-tool weights, cost-based limits. IBM ContextForge and Kong AI MCP Proxy ship rate-limiting at the gateway layer.
- **Observability:** **NOT in the spec.** Production pattern: OpenTelemetry tracing + standard OTLP backends (Phoenix, Jaeger, Zipkin). FastMCP 3.0 ships first-class OTel integration.

For WormBase: **the ledger is the observability primitive.** Every MCP call writes a ledger entry; the ledger replaces (or supplements) OTel for institutional-AI use cases. This is on-thesis with the principle "TRACE is the substrate, not a side-channel."

### §1.7. Multi-tenant readiness — the honest answer

**MCP is not yet enterprise-multi-tenant by spec.** Servers in the wild handle this via:
1. **Subdomain routing** — `tenant1.mcp.example.com`, `tenant2.mcp.example.com`. Used by Atlassian Rovo.
2. **Token-encoded tenant** — the OAuth access token carries the tenant claim; server enforces.
3. **Path-encoded tenancy** — `/api/v1/tenants/{id}/mcp`. DIY.
4. **Gateway-level tenancy** — an MCP gateway (ContextForge, Kong) handles tenancy upstream of the MCP server itself.

WormBase's existing `company_id` scope makes path-encoded or token-encoded tenancy the natural pick; a gateway is overkill for v1 but a clean v3 upgrade path.

---

## §2. MCP server landscape (April 2026)

The ecosystem grew from ~1,500 servers (Q4 2025) to **22,000+ in the Glama registry, 12,970+ in PulseMCP** by April 2026 — with 8 million SDK downloads and 85% MoM growth. Less than 5% are monetized; the vast majority are open-source utilities. Below is a curated, opinionated map of what matters for WormBase.

### §2.1. Critical-for-WormBase servers

| Vendor | Server | Auth | Maintenance | Coverage |
|---|---|---|---|---|
| **Slack** (Salesforce) | Official, GA Feb 2026 | OAuth 2.1 | Active | Search, retrieve messages, send, manage canvases. Supersedes Anthropic's reference Slack server (now Zencoder-maintained). |
| **Atlassian** | Rovo MCP, GA Feb 2026 | OAuth 2.1 + API token | Active (vendor) | Jira issues + Confluence pages: search, create, update, link. Hosted on Cloudflare. SSE endpoint deprecates June 30 2026 → migrate to `/v1/mcp`. |
| **Notion** | Official, GA 2026, v2.0.0 (Notion API 2025-09-03) | OAuth | Active (vendor) | 18 tools — search-and-content focused. **Limitation: human-present required; not designed for unattended agentic flows.** |
| **GitHub** | Official, hosted by GitHub | OAuth 2.1 | Active (vendor) | Repos, issues, PRs, files. |
| **Linear** | Official remote (mcp.linear.app), GA early 2026 | OAuth 2.1 | Active (vendor) | Initiatives, milestones, updates, issues, teams. SSE endpoint deprecated; use `/mcp`. Stability fixes April 2026. |
| **Google Workspace** | Official, GA Cloud Next 2026 | OAuth 2.1 | Active (vendor) | Gmail (10 tools), Drive (7), Calendar (8), People (3), Chat (2). Preview in Q1 2026. |
| **HubSpot** | Official remote, GA April 13 2026 | OAuth 2.1 | Active (vendor) | CRM read+write for Contacts/Companies/Deals/Tickets/Line items/Products + read-only campaigns/landing pages. New self-service "MCP Auth Apps" tool. |
| **Salesforce** | **Not yet public — restricted to Agentforce** | n/a | n/a | Closed via vendor; community alternatives exist but are unofficial. |
| **Postgres** | Anthropic reference (`@anthropic/mcp-server-postgres`) | conn-string | Reference; community-maintained | Schema discovery + read queries. |
| **Snowflake** | Official Cortex MCP integration | OAuth + Snowflake creds | Active (vendor) | Query + Cortex AI features. |
| **BigQuery** | LucasHild/mcp-server-bigquery (community) | service account | Active (community) | Schema browse + run queries. |
| **Databricks** | Official, governance-first | OAuth | Active (vendor) | Lakehouse + catalog read. |
| **Monte Carlo** | Official, private preview | API key | Active (vendor) | `getAlerts`, `getTableLineage`, `search`. **Direct competitor in the same observability/lineage MCP slot.** |
| **Atlan** | Official MCP server | OAuth | Active (vendor) | Asset search, lineage tracing, DSL queries, metadata writes. **Direct competitor.** |
| **Glean** | Official remote MCP | OAuth | Active (vendor) | Enterprise search + actions. **Direct competitor in the "AI knowledge over org" slot.** |
| **dbt Cloud** | Official remote dbt MCP, GA Coalesce 2025 | OAuth | Active (vendor) | Semantic-layer query + model context. **Direct competitor on the data-engineer persona.** |
| **Filesystem** | Anthropic reference | local | Reference | Sandboxed FS browse/read/write. |
| **Fetch** | Anthropic reference | none | Reference | Web fetch + clean. |
| **Exa** | Community (most-used search MCP in 2026) | API key | Active | Semantic web search for agents. |

### §2.2. Quality + coverage rating

Tier-1 (official, vendor-maintained, OAuth 2.1, production-ready): Slack, Atlassian, Notion, GitHub, Linear, Google Workspace, HubSpot, dbt Cloud, Atlan, Glean, Snowflake.

Tier-2 (official but limited, or vendor-restricted): Salesforce (Agentforce-only), Monte Carlo (private preview).

Tier-3 (community / reference): Postgres, BigQuery, Filesystem, Fetch, Exa.

**Implication for WormBase inbound:** the "obvious 6" sources to ingest first via MCP are **Notion, Atlassian (Jira+Confluence), Linear, GitHub, Google Workspace, HubSpot** — all Tier-1, all OAuth 2.1, all GA. Each has a "bronze conversation" or "bronze artifact" analogue that maps cleanly to WormBase's medallion pipeline. Atlassian + Notion + Google Drive are the three that most-directly enrich the **conversation lake** with adjacent doc/decision context.

### §2.3. Where the "obvious" overlap is competitive

dbt Cloud, Atlan, Glean, Monte Carlo all ship MCP servers in the **same conceptual slot** WormBase would target outbound. The direct question: does MCP-native institutional-AI have room when these vendors are already there?

**Yes — because WormBase's MCP server exposes a fundamentally different shape**: not "ask my catalog" but "ask my company's hash-stable ledger of decisions, processes, KPIs, conversations, AND data." Atlan's MCP exposes data context; Glean's MCP exposes search; WormBase's MCP would expose **the organizational truth ledger** — broader, deeper, audit-complete. The other vendors stop at metadata; WormBase goes through to the bytes that produced the metadata.

---

## §3. MCP client landscape (April 2026)

### §3.1. The clients that matter

| Client | MCP-aware? | Notes |
|---|---|---|
| **Claude Desktop** | Yes (native) | Reference client; first-class MCP support. |
| **Claude Code** | Yes | The orchestrator's daily driver; MCP servers register via project config. |
| **Cursor** | Yes (40-tool cap per config) | Fastest IDE-AI; 45s vs 90s on tasks vs alternatives. |
| **VS Code (GitHub Copilot)** | Yes (native MCP support) | Public + enterprise tenants. |
| **Cline** | Yes (no tool cap) | 2026 hybrid pattern: Cline-in-VS-Code for heavy MCP, Cursor for daily completions. |
| **Continue** | Yes | OSS, free. |
| **Windsurf** | Yes | Codeium IDE. |
| **Devin** | Yes | Cognition; agent-of-agents pattern. |
| **Codename Goose** | Yes | Block's open-source agent. |
| **Zed** | Yes | OSS editor with MCP. |
| **Replit, ChatGPT, Gemini CLI** | Yes | Variable maturity. |

### §3.2. Headless / programmatic clients

- TypeScript: `@modelcontextprotocol/sdk` for client + server.
- Python: `mcp` package; FastMCP for server, `mcp.client.session.ClientSession` for client.
- Both support stdio + Streamable HTTP transports.

### §3.3. Enterprise pattern: shared MCP gateway

The dominant enterprise pattern (observed at Cloudflare's reference architecture, IBM ContextForge, Kong AI MCP Proxy, MintMCP) is:

```
[ Many MCP clients ] → [ MCP Gateway ] → [ Many MCP servers ]
                            ↓
                    auth / rate-limit /
                    audit / federation
```

The gateway centralizes OAuth, rate-limits, audits, and federates discovery. **For WormBase: don't build a gateway in Phase 1.** Use one of the existing gateways (ContextForge is OSS) when scale demands it. Phase 0-3 ship a direct-access MCP server; Phase 4+ adds gateway-fronting as an option for enterprise tenants.

---

## §4. WormBase-as-MCP-server — outbound surface design

The thesis: a single hosted MCP server endpoint per tenant, exposing tools + resources + prompts that an external LLM client can call. Every call writes a ledger entry. Role-aware filtering on every read.

### §4.1. Tools (MVP-tagged where shipped in Phase 1)

Read tools (model-controlled queries):

| Tool | Args | Returns | Phase |
|---|---|---|---|
| `query_ledger` | `company_id, since?, kinds?, limit?` | List of redacted/role-filtered ledger entries | **MVP** |
| `query_kpis` | `company_id, domain?` | KPI tree current state | **MVP** |
| `query_decisions` | `company_id, since?` | Extracted decisions | **MVP** |
| `query_processes` | `company_id, domain?` | Process maps | **MVP** |
| `query_data_products` | `company_id, kind?, requested_by?` | Block F artifacts (notebooks, reports, dashboards) | **MVP** |
| `query_notebooks` | `company_id, owner_person_id?` | Block F notebooks | MVP |
| `query_conversations` | `company_id, channel_id?, since?, limit?` | Bronze conversations (role-filtered) | **MVP** |
| `query_audit_trail` | `company_id, person_id?, resource_id?` | Governance traces | follow-up |
| `query_sources` | `company_id, kind?` | Connected source list with classification | follow-up |
| `query_people` | `company_id, role?` | Roster (with role-aware visibility) | follow-up |
| `query_recurring_questions` | `company_id, channel_id?` | The "x4 'what's Q3 revenue'" panel content | follow-up — but **demo gold** |

Write tools (model-controlled actions, all gated):

| Tool | Args | Returns | Phase |
|---|---|---|---|
| `propose_data_product` | `company_id, name, kind, parameters` | `proposal_id` (creates `propose` ledger entry; worm processes async) | **MVP** |
| `propose_kpi` | `company_id, name, formula, owner_domain` | `proposal_id` | follow-up |
| `propose_source` | `company_id, kind, connection_url` | `proposal_id` | follow-up |
| `confirm_proposal` | `company_id, proposal_id, person_id` | `confirmed` ledger entry | follow-up |
| `discard_proposal` | `company_id, proposal_id, person_id, reason` | `discarded` ledger entry | follow-up |

All write tools enforce role-grants: `propose_*` requires `tenancy.member`; `confirm_*`/`discard_*` requires `domain.owner` or `tenancy.admin`.

### §4.2. Resources (URI-addressable read context)

| URI | Content | Phase |
|---|---|---|
| `wormbase://ledger/{company_id}/recent` | Stream of last N ledger entries (role-filtered) | **MVP** |
| `wormbase://kpis/{company_id}/tree` | Current KPI tree as JSON | **MVP** |
| `wormbase://decisions/{company_id}/{decision_id}` | Single decision detail with full provenance | **MVP** |
| `wormbase://data-products/{company_id}/{data_product_id}` | Artifact bytes (HTML/JSON; for notebooks, the rendered HTML) | **MVP** |
| `wormbase://conversations/{company_id}/channels/{channel_id}` | Recent messages (role-filtered) | **MVP** |
| `wormbase://processes/{company_id}/{process_id}` | Process map JSON + diagram | follow-up |
| `wormbase://people/{company_id}/{person_id}` | Person record with role grants | follow-up |
| `wormbase://lake/{company_id}/{table_id}/sample` | Bronze/silver sample bytes | follow-up |

### §4.3. Prompts (shareable templates)

| Prompt | Composition | Phase |
|---|---|---|
| `summarize_company_state` | Pulls KPIs + recent decisions + outstanding proposals + activity-since-yesterday | follow-up |
| `audit_decision` | Walks a decision back → process → KPIs → source bytes → bronze hash | follow-up — **but the H7 killer demo** |
| `daily_digest` | Per-Person daily worm-activity digest (uses role to scope) | follow-up |
| `prep_meeting` | Given an upcoming meeting (from Calendar MCP inbound), pull relevant KPIs + decisions + recent threads | Phase 4+ |

### §4.4. MVP cut summary

Phase 1 ships **7 tools (5 read + 2 write) + 5 resources + 0 prompts** → this is the smallest set that exercises every architectural pattern (read, write, governance, redaction, audit) without bloat. Phase 2 adds the inbound. Phase 3 adds the role-aware redaction polish + remaining read tools. Phase 4 adds prompts + the Decision-Provenance audit prompt that's the H7 demo gold.

---

## §5. Authn/authz design — multi-tenant + role-aware

### §5.1. The constraint

WormBase has **three role facets per `tenancy / domain / resource`** (per PRD §5). MCP needs to:

1. Authenticate the caller as a **Person within a tenant**.
2. Apply **role-aware filtering** on every read (member sees fewer rows than admin; observer sees redaction overlays; non-domain-owner sees `[classified: pii]` placeholders for PII columns).
3. **Audit-log every call** as a ledger entry, regardless of read or write.

### §5.2. v1 auth — bearer token, simple but secure

For Phase 1 (private deployments + dogfooding), ship a **bearer-token model**:

```
Authorization: Bearer wb_<env>_<company_id>_<person_id>_<random>_<hmac>
```

- Token is generated in the dashboard `/settings/tokens` (new tab, ~half-day to ship).
- Token-encoded `company_id` + `person_id`; HMAC over the tail prevents tampering.
- Token can be scoped (read-only vs read-write) at issue time.
- Stored as a salted hash in `projection_tokens`; revocation = `emit_token_revoked` ledger entry.

This is **out-of-spec for public remote MCP servers** but is fine for v1 + private demos + customer pilots where the customer's Claude Desktop connects to their own WormBase tenant.

### §5.3. v2 auth — OAuth 2.1 with PKCE + Resource Indicators

For public remote (Phase 4+), upgrade to OAuth 2.1 per spec:

- **MCP server acts as OAuth 2.1 Resource Server** — emits `protected_resource_metadata` per RFC 9728.
- **Authorization server can be WormBase's existing identity layer** (the same Person model) — new `/oauth/authorize` + `/oauth/token` endpoints in the dashboard.
- **Resource Indicators (RFC 8707)** prevent token misuse across multiple MCP servers.
- **PKCE mandatory** for all browser-based clients (Claude Desktop, etc).

This is comparable to Atlassian Rovo's pattern (OAuth 2.1 + API token both supported; OAuth for hosted, token for power users / CI).

### §5.4. Multi-tenant routing

Three options; pick **token-encoded tenancy** for v1, migrate to **path-encoded** for v2.

| Option | Pros | Cons | When |
|---|---|---|---|
| Subdomain (`tenant1.mcp.wormbase.io`) | Industry standard; clean separation; TLS sni works | Wildcard cert + DNS automation needed | v3, when we have ≥10 tenants |
| **Token-encoded** | Trivial to implement; no DNS/cert work | Single endpoint = single point of misconfig | **v1** |
| Path-encoded (`/api/v1/tenants/{id}/mcp`) | Explicit; debuggable | Tenant ID leaks in URLs (low-risk for non-secret IDs) | v2 |
| Gateway (ContextForge fronting) | Industry-standard enterprise pattern | Operational complexity | v3+ enterprise |

### §5.5. Role-aware filtering — the substrate

Every read tool calls a single helper:

```python
async def role_filter(person: Person, tenant: Tenant, query: Query) -> FilteredQuery:
    """Apply role-aware visibility to a ledger query.

    - tenancy.observer: read-only; redaction overlay on classified.{pii,regulated}
    - tenancy.member: hides domains where person has no domain-grant
    - tenancy.admin: full visibility within tenant
    - cross-tenant: always denied
    """
```

This is the **same role-grant join** the dashboard uses for `useNavForRole` — reused, not duplicated. PRD §5 already specifies the join shape.

### §5.6. Audit-log every call — the ledger entry shapes

Two new entry types:

```python
emit_mcp_call_received {
    company_id: UUID
    caller_person_id: UUID  # resolved from token / OAuth claim
    caller_client: str      # "claude_desktop" | "cursor" | "<custom>"
    tool_name: str | None
    resource_uri: str | None
    args_hash: str          # hash of args, full args stored offline if classified
    classification: Classification  # min over args
    ts: datetime
}

emit_mcp_call_resolved {
    call_id: UUID
    status: "ok" | "denied" | "rate_limited" | "error"
    rows_returned: int | None
    output_hash: str | None
    output_classification: Classification | None
    duration_ms: int
    ts: datetime
}
```

**Critical privacy property:** the call audit can itself be classified (a deny on a PII query reveals existence of PII data). Apply classification min-cap to audit visibility — observers see `<call denied>` not `<call denied for query containing email "ricardo@…">`.

---

## §6. WormBase-as-MCP-client — Connector vs MCP

### §6.1. The three options

The Connector Protocol (`packages/connectors/base.py`) is the existing source-ingestion contract. MCP servers offer a comparable read surface (`list_resources / read_resource / call_tool`). Three integration paths:

#### Option A — **MCP REPLACES Connector**

Rip-and-replace. Every source becomes an MCP-fronted source. The 14 existing connectors become MCP servers internally; the lake-builder calls MCP on every source.

- **Pros:** one integration substrate; matches industry direction; gateway upgrade is trivial.
- **Cons:** **massive backwards-incompatibility cost.** Existing 14 connectors (`csv_local`, `postgres`, `stripe`, etc.) need MCP-server wrappers. The Connector Protocol carries domain semantics (Capability, ClassificationHint, ResourceProposal, Profile, Change) that MCP doesn't have. Lossy conversion. Reactive `watch` semantics don't map naturally to MCP — MCP is request/response, not stream-subscribe (until elicitation/tasks land).
- **Recommendation:** **NO.** The Connector Protocol is too domain-rich to throw away.

#### Option B — **MCP SUPPLEMENTS Connector** (parallel substrates)

Keep Connector for "owned" sources (Postgres, S3, etc.); add a parallel MCP-source path for external MCP servers (Notion, Atlassian, Linear, etc.). The lake-builder routes per-source-kind.

- **Pros:** zero existing-code disruption; MCP gets its own optimized path.
- **Cons:** two substrates means two flow surfaces, two governance paths, two registry tables. Violates the "one Connector contract, no core changes ever" principle in PRD §2.
- **Recommendation:** Sub-optimal but workable as a stopgap.

#### Option C — **MCP IS ONE Connector implementation** (recommended)

Add `MCPConnector(Connector)` to `packages/connectors/`. It implements the Connector Protocol by speaking MCP under the hood. From the rest of the codebase's perspective, an MCP-backed source is indistinguishable from a Postgres source — same `discover/profile/sample/watch`, same registry, same flows.

- **Pros:** zero core changes (PRD §2 invariant preserved); zero new flows; existing flows (`drop_and_profile`, `credential_in_dm`, `mentioned_in_conversation`, `dashboard_form`, `kpi_gap_triggered`, `lake_discovery`) just work; pluralism in the registry (an admin can see "Notion via MCP" and "Notion via REST" side-by-side and pick).
- **Cons:** the `MCPConnector` class needs config (which MCP server URL? which auth?). Per-MCP-server subclassing or per-server JSON-config — pick config.
- **Recommendation:** **YES.** This is the cheapest, most architecturally-coherent path.

### §6.2. `MCPConnector(Connector)` sketch

```python
# packages/connectors/src/wormbase_connectors/mcp.py

class MCPConnector:
    """A Connector backed by an MCP server.

    Configured per-instance with an MCP server URL + auth.
    Maps MCP list_resources -> Connector.discover,
         MCP read_resource -> Connector.sample,
         MCP call_tool       -> Connector.profile (for "describe"-style tools)
                              + Connector.watch (for resource-subscribe, when supported).

    classification_hints come from an MCP "tool annotation" extension or
    are manually configured in the MCPConnector's JSON config.
    """

    kind = "mcp"  # generic; per-server kinds are e.g. "mcp:notion", "mcp:atlassian"
    capability = {Capability.discover, Capability.sample}
    classification_hints: list[ClassificationHint]
    status = ConnectorStatus.preview  # Phase 2 ships in preview
    status_note = "Connect to any MCP server. OAuth or bearer-token."

    def __init__(self, server_url: str, auth: MCPAuth, config: dict):
        ...

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        """OAuth 2.1 dance OR bearer-token verify. Returns an AuthHandle
        that wraps the MCP ClientSession."""
        ...

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        """list_resources() + list_tools() → ResourceProposal[]"""
        ...

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        """read_resource() → schema inference; or call_tool('describe_*') if available."""
        ...

    async def sample(self, handle: AuthHandle, resource_id: str, n: int) -> bytes:
        """read_resource() with pagination → bytes."""
        ...

    def watch(self, handle: AuthHandle, resource_id: str) -> AsyncIterator[Change]:
        """Until MCP elicitation/tasks land, yields nothing (pull-only).
        Once available, subscribes to resource_updated notifications."""
        async def _empty():
            return
            yield  # pragma: no cover
        return _empty()
```

A registry pattern lets per-server presets register as kinds:

```python
register_connector("mcp:notion", lambda cfg: MCPConnector(
    server_url="https://mcp.notion.com",
    auth=MCPAuth.OAuth(client_id=cfg["client_id"]),
    classification_hints=[
        ClassificationHint(pattern="email", classification="pii"),
        ...
    ],
))
register_connector("mcp:atlassian", ...)
register_connector("mcp:linear", ...)
register_connector("mcp:github", ...)
register_connector("mcp:google_workspace", ...)
register_connector("mcp:hubspot", ...)
```

Each preset is **~30 LOC** (URL + auth + hints). Six of these = 180 LOC + the MCPConnector base = ~400 LOC total for **6 new sources** wired into the lake. This is the unique velocity unlock MCP delivers.

### §6.3. What changes for the existing 14 connectors

**Nothing.** They keep their kind (`csv_local`, `postgres`, `stripe`, etc.) and their direct-API implementation. The `MCPConnector` lives alongside them. A future cleanup pass can rewrite some as `mcp:postgres` etc. once Anthropic's reference servers stabilize, but that's a v3 nice-to-have, not a v1 commitment.

### §6.4. What about reactivity?

`watch` is the gap. MCP is request/response (until elicitation/tasks lands per the 2026 roadmap). For now, `MCPConnector.watch` returns an empty async iterator; reactivity for MCP-backed sources is **polled** by `lake_discovery` cron rather than push-driven. Acceptable for v1; flag as a v3 watchpoint as MCP elicitation matures.

---

## §7. ChannelAdapter vs MCP

### §7.1. The question

Are there MCP servers for chat platforms that could replace `SlackChannelAdapter` / `DiscordChannelAdapter` / `TeamsChannelAdapter`?

### §7.2. The answer

**Slack's official MCP server exists** (GA Feb 2026, Salesforce-maintained). It provides search-message, retrieve-message, send-message, manage-canvas. Atlassian Rovo includes a chat-adjacent surface. Google Chat is in the Workspace MCP server (2 tools).

But: **MCP servers for chat are pull-based query surfaces, not push-based event firehoses.** They don't replace `ChannelAdapter.listen()` — there's no `await for event in mcp_chat.listen()` pattern in MCP today. Elicitation in the 2026 roadmap moves the protocol toward server-initiated messages, but it's not a full event subscription.

### §7.3. Architectural risk parallel to Hermes/OpenClaw

Per the user's directive (Hermes spike was NO-GO): MCP-as-channel-replacement carries the **same architectural risks**:
- **Event-emit semantics** — MCP doesn't natively support "for every new Slack message, emit". You'd poll. Polling vs. real-time changes the latency and KPI-tree-firing characteristics.
- **Hook coverage** — Slack RTM events (file_shared, reaction_added, edit, thread_reply) are not 1:1 with the Slack MCP tool surface. The MCP server is a *query surface over Slack's REST API*, not a streaming firehose over Slack's RTM/Events API.
- **Send semantics** — `chat.postMessage` works in MCP, but file_upload v2 with the Slack-bot's specific permissions is a brittle integration today.

**Recommendation: NO replacement.** Keep `SlackChannelAdapter` / `DiscordChannelAdapter` / `TeamsChannelAdapter` as-is — they're the production wire. **Use MCP for channel data on the inbound side as a SUPPLEMENT** (e.g., a customer's pre-existing Slack archive can be backfilled via Slack MCP server tools) but never as the primary live wire.

This matches the Hermes finding pattern: MCP-as-channel-substrate is architecturally appealing but unproven for the "every message must emit" loop. Defer until elicitation/tasks land + a customer specifically requests it.

---

## §8. Governance + audit — every MCP call is a ledger event

### §8.1. The unique competitive position

> The thesis stated in the brief: "every external query through WormBase's MCP server should write a ledger entry … the worm's ledger thereby becomes the audit log of every AI agent that ever touched the data."

This is **competitively unique in the 2026 MCP landscape.** Surveyed:

- Atlan MCP — logs to Atlan's audit log; not part of the customer's ledger.
- Glean MCP — logs to Glean's internal logs; opaque.
- Atlassian Rovo MCP — Cloudflare-side logs; opaque to customer.
- Monte Carlo MCP — logs in Monte Carlo's UI, not the customer's substrate.
- IBM ContextForge / Kong AI MCP Proxy — gateway-level logs; not domain-meaningful.

**Nobody else makes the MCP audit log a first-class business artifact.** The wormbase ledger doing this is the AI-auditor wedge from §5.2 of the business audit, made specific.

### §8.2. The entry shape (already in §5.6 above, repeated for the governance frame)

`emit_mcp_call_received` + `emit_mcp_call_resolved` form the canonical PEVR pair. Optionally, for write tools, a `propose / execute / verify / resolve` chain wraps the call (since proposing a data product is itself a propose entry).

### §8.3. Privacy nuance — the audit log is more sensitive than the data

A failed query for `email = ricardo@…` is sensitive *because* the email was attempted. Solutions:

1. **Args hashing, not args storage.** `args_hash` in the ledger; full args in encrypted side-storage.
2. **Min-classification cap** on audit visibility. An observer cannot read another Person's MCP-call audit if any arg's classification was `pii` or `regulated`.
3. **Inflation of write entries' visibility.** A `propose_data_product` write call is auditable to all `tenancy.member`+; a `query_audit_trail` read call is admin-only.

### §8.4. Rate-limiting via the ledger

A clean institutional-AI pattern:

- Every tool call counts against a rolling 1-hour and 1-day budget per (Person, tenant, tool).
- Budgets are read directly from `projection_mcp_calls` (a fold of `emit_mcp_call_received` over time).
- Limit exceeded → the gate emits `emit_mcp_call_rate_limited` instead of `emit_mcp_call_received`; tool returns 429.
- Budgets are configurable per tenant by `tenancy.admin` via the dashboard.

This is **rate-limiting as code, not as policy** — same governance principle as the rest of the substrate. No Redis required for v1; the ledger fold is fast enough for ≤1000 calls/min/tenant.

### §8.5. On-thesis criteria fired

| Criterion | How |
|---|---|
| C1 unprompted | The wormbase still acts unprompted (autoresearch); MCP exposes the result. |
| C2 deterministic | Tool outputs are hash-stable since they're projections of the ledger. |
| C3 compounding | Every MCP call adds to the ledger; the audit log compounds. |
| C4 maintenance ≈ 0 | The ledger fold is the audit log; no separate audit DB. |
| C6 auditable | Every external AI agent's touch is on the same hash chain. |
| C7 domain-specialized | The tools surface is data-function-specific (KPIs, decisions, processes). |

**6/8 of the rubric — strong.** This is on-thesis.

---

## §9. Strategic positioning — does MCP shift the wedge?

### §9.1. The MCP-native institutional-AI thesis

The business audit (§3.2) lists 5 unclaimed positions WormBase could own. Adding MCP-native institutional-AI is **unclaimed position #6**:

- **"The audit substrate for every AI agent that ever touched your data."**

No competitor in the 2026 MCP landscape ships:
1. An MCP server **AND** a hash-chained ledger of every external query;
2. With **role-aware redaction** at the same fidelity as the dashboard;
3. With **deterministic replay** of any past MCP-call response;
4. With **classification-aware audit visibility** (the audit log is governed too).

This adds a new bullet to §3.2 of the business audit:

| Unclaimed position | Evidence | WormBase fit |
|---|---|---|
| **"MCP-native institutional AI for the data function"** | Atlan/Glean/MC ship MCP servers but log to opaque internal stores. Nobody makes the MCP audit a first-class customer artifact. | Direct: every MCP call is `emit_mcp_call_*` on the customer's hash-chained ledger. |

### §9.2. Does the wedge SURVIVE Atlan / Glean / Hex / Monte Carlo MCP?

Yes — and gets **sharper**, not duller. The competitor servers are query surfaces; the WormBase MCP server is a **truth surface** (hash-stable, replayable, classification-governed, role-filtered). They're orthogonal: a customer can use Atlan's MCP for catalog metadata AND WormBase's MCP for organizational truth + audit. The pitch sharpens to:

> "Atlan's MCP gives Claude Desktop your column-level lineage. Glean's MCP gives Claude your search results. WormBase's MCP gives Claude your **decisions, your processes, your KPIs, your conversations, AND** an audit log of every query Claude just made. The first three vendors are oracles. WormBase is the substrate."

### §9.3. Pricing implication — does MCP unlock outcome-based?

**Yes, cleanly.** The pricing primitives the business audit settled on were:

- Per-seat (anchor)
- Per-source-connector (adder)
- Per-conversation-volume (outcome)

MCP adds a **fourth, demonstrably pure-outcome primitive**:

- **Per-MCP-call** — every tool call is metered. Free tier: N calls/Person/month. Overages: $0.01-$0.10/call depending on tool weight (write tools cost more).

This matches the Moesif outcome-pricing pattern and the Microsoft Sentinel MCP per-event pricing model — both proven 2026 patterns. **Crucially: the ledger entry is the metering primitive.** The customer can audit their own metering, in their own ledger. This is institutional-AI pricing as governance — competitively unique.

### §9.4. The repositioning summary

The business audit's recommended headline ("Institutional AI for the data function") **gets stronger with MCP integration**, not weaker. New tagline candidates that reinforce the MCP wedge:

- "The audit substrate for AI agents in your data function."
- "Where Claude, Cursor, and your data team's agents share one ledger."
- "Institutional AI's accountability layer — MCP-native."

Slide-3 metaphor unchanged ("Read.ai for data sources"); MCP becomes a **slide-5 proof point** ("here's Claude Desktop querying your KPI tree, and here's the audit entry it just wrote — your ledger, your hash chain, your trust").

---

## §10. Phased adoption plan

Per `feedback_research_then_empirically_validate.md`: each phase has a clear empirical-spike question that must answer green before committing engineering hours. Per `feedback_velocity_actual.md`: agent-paced wall-clock estimates assume 4-8× human-typing-speed and atomic-commit review cadence.

### §10.1. Phase 0 — Spike (~1 day)

**Goal:** stand up a 50-line MCP server inside `apps/worm-core` that exposes ONE tool (`query_ledger`); connect Claude Desktop to it; verify the round-trip works and a ledger entry is written.

**Empirical-spike question:** *Does FastMCP 3.0 + Streamable HTTP + a Claude Desktop client successfully round-trip a query through a stateless WormBase server, and does the request write an `emit_mcp_call_received` entry to the existing ledger? End-to-end latency under 500ms for a simple query?*

**Files / packages touched:**
- `apps/worm-core/src/wormbase_worm_core/mcp_server.py` (new, ~50 LOC)
- One new ledger entry type registration (`emit_mcp_call_received`)
- Claude Desktop config (off-repo, demo machine)

**Dependencies:** none. Block I and projection_runner already shipped.

**Risk:** **MEDIUM.** FastMCP 3.0 is recent (Jan 2026); Claude Desktop's MCP client occasionally regressed on Streamable HTTP through Q1 2026. Spike validates the assumption that a Python FastMCP server + Claude Desktop talk cleanly. **If the spike returns NO-GO, the entire phased plan is paused** — re-evaluate with stdio transport + `mcp-server-stdio` packaging.

**Deliverable:** a 1-page spike note (`docs/superpowers/notes/2026-04-28-mcp-phase0-spike.md`) with: it works / it doesn't / the latency number / the ledger-entry verification screenshot.

### §10.2. Phase 1 — MVP outbound (~3-5 days agent-paced)

**Goal:** ship 5-7 query tools + 5 resources + bearer-token auth + per-call audit logging. The customer's Claude Desktop / Cursor can now query WormBase's ledger, KPIs, decisions, processes, data products, conversations.

**Empirical-spike question:** *Does role-aware filtering on `query_conversations` correctly redact PII for `tenancy.observer`, return full content for `domain.owner(finance)`, and write a single `emit_mcp_call_received` + `emit_mcp_call_resolved` pair per call regardless of role?*

**Files / packages touched:**
- `apps/worm-core/src/wormbase_worm_core/mcp_server.py` (~300-500 LOC at full Phase 1 scope)
- `packages/ledger/src/wormbase_ledger/schema.py` (new entry types, 2 new projection columns or a new `projection_mcp_calls` table)
- `apps/dashboard` — `/settings/tokens` page (new, ~200 LOC TS+UI)
- `tests/mcp/test_outbound_role_aware.py` (new)

**Dependencies:** Phase 0 green. Projection_runner already shipped. Role-grant projections already shipped.

**Risk:** **LOW-MEDIUM.** Role-aware filtering reuses the same join the dashboard uses. The new code is the wire-protocol adapter. Testing is the long tail.

**Deliverable:** 5-7 tools live; demo script runs Claude Desktop asking "what are my KPIs and recent decisions?" and getting an answer with audit-log evidence on the dashboard.

### §10.3. Phase 2 — MVP inbound (~2-3 days agent-paced)

**Goal:** `MCPConnector(Connector)` lands. First inbound MCP source flows to bronze. Recommended first source: **Notion** (cleanest OAuth, simplest content model, highest demo value for "two-lake" story).

**Empirical-spike question:** *Does `MCPConnector` successfully OAuth + discover + profile + sample a Notion workspace via the official Notion MCP server, and do the resulting bytes flow through the existing `bronze_ingest` pipeline to produce a `projection_sources` row identical-in-shape to a `csv_local` source?*

**Files / packages touched:**
- `packages/connectors/src/wormbase_connectors/mcp.py` (new base, ~250-400 LOC)
- `packages/connectors/src/wormbase_connectors/mcp_presets/notion.py` (~30-50 LOC)
- `packages/connectors/src/wormbase_connectors/registry.py` (register `mcp:notion`)
- `apps/dashboard/src/app/sources/new/page.tsx` (add MCP-presets to connector grid; ~100 LOC TS)
- `tests/connectors/test_mcp_connector.py` (new)

**Dependencies:** Phase 1 ledger machinery; existing 14 connectors as reference.

**Risk:** **LOW.** Notion MCP is GA, OAuth is documented, and the Connector contract is well-tested. The MCP-client side of the codebase is new but the surface area is small.

**Deliverable:** customer can `@connect notion` from `/sources/new`; OAuth runs; Notion pages flow into bronze; one demo beat is "ask the worm about an unstructured Notion doc — answer cites the bronze hash."

**Phase 2.5 (optional adjacent ~2 days):** Add **5 more presets** — `mcp:atlassian`, `mcp:linear`, `mcp:github`, `mcp:google_workspace`, `mcp:hubspot`. Each is ~30 LOC of preset config. The "WormBase ingests 6 sources via MCP, zero per-vendor adapter code" demo beat is competitively unique.

### §10.4. Phase 3 — Governance integration (~2 days agent-paced)

**Goal:** role-aware filtering polish; classification-aware redaction on outbound; rate-limit ledger entries; observability via OpenTelemetry passthrough; `query_audit_trail` tool ships.

**Empirical-spike question:** *When a `tenancy.observer` calls `query_conversations` against a channel with classification:`pii`, does the response (a) return the redacted shape, (b) write `emit_mcp_call_received` + `emit_mcp_call_resolved` with `output_classification = pii`, (c) make the audit row visible only to admins, AND (d) reject if rate-limit exceeded with `emit_mcp_call_rate_limited`?*

**Files / packages touched:**
- `apps/worm-core/src/wormbase_worm_core/mcp_server.py` (rate-limit gate; classification-aware redaction)
- `packages/ledger/src/wormbase_ledger/schema.py` (`emit_mcp_call_rate_limited`)
- `apps/dashboard/src/app/governance/mcp/page.tsx` (new tab — "MCP audit log per Person", ~300 LOC TS)
- `tests/mcp/test_governance_observation.py` (new — exhaustive role × classification matrix)

**Dependencies:** Phase 1+2 green.

**Risk:** **LOW.** Logic is incremental on top of the role-grant join.

**Deliverable:** the H7 demo beat — "Carol-CFO asks Claude Desktop a Q3 finance question; Claude calls WormBase MCP; WormBase returns the answer; the dashboard /governance/mcp tab shows the call within 1 second; switching to Bob-Engineer's view, the same call shows as `<redacted: domain.finance>`."

### §10.5. Phase 4 — Production posture (~3-5 days agent-paced)

**Goal:** prompts surface, multi-tenant routing (path-encoded `/api/v1/tenants/{id}/mcp`), OAuth 2.1 upgrade, per-tenant observability, public MCP catalog page on the dashboard.

**Empirical-spike question:** *With OAuth 2.1 + PKCE + Resource Indicators implemented, does Claude Desktop successfully complete the 3-legged flow against WormBase, persist refresh tokens, and recover from a 401 mid-session per RFC9728?*

**Files / packages touched:**
- `apps/dashboard/src/app/oauth/{authorize,token}/route.ts` (new)
- `apps/worm-core/src/wormbase_worm_core/mcp_server.py` (auth swap + path-encoded tenancy)
- `apps/dashboard/src/app/mcp/catalog/page.tsx` (public-readable list of WormBase's MCP tools + resources, with classification badges; the "marketplace" page that customer admins share with their AI-team)
- Prompts implementations (the 4 prompts from §4.3)

**Dependencies:** Phases 1-3.

**Risk:** **MEDIUM.** OAuth 2.1 implementation is the highest-spec-conformance lift in this plan. Recommend leveraging an existing OAuth 2.1 server library (e.g., `authlib` for Python) rather than rolling.

**Deliverable:** WormBase MCP is publishable to the **official MCP Registry** (registry.modelcontextprotocol.io). Customer's Claude Desktop config: `mcp: { wormbase: { url: "https://mcp.wormbase.io/api/v1/tenants/<id>/mcp" } }`. Catalog page screenshots ready for sales decks.

### §10.6. Total

~2-3 weeks agent-paced (the original brief's estimate was right). Phase 0 is the gate: 1-day spike answers GO/NO-GO before committing the rest.

---

## §11. Top 5 strategic recommendations for the parent

### Recommendation 1 — Run Phase 0 spike this week. It's 1 day; GO/NO-GO answer changes everything downstream.

The whole plan rests on FastMCP 3.0 + Streamable HTTP + Claude Desktop talking cleanly. Verifying this in 50 LOC of `mcp_server.py` + a single ledger-entry write is the lowest-risk highest-value next move. **If it works, Phase 1-4 unlock. If it doesn't, the plan reroutes to stdio + a Claude Desktop add-in package.** Either way, you know in 1 day. Do not commit engineering hours past Phase 0 without this spike's verdict.

### Recommendation 2 — Choose Option C (`MCPConnector(Connector)`). Don't replace; don't supplement; instantiate.

The Connector Protocol is too domain-rich (Capability, ClassificationHint, ResourceProposal, Profile, Change) to throw away for MCP. But MCP is too widely adopted to ignore. The reconciliation: **MCP is one Connector implementation.** ~400 LOC for the base class + 6 presets (Notion, Atlassian, Linear, GitHub, Google Workspace, HubSpot) = 6 new sources without changing core code. PRD §2's invariant ("no core code ever changes to add a connector") is preserved. This is the highest-leverage architectural decision in the plan.

### Recommendation 3 — DO NOT replace ChannelAdapter with MCP. Same risk profile as Hermes; the spike outcome was already NO-GO once.

Slack-MCP is a query surface, not a streaming firehose. ChannelAdapter is the production wire. They are NOT substitutes. **Keep ChannelAdapter for live wire; use MCP-as-channel-source as a SUPPLEMENT for backfilling archives.** This avoids re-litigating the Hermes finding through a different door.

### Recommendation 4 — Make the audit log the demo. The MCP server is table-stakes; the ledgered MCP audit is the wedge.

The 2026 MCP landscape is saturated with Atlan/Glean/Atlassian/Notion/dbt/Monte Carlo MCP servers. **No competitor makes the MCP audit a first-class customer artifact on a hash-chained ledger.** This is the unclaimed position. The Phase 3 demo beat — "Carol asks Claude → answer + redaction + audit row + role-aware visibility" — is the most institutional-AI moment WormBase can stage. It's also the cheapest to add (Phase 3 is 2 days). Lead the demo with Atlan-comparable functionality; close with the audit beat that nobody else can match.

### Recommendation 5 — Add per-MCP-call as the fourth pricing primitive, paired with the ledger as audit substrate.

The business audit settled on three pricing primitives (seat / connector / conversation-volume); MCP adds a fourth, demonstrably pure-outcome (per-tool-call). Crucially, **the customer can audit their own metering on their own ledger** — institutional-AI pricing as governance, not as billing. This sharpens the institutional-AI positioning and is competitively unique vs Moesif/Sentinel-style MCP metering (where the customer can only trust the vendor's logs). Land this as a slide in the pricing section: "every dollar you pay maps to a hash on your own ledger."

**Defer:** anything past Phase 4. MCP gateway-fronting (ContextForge), subdomain tenancy, full OAuth federation with customer's IdP, MCP elicitation/tasks integration — all v3+. Don't build them until a customer asks.

**Spike to run:** Phase 0 only. Everything else compiles from there.

---

## §12. Sources

- [Model Context Protocol — Transports specification (2025-03-26)](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [The 2026 MCP Roadmap — Model Context Protocol Blog](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
- [Model Context Protocol — Authorization (draft)](https://modelcontextprotocol.io/specification/draft/basic/authorization)
- [Model Context Protocol — Roadmap](https://modelcontextprotocol.io/development/roadmap)
- [The Complete Guide to Model Context Protocol (MCP) in 2026 — Essa Mamdani](https://www.essamamdani.com/blog/complete-guide-model-context-protocol-mcp-2026)
- [MCP Cheat Sheet (2026) — Webfuse](https://www.webfuse.com/mcp-cheat-sheet)
- [MCP Architecture Explained — Tools, Resources, and Prompts (Knit)](https://www.getknit.dev/blog/mcp-architecture-deep-dive-tools-resources-and-prompts-explained)
- [MCP Resources explained vs MCP Tools — Laurent Kubaski](https://medium.com/@laurentkubaski/mcp-resources-explained-and-how-they-differ-from-mcp-tools-096f9d15f767)
- [MCP Demystified: Tools vs Resources vs Prompts (Microsoft)](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/mcp-demystified-tools-vs-resources-vs-prompts-explained-simply/4508057)
- [MCP Ecosystem in 2026: v1.27 release — Context Studios](https://www.contextstudios.ai/blog/mcp-ecosystem-in-2026-what-the-v127-release-actually-tells-us)
- [MCP's Remote Revolution: Streamable HTTP, OAuth, Path to 18,000 Servers — Zylos](https://zylos.ai/research/2026-03-08-mcp-remote-evolution-streamable-http-enterprise-adoption)
- [Everything your team needs to know about MCP in 2026 — WorkOS](https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026)
- [Official MCP Registry (registry.modelcontextprotocol.io)](https://registry.modelcontextprotocol.io/)
- [GitHub: modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)
- [GitHub: modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- [MCP Servers List 2026 — TokenMix](https://tokenmix.ai/blog/mcp-servers-list-2026-complete-directory)
- [Best MCP Servers for AI Developers 2026 — Taskade](https://www.taskade.com/blog/mcp-servers)
- [MCP Server Directory — PulseMCP](https://www.pulsemcp.com/servers)
- [Open-Source MCP Servers — Glama Registry](https://glama.ai/mcp/servers)
- [Best MCP Registries 2026 — Truefoundry](https://www.truefoundry.com/blog/best-mcp-registries)
- [Anthropic — Model Context Protocol announcement](https://www.anthropic.com/news/model-context-protocol)
- [Slack — MCP Real-Time Search API GA](https://slack.com/blog/news/mcp-real-time-search-api-now-available)
- [Slack — Guide to the Slack MCP server](https://slack.com/help/articles/48855576908307-Guide-to-the-Slack-MCP-server)
- [Slack docs — MCP overview](https://docs.slack.dev/ai/slack-mcp-server/)
- [Salesforce Slack deepens Anthropic Claude integration](https://www.nojitter.com/ai-automation/salesforce-s-slack-deepens-anthropic-s-claude-integration)
- [Atlassian Rovo MCP Server GA — Atlassian](https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga)
- [Introducing Atlassian's Remote MCP Server](https://www.atlassian.com/blog/announcements/remote-mcp-server)
- [Atlassian Rovo MCP Server — getting started](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/)
- [GitHub: atlassian/atlassian-mcp-server](https://github.com/atlassian/atlassian-mcp-server)
- [Notion MCP — Notion Docs](https://developers.notion.com/guides/mcp/mcp)
- [Notion's hosted MCP server — inside look](https://www.notion.com/blog/notions-hosted-mcp-server-an-inside-look)
- [GitHub: makenotion/notion-mcp-server](https://github.com/makenotion/notion-mcp-server)
- [Notion MCP Server: Capabilities, Limitations, Alternatives — StackOne](https://www.stackone.com/blog/notion-mcp-deep-dive/)
- [GitHub: github/github-mcp-server](https://github.com/github/github-mcp-server)
- [Linear MCP — official guide (overview via TeamDay)](https://www.teamday.ai/blog/slack-mcp-server-guide-2026)
- [Best Project Management MCP Servers 2026 — ChatForest](https://chatforest.com/guides/best-project-management-mcp-servers/)
- [Google Workspace MCP — official configuration](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Announcing official MCP support for Google services — Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/announcing-official-mcp-support-for-google-services)
- [HubSpot MCP — developers.hubspot.com](https://developers.hubspot.com/mcp)
- [HubSpot MCP — GA changelog April 2026](https://developers.hubspot.com/changelog/remote-hubspot-mcp-server-is-now-generally-available)
- [HubSpot MCP — Spring 2026 spotlight](https://developers.hubspot.com/changelog/spring-2026-spotlight)
- [Salesforce MCP / Agentforce — Salesforce Ben](https://www.salesforceben.com/salesforce-model-context-protocol-explained-how-mcp-bridges-ai-and-your-crm/)
- [Best CRM MCP Servers — Fastio](https://fast.io/resources/best-mcp-servers-crm/)
- [Data Warehouse MCP Servers — ChatForest](https://chatforest.com/reviews/data-warehouse-lakehouse-mcp-servers/)
- [MCP and Data Warehouses — ClickHouse](https://clickhouse.com/resources/engineering/mcp-data-warehouse-everthing-you-need-to-know)
- [Snowflake Postgres GA — Snowflake docs](https://docs.snowflake.com/en/release-notes/2026/other/2026-02-24-snowflake-postgres-ga)
- [MCP for Databases (2026) — AI2SQL](https://builder.ai2sql.io/blog/mcp-database-model-context-protocol)
- [Best MCP Servers for Database Management — DbVis](https://www.dbvis.com/thetable/best-mcp-servers-for-database-management-of-2025/)
- [Atlan MCP server — what is it](https://atlan.com/know/what-is-atlan-mcp/)
- [Atlan named Leader in Gartner MQ for Data Governance 2026](https://atlan.com/gartner-magic-quadrant-data-governance-2026/)
- [Atlan — The Context Layer for AI](https://atlan.com/)
- [Glean — Introducing MCP in Glean (March 2026)](https://www.glean.com/blog/mcp-mar-drop-2026)
- [Monte Carlo MCP — technical overview](https://docs.getmontecarlo.com/docs/monte-carlo-mcp-server-technical-overview)
- [Monte Carlo MCP server announcement](https://www.montecarlodata.com/blog-mcp-data-ai-observability/)
- [dbt MCP server — Coalesce 2025 announcement](https://www.getdbt.com/blog/coalesce-2025-rewriting-the-future)
- [How to Add Authentication to MCP Server — OAuth 2.1 (2026)](https://mcpplaygroundonline.com/blog/mcp-server-oauth-authentication-guide)
- [The New MCP Authorization Specification (April 2026)](https://dasroot.net/posts/2026/04/mcp-authorization-specification-oauth-2-1-resource-indicators/)
- [MCP Authentication: OAuth 2.1 & API Keys Guide — Toolradar](https://toolradar.com/blog/mcp-authentication)
- [Cloudflare — Authorization (Agents docs)](https://developers.cloudflare.com/agents/model-context-protocol/authorization/)
- [Cloudflare — Transport (Agents docs)](https://developers.cloudflare.com/agents/model-context-protocol/transport/)
- [Cloudflare — Scaling MCP Adoption (Enterprise reference architecture)](https://blog.cloudflare.com/enterprise-mcp/)
- [Cloudflare Outlines MCP Architecture (InfoQ)](https://www.infoq.com/news/2026/04/cloudflare-mcp/)
- [MCP OAuth — Prefect](https://www.prefect.io/resources/mcp-oauth)
- [Atlassian Rovo MCP — Configuring OAuth 2.1](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1/)
- [MCP Python SDK — github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP — github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
- [Build an MCP server — modelcontextprotocol.io](https://modelcontextprotocol.io/docs/develop/build-server)
- [Building a Production-Ready MCP Server in Python — DZone](https://dzone.com/articles/building-a-secure-observable-and-production-ready)
- [Building Your Own MCP Server — Streamable HTTP — Jangwook](https://jangwook.net/en/blog/en/mcp-server-build-practical-guide-2026/)
- [MCP Python SDK overview — Stainless](https://www.stainless.com/mcp/mcp-python-sdk-model-context-protocol-clients-and-servers)
- [9 Best MCP Servers and Deployment Platforms for Enterprise 2026 — Prefect](https://www.prefect.io/resources/best-mcp-deployment-platforms-enterprise-2026)
- [10 Best MCP Gateways for Developers 2026 — Composio](https://composio.dev/content/best-mcp-gateway-for-developers)
- [5 Best MCP Gateways 2026 — Truefoundry](https://www.truefoundry.com/blog/best-mcp-gateways)
- [GitHub: IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge)
- [GitHub: agentic-community/mcp-gateway-registry](https://github.com/agentic-community/mcp-gateway-registry)
- [MCP Aggregation, Gateway, Proxy — State of Ecosystem Q1 2026](https://www.heyitworks.tech/blog/mcp-aggregation-gateway-proxy-tools-q1-2026)
- [MCP Security Vulnerabilities — Practical DevSecOps](https://www.practical-devsecops.com/mcp-security-vulnerabilities/)
- [Auditing MCP Server Access — Aembit](https://aembit.io/blog/auditing-mcp-server-access/)
- [MCP Tool Poisoning — Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)
- [Securing MCP — Risks, Controls, Governance (arxiv)](https://arxiv.org/html/2511.20920v1)
- [MCP Security — Reco](https://www.reco.ai/learn/mcp-security)
- [Best MCP Security Tools 2026 — Truefoundry](https://www.truefoundry.com/blog/best-mcp-security-tools)
- [Protecting MCP from indirect prompt injection — Microsoft](https://developer.microsoft.com/blog/protecting-against-indirect-injection-attacks-mcp)
- [Monetizing MCP Servers with Moesif](https://www.moesif.com/blog/api-strategy/model-context-protocol/Monetizing-MCP-Model-Context-Protocol-Servers-With-Moesif/)
- [Microsoft Sentinel MCP — pricing & limits](https://learn.microsoft.com/en-us/azure/sentinel/datalake/sentinel-mcp-billing)
- [The Rise of MCP — Adoption + Monetization 2026 — Gary Weiss](https://medium.com/mcp-server/the-rise-of-mcp-protocol-adoption-in-2026-and-emerging-monetization-models-cb03438e985c)
- [9 Best MCP Clients for Developers 2026 — Fastio](https://fast.io/resources/best-mcp-clients-developers/)
- [Cline vs Cursor vs Roo Code vs Claude Code 2026 — GitHub](https://github.com/cline/cline/issues/9174)
- [MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
