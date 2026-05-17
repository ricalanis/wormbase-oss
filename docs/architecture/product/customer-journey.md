# Customer Journey

This document walks the WormBase customer journey end-to-end, stage by
stage, with the seams between subsystems made visible. It is intended
as a reference for anyone reasoning about product completeness,
onboarding flows, or where the next leverage point lives.

The journey moves across six personas, nine stages, and four big
architectural seams that cut across the substrate. The substrate
itself is correct in isolation; the *transitions* between subsystems
are where the rough edges live.

---

## Headline

WormBase ships a complete institutional-AI stack: data plane (catalog
mirror), control plane (agent gateway, semantic-layer MCP tools,
compounding query loop), dashboard (18+ surfaces), and a 6-beat demo
arc that runs hermetically in under 2 seconds.

The substrate is correct. The customer journey through it is not yet
seamless. Six seams worth naming:

- **The semantic-layer MCP surface is `lake.*`-only.** Conversation-
  derived gold (decisions, processes, topics, data products) is a peer
  dataset architecturally, but agent-gateway does not expose it. An
  external agent calling MCP cannot ask "what did the team decide about
  Q3 EMEA?" through the same surface that lets it query revenue.
- **Agent registration is API-only.** The dashboard reads the agent
  projection but there is no "Register new agent" form. Admins need
  the CLI.
- **Onboarding does not differentiate "create new lake" vs "import
  existing catalog."** Tier 3 pushes "first source connect" through the
  connector picker, none of which are dbt/Snowflake-as-catalog. Catalog-
  mirror import is admin-CLI-only.
- **Internal-worm output is not ledger-linked to external-agent
  consumption.** Process maps published by the process-extractor do not
  trace to which external agents consumed them via MCP, because no MCP
  tool exposes them.
- **WhatsApp onboarding is preview-status but the dashboard treats it
  production-shaped.** Status honesty is enforced at the connector
  picker but not at the channels surface.
- **The demo arc demonstrates the engine, not the flywheel.** Real
  customer journeys span 90 days, not 3 minutes. Flywheel beats —
  7-day team-discovery, 30-day template-promotion, 90-day governance-
  evolution — are missing from the canonical demo.

---

## The six personas

| Persona | Primary surface | Driving question |
|---|---|---|
| **Prospect** (eval / trial) | marketing landing → `/login` → `/onboarding` | "Will this work on my mess?" |
| **Installer** (Tier 1 admin) | `/onboarding/{welcome,tier2,tier3}`, `/channels/connect/*` | "Is the setup 60 seconds or 6 hours?" |
| **Domain owner** (data team lead) | `/sources`, `/lake/*`, `/policies`, `/people` | "Is the right data exposed to the right roles?" |
| **Org member** (consumer) | chat platform (Slack/WhatsApp DM/group), `/dashboard`, `/data-products` | "Did the worm answer my question? Was it right?" |
| **External agent** (Claude Desktop, ChatGPT, custom) | MCP server (stdio/HTTP) | "Can I query the org's semantic layer with full governance?" |
| **Worm itself** (autonomous) | Reactivity runner | "Did anything need my attention? Should I propose work?" |

Each has a distinct journey; the journeys intersect at the dashboard
and chat surfaces. The semantic-layer waves primarily serve the
external-agent and domain-owner personas — the other four still have
journey gaps that the substrate alone does not address.

---

## Stage-by-stage walkthrough

### Stage 0 — Discovery → trial

**Today**

- Marketing surfaces are implicit: a `/pricing` page and a `/security`
  page exist; no top-of-funnel landing optimized for self-serve trial
  signup.
- The 6-beat demo arc is hermetic and runs as a test, not a click-
  through. The wire-replay tape from the polish wave can drive a
  deterministic replay, but there is no recorded video or live sandbox.
- Trial provisioning: `auth/email/confirm` + `/login` exist; no trial-
  tenant auto-provisioner.

**Seam:** prospects discovering WormBase have no path from "interesting"
to "running on my data" without a sales call. The hermetic demo is a
capability assertion, not a visceral one.

**Effort to close**

- *Low:* record the demo arc as a 3-min screencast, embed on landing.
- *Medium:* live sandbox at `app.wormbase.demo/<fixture>` — pre-
  provisioned tenant with a fixture manifest + a Claude-Desktop-style
  MCP-client browser embed.
