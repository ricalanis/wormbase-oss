# Semantic Layer Best Practices

This document synthesizes the industry, academic, and practitioner
zeitgeist on semantic layers for AI agents, and translates the durable
findings into concrete architectural commitments for WormBase. It is
intended as ongoing reference for anyone reasoning about the
agent-gateway, the catalog mirror, the compounding query loop, and the
governance gates that compose into them.

The synthesis draws on a 2026 sweep of practitioner posts, four academic
systems for self-improving SQL agents, the Open Semantic Interchange
(OSI) standard, and the published WormBase semantic-layer design spec.

---

## Three load-bearing claims

The 2026 zeitgeist on "semantic layer for AI" converges on three claims
that drive every design decision below.

### 1. Ontology beats text-chunk RAG

Palantir's Ontology Augmented Generation (OAG) framing has gone mainstream
across the data-platform vendor ecosystem. Even Databricks (a Palantir
competitor) publicly conceded that enterprises need a structured semantic
layer for AI to work. The distinction:

- **Conventional RAG** retrieves chunks of text and injects them as
  context. The agent reasons against unstructured pieces.
- **Ontology Augmented Generation** retrieves ontology objects —
  entities, relationships, business definitions — and injects them as
  structured context. The agent reasons against a model of the business.

The empirical gap is large: LLM accuracy on data questions reportedly
rises from ~40% to over 83% when grounded in a governed semantic layer
(per Cube benchmarks). The unbundling of "enterprise AI platform" has
explicitly carved out an "ontology slot" — Atlan, Unity Catalog, Horizon,
and now SAP (post-Dremio acquisition) all compete for it.

### 2. Text-to-SQL alone is dangerous

Academic benchmarks for text-to-SQL report >85% accuracy. Pointed at real
enterprise data, accuracy collapses to ~10.8%. The gap is the
semantic-meaning gap that schema cannot reveal:

- Ambiguous business terms (which "revenue" — booked, recognized, net?)
- Unstated joins (which customer table — the operational one or the
  warehouse-conformed one?)
- Implicit time grains (does "Q3" mean fiscal-Q3 or calendar-Q3?)
- Inherited filters (do `dim_users` queries automatically exclude
  internal accounts?)

The "most confidently wrong AI product category" framing applies: raw
text-to-SQL works just well enough to be dangerous. Agents need a
semantic-layer interface, not a SQL escape hatch.

### 3. Self-improving query layers are an emergent pattern

Multiple independent academic systems have converged on the same loop:

| System | Headline | Core mechanism |
|---|---|---|
| OmniQuery | 94.2% on multi-table, +23pp over single-pass | Four-layer architecture: schema-aware retrieval + iterative SQL self-correction + AI-generated analytics |
| Dynamic-SQL | 63.23% on BIRD, -50.83% prompt length | Multi-path chain-of-thought fusion + execution-feedback correction |
| ExeSQL | Self-training framework | Generate N candidates per question, execute, keep validated, refine, iterate |
| MAGIC | In-context self-correction | Self-generated correction guidelines from prior errors |
| chase-sql | Multi-path reasoning + preference | Diverse query candidates with preference-based selection |