- *High:* self-serve trial with email-only signup + auto-tenant + 14-
  day free tier.

### Stage 1 — Tenant creation (Tier 0 → Tier 1)

**Today**

- Tier 0 is **chat-platform-first** (Slack OR WhatsApp button). A
  default local lake auto-provisions at install (the tenant has bronze
  + silver + gold visible at `/sources` from minute zero, before any
  external source connects).
- Tier 0 → Tier 1 happens via OAuth (Slack/WhatsApp pairing). Real
  OAuth or disabled-with-config-message — no synthesized grants.
- The wizard-vs-bot fork moves to a banner CTA post-install — no
  longer a forced redirect.

**Works well**

- The 60-second target is plausible for Slack (OAuth round-trip +
  Install row + role grants + default lake).
- The default local lake means **no empty-dashboard problem** on day
  zero. Existing tenants visit `/sources` and see bronze samples
  immediately.
- Connector picker enforces production/preview/coming_soon honestly.

**Seams**

- **WhatsApp Tier 0 is pairing-based, not OAuth-based** (Baileys via
  OpenClaw). Pairing requires the operator to scan a QR or enter an
  8-digit code on a bot phone — fundamentally less ambient than Slack
  OAuth.
- **Tier 1 → Tier 2 transition is ambiguous when the default lake is
  enough.** If a tenant just wants to chat with the worm and let the
  conversation lake fill, do they need to advance past Tier 1? Today
  the answer is no, but the onboarding-milestones panel still displays
  six tiers, implying linear progression.
- **No "import existing catalog" path in Tier 3.** The 12-connector
  picker covers live sources only. A customer with an existing dbt repo
  + Snowflake warehouse has no Tier-3 button for "import my catalog";
  they fall back to admin CLI.

### Stage 2 — WhatsApp onboarding

**Today**

- `/channels/connect/whatsapp` shows the pairing UI (QR + 8-digit
  code).
- Pairing fires `emit_whatsapp_install` → Install row populated →
  wires bind.
- Send wire validated and rate-limited via OpenClaw subprocess.
- Status: **preview**. Production graduation gated on operator-approved
  write scopes + container with docker-host access OR upstream HTTP
  route from OpenClaw.
- Provenance honest: every `InfraEvent` + `ChatReceivedPayload`
  carries `delivery_mode`, `platform_ts`, `history_sync_id`. The
  `LiveOnly` condition gates speak-paths from history-replayed
  messages.
- Echo guard: drops `key.fromMe` before normalize.

**Works well**

- Capability honesty is rigorously enforced in payload + spec text. A
  preview-status WhatsApp install can read/listen with high confidence;
  sending is gated.
- The conversation lake fills regardless of preview status (bronze
  cascade ingests history-replayed messages alongside live ones).

**Seams**

- **Inviting the worm to a conversation is not surfaced separately.**
  Today, the worm joins channels at pairing time. For DMs, the worm's
  phone is the recipient. For groups, the worm must be invited by a
  group admin (WhatsApp-side, not WormBase-side). There is no
  dashboard panel that says "Here's the worm's WhatsApp number; share
  with team / invite to groups."
- **Talkativeness-per-channel default is not admin-visible.** First-
  touch WhatsApp channels default to lurker + `daily_interjection_
  budget=0`. The dashboard's `/settings/channels` page exposes this,
  but a tenant onboarding via WhatsApp does not get a clear "raise
  talkativeness for this group" affordance unless they navigate there.
- **Production-graduation messaging is buried.** A customer who pairs
  a WhatsApp install today sees a working setup with `send` capable,
  but the spec says "send capability requires operator approval to
  graduate to production." Where does this surface? Not in the
  pairing page.
- **WhatsApp ≠ Slack feature parity in the audit chain.** Two trace
  flows are separate: `/trace/agent_query/[id]` walks MCP-call PEVR
  chains; `/trace/decision/[id]` walks chat-derived decisions. A user
  asking "show me the audit chain for this conversation" must visit
  the right one for the source. The conceptual mapping isn't
  documented.

### Stage 3 — Conversation populates (the worm in the room)

**Today**

- `ChatReceivedReactivity` writes bronze entries for every message
  that survives the relevance gate.
- `MentionResponseReactivity` (with `LiveOnly` + `DomainEnabled`
  gates) determines whether the worm speaks back. Today it is mention-
  triggered (`@worm`) + occasional autonomous interjection within the
  budget.
- `SourceMentionedReactivity` fires when a chat message references a
  data source. Drops a source-proposed entry.

**Works well**

- The bronze cascade is on-thesis with the conversation-as-data-source
  architecture. Every message becomes silver (topics/threads) then
  gold (decisions/processes/data products). Visible via `/topics`,
  `/decisions`, `/processes`, `/data-products`.
- `LiveOnly` correctly prevents history-replay from triggering speak-
  paths.

**Seams**

- **No clean affordance for "this conversation matters; raise
  priority."** All conversations get the same talkativeness/relevance
  treatment per channel. A team-lead-driven important conversation has
  no way to flag itself for higher attention without dashboard
  navigation.
- **The worm's response provenance is opaque mid-conversation.** When
  the worm speaks, the message arrives in chat. The audit trail is in
  `/trace`. There is no inline "[show me why the worm said this]" UX
  — users would have to manually visit `/trace`, find the entry, walk
  the chain.
- **Conversation lake gold is not exposed via MCP.** External agents
  cannot ask "what process did the team follow for last quarter's
  release planning?" — that gold lives in the conversation lake, not
  the external catalog. The MCP tools are `lake.*`-prefixed and read
  external-catalog projections only.

### Stage 4 — Data lake build-up

**Today**

- Five live-source trigger flows wired (drop-and-profile, credential-
  offered-in-DM, mentioned-in-conversation, dashboard "Add source"
  form, KPI-gap-triggered).
- Sixth trigger flow (catalog mirror): admin-CLI-only today.
- Conversation lake fills automatically (per Stage 3).
- Default local lake auto-provisions at install.

**Works well**

- Five live-source flows are wired. Each writes the same ledger
  sequence: `source_proposed → source_confirmed → source_connected →
  source_profiled`.
- Catalog-mirror import is functional and verified against live
  Snowflake trial + dbt manifest.

**Seams**

- **Catalog-mirror import has no dashboard surface.** The admin runs
  it via `@worm import dbt at ...` in chat, or via direct API call.
  `/sources/new` does not list "dbt manifest" or "Snowflake catalog"
  as connector options because they are `CatalogSource` implementations
  (a separate Protocol from `Connector`).
- **`upstream_mirror` Sources do not appear at `/sources` the same way
  `wormbase_owned` Sources do.** The `/sources` page reads
  `projection_sources`; catalog-mirror writes `projection_external_
  catalog`. A tenant who imports a dbt catalog won't see those tables
  in `/sources` — only in `/lake/catalog`. Two different concepts of
  "source" in two different surfaces.
- **The classification step is implicit for catalog-mirror.** For
  wormbase-owned sources, the connector form asks for classification
  at connect time. For upstream-mirror sources, classification comes
  from the upstream's tags (Snowflake tags, dbt meta) and is auto-
  derived. Most upstream catalogs have inconsistent tagging. There is
  no "review proposed classifications" flow for upstream-mirror
  imports.

### Stage 5 — Agent registration

**Today**

- Four entry kinds registered (`agent_registered`, `agent_grant`,
  `agent_query`, `credential`).
- Projection tables populated; `/people/agents` dashboard page shows
  registered agents + grant counts + budget.
- Registration is **API-only**: there is a worm-core write_action
  endpoint, but no dashboard form.
- Agent grants distinguish four kinds: `domain.read`, `resource.read`,
  `resource.maintainer`, `model.access`. The `model.access` grant
  carries `budget_remaining_usd`.

**Seams**

- **No "Register new agent" dashboard form.** Admin must use admin
  CLI / API. For a non-technical domain owner setting up Claude Desktop
  access, this is friction.
- **No "Configure Claude Desktop with WormBase MCP" walkthrough.** The
  MCP server endpoint exists, but the URL/config the admin pastes into
  Claude Desktop's MCP config file is not documented in any surface.
- **Per-agent budget UI is read-only.** The page shows
  `budget_remaining_usd_sum` (the sum across active model.access
  grants) but no "top up budget" or "set monthly budget" affordance.
  Budget is set at grant time only.

### Stage 6 — Agent operating mode (queries → outcomes → compounding)

**Today**

- Nine MCP tools: `lake.catalog.tables`, `lake.semantic.metric`,
  `lake.lineage`, `lake.query`, `lake.semantic.search`,
  `lake.semantic.query_spec`, `lake.query.suggest_correction`,
  `lake.query.record_outcome`, `lake.semantic.gap`.