The common pattern: **propose → execute → reflect-on-error → retry →
record**. This is WormBase's PEVR primitive (`propose → execute → verify
→ resolve`) under a different name. The academic field independently
re-invented the loop. The implication for the architecture is that PEVR
is the self-improving query loop, made first-class on the
agent-gateway surface.

---

## The compounding query layer

Synthesizing the academic loop, the practitioner prescription
(`QuerySpec` as the agent-facing primitive), the PEVR substrate, and the
outcome-ledger anchor produces a single architectural shape: the
compounding query layer.

```
Agent (NL question, e.g., "what was Q3 EMEA revenue?")
  │
  ├─► (1) lake.semantic.search(nl_question) ─► semantic-similarity over
  │                                              catalog + metric defs +
  │                                              prior outcomes
  │
  ├─► (2) lake.semantic.query_spec({metric, filter})
  │                  │
  │                  ├─► (3) agent_query (propose) — audit start
  │                  ├─► (4) governance gates inline
  │                  ├─► (5) catalog-mirror compiles QuerySpec → upstream SQL
  │                  ├─► (6) execute via CredentialBroker
  │                  ├─► (7) execution feedback (rows | error | empty)
  │                  │      │
  │                  │      └─► IF error/empty:
  │                  │           ├─► lake.query.suggest_correction(spec, error)
  │                  │           │       — reflective LLM call using
  │                  │           │       — execution feedback
  │                  │           │       — proposes refined QuerySpec
  │                  │           │
  │                  │           └─► IF no semantic match:
  │                  │                ├─► lake.semantic.gap(nl, "no_match")
  │                  │                └─► ledger: semantic_gap_proposed
  │                  │                            → metric-proposal workflow
  │                  │
  │                  ├─► (8) agent_query (verify) — row hash, shape
  │                  └─► (9) agent_query (resolve) — kept, returned
  │
  ├─► (10) agent returns synthesis to user
  │
  └─► (11) lake.query.record_outcome(query_id, {used, useful, correction})
                                                      │
                                                      └─► ledger: query_outcome_recorded
                                                            │
                                                            ├─► outcome quality scoring
                                                            └─► IF high quality:
                                                                 └─► query_template_promoted
                                                                       — added to projection
                                                                       — next agent gets faster hit
```

### Key properties

- **Loop, not pipe.** Every query is recorded as an outcome; outcomes
  feed the next query's catalog hit.
- **Substrate IS the loop.** The PEVR primitive carries the four phases
  of the academic "propose → execute → reflect → retry" pattern. No new
  loop is introduced; the existing one is named.
- **Compounding.** `projection_query_templates` grows from accumulated
  good outcomes. The longer WormBase runs, the better the next agent's
  first query lands.
- **Governance in-line.** Every iteration of the self-correction loop
  passes through the same agent-gateway governance gates. Self-correction
  does not bypass policy.
- **Self-improvement is auditable.** Each correction is a new
  `agent_query` PEVR cycle linked via `caused_by`. The agent's thinking
  trail is the ledger.

---

## Industry product landscape

The semantic-layer-for-AI product space in 2026 looks roughly as follows.
These are the products WormBase positions against, learns from, and in
some cases interoperates with via OSI.

| Product | Posture | Coverage |
|---|---|---|
| **dbt Semantic Layer (MetricFlow)** | Most widely adopted vendor-neutral semantic layer. Ships an MCP server that lets AI agents query metrics with full business context. Limited to dbt projects. |
| **Cube** | Leading open-source semantic layer. Dedicated "AI API endpoint" and "semantic model agent" serve the full data model in a format LLMs can reason over. Code-first; strong API support. |
| **Snowflake Semantic Views** | Native Snowflake offering; combines with dbt for hybrid deployments. |
| **Databricks Metric Views** | Same shape inside Databricks Unity Catalog. |
| **AtScale** | Enterprise virtualization layer with a large vendor footprint; less AI-native. |
| **Palantir Foundry Ontology / OAG** | Closed; the reference implementation for "ontology as decision substrate." |
| **Microsoft Foundry IQ** | Announced 2026; connects expert knowledge directly into the agent-building process within the Microsoft stack. |
| **SAP Business Data Cloud** | Post-Dremio acquisition; discovery + semantic layer + Iceberg REST. |

Two patterns cut across the landscape:

1. **MCP is becoming the universal agent interface to the semantic
   layer.** dbt ships an MCP server; Microsoft Fabric ships an Ontology
   MCP Server; the trend is unmistakable. WormBase's agent-gateway lands
   here natively.
2. **Knowledge-graph framing competes with ontology framing.** Both
   describe the same shape — entities, relationships, business
   definitions, governed query interface — just under different
   intellectual lineages. The practical implementation is the same.

---

## Open Semantic Interchange (OSI)

OSI is a vendor-neutral format finalized in January 2026 for sharing
business context — definitions, relationships, access policies — between
semantic layers and AI consumers. It is the "USB of semantic layers."

WormBase's posture toward OSI is **read and emit at the boundaries**:

- **OSICatalogSource** — `CatalogSource` Protocol implementation that
  reads OSI-format manifest files. Lets WormBase ingest from any
  OSI-compliant upstream.
- **OSI exporter** — `catalog-mirror` exposes `export_osi(domain_id)`
  returning an OSI manifest for a domain. Lets WormBase publish its
  catalog to any OSI-aware consumer.

This is the "WormBase reads/writes the standard" positioning: open the
ontology boundary while keeping the compounding-loop and the
audit-trail moats in-process.

---

## Enterprise MCP governance trajectory

The MCP roadmap published in early 2026 names four priorities: transport
scalability, agent communication, governance maturation, and enterprise
readiness. Audit trails and observability are explicitly planned;
OAuth 2.1, MCP gateways, and formal audit support are confirmed.

WormBase's PEVR ledger pre-dates this MCP roadmap. Every MCP tool call
already lands as a `propose → execute → verify → resolve` cycle with full
provenance. As MCP audit standards land formally, a thin converter emits
MCP-standard audit envelopes from the existing PEVR entries. Net-zero
implementation work; pure positioning win.

---

## Translated to WormBase

The synthesis above maps onto concrete WormBase surfaces.

### MCP tool families

The agent-gateway exposes nine semantic-layer MCP tools, falling into
four families:

| Family | Tools | Role |
|---|---|---|
| Discovery | `lake.catalog.tables`, `lake.semantic.search` | Find the right catalog object or metric for an NL question. |
| Structured query | `lake.semantic.metric`, `lake.semantic.query_spec` | Submit a typed query intent; backend validates, plans, compiles, executes. |
| Self-correction | `lake.query.suggest_correction`, `lake.semantic.gap` | Reflective LLM call on failed query OR explicit semantic-gap reporting. |
| Outcome + escape hatch | `lake.query.record_outcome`, `lake.lineage`, `lake.query` | Outcome ledger feed, lineage walk, federate-mode SQL escape hatch. |

### `QuerySpec` — the agent-facing primitive

Agents submit `QuerySpec` rather than raw SQL. The backend
(catalog-mirror) validates against the metric registry, compiles to
upstream-specific SQL, and executes via the credential broker.

```python
@dataclass(frozen=True)
class QuerySpec:
    """Structured query intent — agents submit this, NOT SQL."""
    metric: str | None                    # named metric (revenue_q3) OR
    dimensions: tuple[str, ...] = ()      # ad-hoc grouping
    measures: tuple[str, ...] = ()        # ad-hoc aggregation
    filter: dict[str, Any] | None = None  # WHERE-clause-shaped
    time_grain: str | None = None         # day | week | month | quarter | year
    time_range: tuple[str, str] | None = None
    limit: int = 1000
```

The rationale is the empirical text-to-SQL collapse cited above. Raw SQL
gives the agent more rope than it can safely use; `QuerySpec` constrains
the agent to expressing intent, then trusts the backend with the
compilation.

### Outcome ledger + template promotion

Two projection tables materialize the compounding loop:

```sql
projection_query_outcomes (
    id UUID PRIMARY KEY,
    agent_query_id UUID,             -- caused_by chain
    nl_question TEXT,                -- the original NL input (for retrieval)
    final_query_spec JSONB,          -- the spec that actually executed
    result_summary JSONB,            -- row count, top-N preview hash, latency
    used BOOL,                       -- did the agent actually use the result?
    useful BOOL,                     -- did the user accept the synthesis?
    user_correction TEXT,            -- if user corrected, the verbatim correction
    quality_score NUMERIC,           -- derived: used * useful * (no_correction ? 1 : 0.5)
    embedding VECTOR(N),             -- for semantic search over prior outcomes
    recorded_at TIMESTAMPTZ
)