- Every tool call writes `agent_query` PEVR. Some chain
  `inference_served` + `credential`. The audit chain is browsable at
  `/trace/agent_query/[id]`.
- `query_outcome_recorded` outcomes feed `projection_query_outcomes`.
- `OutcomeToTemplatePromotion` Reactivity fires when ≥3 high-quality
  outcomes cluster.

**Seams**

- **The 9 MCP tools are all `lake.*`.** No `decisions.*`,
  `processes.*`, `topics.*`, `data_products.*`, `notebooks.*`. An
  external agent has no path to the conversation lake or notebook
  outputs through the same governance gate that protects external-
  catalog reads.
- **Agent identity is not visible inline in chat.** When an external
  agent queries the worm and gets a result, that interaction lands in
  `agent_query` PEVR. It's traced. But it does not appear in the
  relevant team's channel ("FYI, claude_research just pulled revenue_q3
  for EMEA"). Audit is silent; consumers do not see agent activity
  unless they visit `/trace`.
- **The compounding loop has not fired in production.** The Reactivity
  is wired and the predicate is canonical, but no tenant has
  accumulated ≥3 high-quality outcomes on the same NL-intent yet. The
  flywheel is shaped; it has not spun.

### Stage 7 — Governance evolution

**Today**

- Three role facets (tenancy / domain / resource) per the role spec.
- Domain owners assigned at Tier 2 of onboarding.
- Per-source classification at connect time (live sources) or auto-
  derived from upstream tags (catalog mirror).
- Inline MCP gates: `AgentAccessGate`, `ClassificationGate`,
  `PIIRedactionGate`, `CostGate`. Pure-function, not stateful.
- Existing stateful gates (`packages/governance/`): `PIIGate`,
  `WarmupGate`, `InterjectionGate`, `KnowledgeGate`. These emit
  `gate_fired` ledger entries.
- `/policies` and `/lake/governance` for policy inventory + upstream-
  policy mirror.
- `/people/proposals` for confirming auto-proposed people + role
  grants.

**Seams**

- **Two gate families have not been unified.** The inline gates (4)
  run in the MCP path. Existing stateful gates (4) run in the chat /
  write-action path. A query that crosses both (an external agent
  pulling data → the result lands in a process-extractor decision)
  gets two passes of partial governance.
- **`gate_fired` audit entries are not surfaced for agent_query
  denials.** When an `AgentAccessGate` denies an agent query, the
  agent_query PEVR resolves with `status="denied"`. The denial reason
  is in payload. But there is no `/governance` admin view of "denials
  this week" or "which gates are firing most."
- **Per-domain policy ownership is not editable.** Upstream policies
  (Snowflake masking, etc.) mirror into `projection_external_policy`.
  WormBase-native policies are read-only — no admin form to author a
  new policy. Today, policy authoring happens at install time (Tier 2
  picks classification defaults) and via direct ledger writes.
- **Classification of conversation lake is opaque.** A Slack message
  gets classified at ingest by the relevance gate, but the
  classification isn't shown to the user. The conversation lake's
  gold-layer outputs inherit classifications from sources mentioned +
  the channel's domain — but there is no admin view that says
  "decisions in domain finance have inherited PII classification from
  these 3 messages."

### Stage 8 — Consistent products (data products as first-class artifacts)

**Today**

- Four entry kinds: `data_product_proposed`, `data_product_published`,
  `data_product_consumed`, `data_product_demoted`.
- `/data-products` and `/data-products/[id]` dashboards exist.
- Process maps auto-emit `data_product_proposed`.
- Consumption logged per event (a member opens the data product →
  `emit_data_product_consumed` lands).

**Seams**

- **Agent-query results do not auto-emit data products.** A high-
  quality `agent_query` with a useful result is functionally a data
  product — a governed answer to an NL question with provenance. But
  MCP tools do not emit `data_product_proposed` on resolve. They only
  emit `query_outcome_recorded` if the agent calls
  `lake.query.record_outcome`.
- **No "promote agent_query result to data product" flow.** A user
  receiving an agent answer via chat or dashboard has no button to
  "promote this to a data product for the team." Today, data products
  are created by the worm autonomously (process-extractor) or by
  manual notebook writes.
- **Data product lineage to agent queries is missing.** When a data
  product is consumed by an external agent (e.g. claude_research
  calls `lake.semantic.metric("revenue_q3")` which returns a stored
  metric definition), the consumption event does not link back
  through `caused_by` to the original data product. The audit chain
  breaks at the data-product → agent-query boundary.

### Stage 9 — Day-100 operating state

**Today (extrapolating)**

- Conversation lake accumulates per-channel. Topics, decisions,
  processes auto-derive.
- External catalogs imported once; drift Reactivity refreshes per
  `wire_catalog_for_source`.
- Agent grants set at registration; budgets refilled manually.
- Templates promoted when clusters fire.
- Semantic gaps queue grows; admin promotes intermittently.

**Seams**

- **No 30-day / 90-day "compounding state" dashboard.** A tenant has
  no view of "how much has the layer learned in the last 30 days?" —
  no graph of template promotions over time, no graph of gap → metric
  promotions, no graph of agent activity ramp.
- **No "the worm noticed something" notification surface.** When drift
  fires on a catalog, or a high-priority gap goes unaddressed, the
  worm just writes ledger entries. No push to email / Slack DM to the
  domain owner. The worm is mute about its own observations beyond
  chat-channel interjections.
- **No "tenant health" admin view.** Day-100 admin question: "is
  governance fresh? are there stale grants? unconfirmed proposed
  people?" — these are scattered across `/people/proposals`,
  `/policies`, `/lake/governance`. No single rollup.

---

## The four big architectural seams

Pulling back from stages, four cross-cutting seams emerge.

### Seam 1 — Conversation-lake / external-lake silo at the MCP surface

**The problem.** The agent-gateway exposes nine `lake.*` tools that
read the external catalog. The conversation lake's gold-layer outputs
(decisions, processes, topics, data products, notebooks) are equally
first-class data per the architecture but are invisible to external
agents.

A real-world-shaped query — *"what decision did the team make about
the Q3 forecast revision?"* — is in conversation gold (decisions
table, populated by process-extractor from chat threads). No MCP tool
reaches it.

**The fix.** Add `decisions.*`, `processes.*`, `topics.*`,
`data_products.*` tool families to the agent-gateway MCP surface.
Each follows the same pattern as `lake.*`: pass through `apply_gates`
for governance, wrap in `agent_query_pevr` for audit, return
structured response with `audit_trail_id`. They are additive — no
schema changes — these projections already exist.

**Why it matters.** The institutional-AI moat depends on agents being
able to ask about **operational truth**, not just **catalog truth**.
Today's MCP surface is half-empty.

### Seam 2 — Onboarding tier ↔ semantic-layer journey

**The problem.** Onboarding (Tier 0-3) is chat-first and provisions a
default local lake. The semantic-layer surface expects either a
WormBase-owned lake or an upstream_mirror catalog. The Tier-3
connector picker shows 12 live-source kinds, none of which trigger
catalog-mirror import.