projection_query_templates (
    id UUID PRIMARY KEY,
    domain_id UUID,
    nl_intent TEXT,                  -- canonical NL form
    query_spec JSONB,                -- the QuerySpec that consistently works
    promoted_from_outcome_ids UUID[],-- provenance
    quality_score NUMERIC,           -- aggregate over source outcomes
    hit_count INT,                   -- usage counter
    embedding VECTOR(N),
    promoted_at TIMESTAMPTZ
)
```

Outcome → template promotion is a Reactivity:

- **Trigger:** `query_outcome_recorded` lands with `quality_score ≥ 0.9`.
- **Predicate:** at least N similar `(NL, spec)` pairs already at high
  quality form a cluster.
- **Action:** write `query_template_promoted`; insert into
  `projection_query_templates`; future `lake.semantic.search` calls
  retrieve the promoted template instead of starting from raw catalog.

The promotion is a Reactivity, not a background batch job — the
compounding pressure rises with usage, not with a cron.

### New entry kinds

Four ledger entry kinds support the loop:

| Kind | Purpose |
|---|---|
| `query_outcome_recorded` | Agent's post-query outcome (used / useful / user_correction); feeds template promotion. |
| `query_correction_suggested` | Backend's reflective suggestion for a failed query; chains via `caused_by` to the `agent_query`. |
| `semantic_gap_proposed` | Agent-reported gap: no matching metric for an NL question; triggers metric-proposal workflow. |
| `query_template_promoted` | Accumulated outcomes crossed quality threshold; durable query template added to the library. |

---

## The four positioning shifts

The synthesis above motivates four specific positioning choices for
how WormBase is talked about externally.

### 1. Lead with the accuracy uplift

"LLM accuracy on data questions jumps from ~40% to over 83% when
grounded in a governed semantic layer." This is the numerical claim that
makes the pitch concrete. WormBase frames itself as the open-source
alternative to Cube and Palantir Ontology for that grounding.

### 2. The compounding-loop wedge

Palantir's Ontology is static (admin-defined). dbt MetricFlow is static
(engineer-defined). Cube is static (engineer-defined). **WormBase's
compounding query layer learns from agent usage.** The demo shape:

- An agent asks a question.
- The semantic gap is auto-proposed.
- An admin promotes the gap to a metric (one click).
- Subsequent agents get the promoted metric.
- Over weeks, the layer has 10× more metric coverage with zero admin
  steady-state time.

This is the Karpathy "compounding state" anchor made operationally
concrete in the semantic layer.

### 3. Model-agnostic, client-agnostic

The MCP wire is the contract; the model behind it is the customer's
choice. Customer agents can be Cursor, custom internal, Claude Desktop,
ChatGPT — all equally supported. WormBase's value lives in the
substrate, not in a model partnership.

### 4. Reads and writes the standard

OSI import/export ships at the boundaries. WormBase publishes its
catalog to any OSI-aware consumer and ingests from any OSI-aware
upstream. The "open the ontology, close the loop" framing positions
WormBase as the open ontology layer alongside (rather than competing
with) closed Foundry-style ontologies.

---

## Cross-references

- [`ARCHITECTURE.md` §3](../../../ARCHITECTURE.md) — Connector contract
  and catalog-mirror.
- [ADR-0002: Agent Gateway as in-band MCP server](../decisions/ADR-0002-mcp-server-in-band-with-governance-gates.md)
- [ADR-0012: Semantic layer foundations](../decisions/ADR-0012-semantic-layer-foundations.md)
- `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` — the
  detailed semantic-layer design spec this synthesis informed.