A real customer with an existing dbt repo + Snowflake warehouse has
no Tier-3 path. They install via Slack, get a default lake (which they
don't want — they have their own data), and then fall back to admin
CLI to run `@worm import dbt at github.com/acme/analytics`.

**The fix.** Add an "Import existing catalog" branch to Tier 3 with
two sub-paths:

- "Connect dbt project" — collects manifest URL (https URL or local
  upload), fires catalog-mirror import.
- "Connect existing warehouse" — Snowflake-native or Databricks-UC
  catalog mirror without the live-source connector path.

**Why it matters.** Enterprise customers don't want a new lake. They
want WormBase to layer over what they have. The current onboarding
pushes them toward a workflow they will abandon.

### Seam 3 — Internal worms ↔ external agents interaction asymmetry

**The problem.** Internal worms are autonomous (Reactivities fire on
conditions). External agents are reactive (they call MCP tools). Today
they share the inference router + audit but they do not share a clean
way to **propose work to each other**:

- An external agent **cannot ask the worm to do something
  autonomously.** Example: "set up a recurring monitor: alert me when
  revenue_q3 drops >10%." Today the agent can call
  `lake.semantic.metric` synchronously; it cannot register a
  Reactivity.
- The worm **cannot proactively push to an external agent.** When
  drift fires on a catalog, the worm writes a ledger entry. No MCP
  notification, no agent-side callback URL invoked.

**The fix (two-part).**

- *Part A:* an `agent_request_reactivity` MCP tool that lets agents
  register their own Reactivities (governed by an
  `AgentReactivityGate` to prevent abuse). The Reactivity is owned by
  the agent's identity; on fire, it pushes an `agent_notification`
  entry that the agent polls or webhook-receives.
- *Part B:* an outbound webhook capability per agent — registered at
  `agent_registered` time. When the worm has something to push (drift,
  gap, completed Reactivity), it POSTs to the agent's webhook with
  the `audit_trail_id`. The agent fetches detail via MCP.

**Why it matters.** Without this, external agents are stateless data
consumers. The continuous-improvement-agent posture requires agents
that can register their own loops. Today, only internal worms can.

### Seam 4 — Conversation-lake gold ↔ agent-gateway compounding loop

**The problem.** The compounding loop is wired for
`query_outcome_recorded` events on MCP tool calls. Its
`OutcomeToTemplatePromotion` Reactivity clusters outcomes on NL-intent
over external-catalog queries.

The conversation lake has its own equivalent compounding: every team
conversation produces decisions, processes, topics. These compound
differently — by author cluster, by time window, by topic resurrection
— but the existing promotion machinery does not apply.

**The fix.** Generalize `OutcomeToTemplatePromotion` to a
**`Compounding`** primitive that can be parameterized by:

- Source predicate (which entry kind triggers).
- Clustering function (embedding cosine, author cluster, topic
  similarity).
- Promotion threshold (≥3 high-quality, ≥5 reproduced, ≥2 contradicted).
- Promotion target (template, knowledge-base article, deprecation flag).

Then wire it for:

- `agent_query` outcomes → query templates (existing).
- chat decisions → process maps (today: ad-hoc in process-extractor).
- `agent_query` failures → known-bad-patterns library (new).
- semantic gaps unanswered for N days → escalation (new).

**Why it matters.** The compounding loop is the institutional-AI moat.
Today it operates on one axis (MCP-query outcomes). Five axes would be
on-thesis with the "the worm builds the wiki" framing.

---

## Cross-cutting bets worth holding

Patterns that aren't "fixes" but should compound across waves.

1. **Capability honesty everywhere.** Already enforced for connectors
   and channels. Extend to: MCP tools (preview vs production status
   visible to external agents in the tool's docstring), data products
   (proposed vs published distinction surfaced clearly), Reactivities
   (active vs paused state visible in `/reactivities`).

2. **Provenance chain end-to-end.** Today the audit chain works inside
   the MCP surface and inside the chat surface. These two chains do
   not cross-link when an agent query feeds a chat reply or vice
   versa. The unified chain should walk both worlds.

3. **No demo seams.** Standing invariants (no fixture loads, no
   hardcoded persona lists, no flow-bypass shortcuts) keep the demo
   path identical to the production path. Every fix to a seam should
   leave that invariant unaffected.

4. **The compounding knowledge corpus.** Today the worm maintains
   three corpora: the conversation lake (chat → decisions → process
   maps), the external catalog (drift detection), and the query
   template library (compounding). Two more are natural extensions:
   the **agent profiles** corpus (per-agent learned grants, patterns,
   budget preferences) and the **governance policies** corpus (auto-
   proposed policy refinements based on observed denials).

---

## What this journey does not address

To keep scope honest, this walkthrough does not cover:

- Specific pricing model or business model (the `/pricing` page
  state).
- SOC 2 / GDPR / HIPAA compliance certification work.
- Cloud deployment topology (how WormBase actually runs in
  production).
- Customer support tooling.
- Marketing site / sales materials beyond the demo arc.
- Internationalization.
- Mobile app.
- Pricing of inference at scale.
- Capacity planning per the architecture's scale assumptions.

These are real product concerns but distinct from the customer journey
through the **substrate**.

---

## Cross-references

- [`ARCHITECTURE.md`](../../../ARCHITECTURE.md) — the durable
  architectural shape the journey moves across.
- [institutional-onboarding-proposal.md](institutional-onboarding-proposal.md)
  — the architectural proposal for closing Seam 2 (onboarding tier ↔
  semantic-layer journey) and extending OpenClaw's pattern to the
  institutional ontology.
- [openclaw-integration-patterns.md](../case-studies/openclaw-integration-patterns.md)
  — the OpenClaw pattern characterization that informs the
  `@onboard <object>` verb.
- [semantic-layer-best-practices.md](../synthesis/semantic-layer-best-practices.md)
  — the substrate the journey traverses at the agent-gateway surface.
