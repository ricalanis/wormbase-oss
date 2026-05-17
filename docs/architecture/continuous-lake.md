# The Continuous Lake

> **Status:** Authoritative (2026-05-17)
> **Audience:** Engineers landing in `docs/architecture/` who want the
> mental model of what WormBase actually is.
> **Companion docs:** `docs/architecture/lake-side-loops.md` (the eight
> tending behaviors), `docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md`
> (the architectural commitment behind this framing).

---

## What this is

**WormBase is the agent-installable continuous lake.**

It installs into your chat platform (Slack / Discord / Teams) and into
your data lake — either by **building** one (default local: csv / sqlite
/ parquet under `~/.wormbase/lake/`) or by **connecting** to your existing
lake (Postgres warehouse, Snowflake, BigQuery, S3 lakehouse, Notion via
MCP, and so on). Both paths end at the same state: a continuous, governed,
agent-tended lake.

From the moment of install, the lake is continuous and agent-operated.
The agent and the lake **co-emerge**. There is no pre-existing lake that
the agent then arrives to operate; the lake exists because the agent is
tending it. Eight lake-side loops continuously tend the lake's state.
Maintainable surfaces detect drift, refresh classification, signal
staleness, and report lineage health on their own. Every action is
hash-chained from the ledger, every action is replayable, every action
is auditable.

This document is the umbrella narrative. It does not duplicate the deep
references — it points at them. Read this first; follow the
cross-references at the bottom for depth.

---

## Positioning

The 2026 industry vocabulary around "agentic data" is crowded. Every
major vendor has staked out a phrase. The slot WormBase occupies is
genuinely different, but it sits adjacent to several others, and the
adjacencies are worth naming explicitly.

The shared assumption across the field is that **agentic maintenance is
a bolt-on layer over an existing lake / warehouse / lakehouse.** The
substrate pre-exists; the agents arrive afterwards to maintain it.
WormBase inverts that assumption: **the lake exists because the agent is
tending it.** Install is the first act of maintenance. Lurking is bronze
ingestion. The conversation stream is a source family. There is no lake
before the agent.

| Vendor / source | What they call themselves | What WormBase does differently |
|---|---|---|
| **IBM** | "Agentic data management" — AI agents on top of an existing data platform | We don't sit on top of a platform; we install into your lake (or boot you one) and the agent and lake co-emerge from t=0. |
| **Acceldata** | "Agentic data management" + "Agentic policy management" — specialized agents for anomaly / quality / lineage layered over your existing stack | Same bolt-on shape — they layer onto your existing stack. WormBase has no "existing stack" assumption; the chat install brings the first surface. |
| **Snowflake** | "Self-driving" — a managed warehouse that auto-optimizes itself | They manage one warehouse. WormBase tends an open lake that may live in your warehouse, your S3, your Postgres, or a fresh local one — federated by surface, not by vendor. |
| **Databricks** | "Self-healing pipelines" — pipelines that detect and correct their own breaks (Ali Ghodsi: 80%+ of new Databricks DBs created by AI agents, 2026) | We don't have pipelines. We have continuous tending behaviors that work on whatever lake is installed-into. No pipeline framing to heal. |
| **Google Cloud** | "AI-native lakehouse" / "always-on context" / "continuous feedback loops" — lakehouse re-engineered to feed agents | They re-engineered the lakehouse for agents. WormBase doesn't re-engineer the lake at all — it installs into whatever lake you have and tends it continuously. The lake is yours; the tending is ours. |
| **Atlan / DataHub** | "Active metadata" — metadata that drives action, not just stored | Active-metadata framing is on-thesis, but it sits alongside the lake as a separate catalog. WormBase's ledger IS the metadata, and every action is hash-chained from it. One substrate, not two. |
| **Monte Carlo / Bigeye** | "Data observability" / "AI Trust Platform" — detection + autonomous remediation as a bolt-on observability layer | They observe the lake from outside. WormBase tends the lake from inside. Drift detection, classification refresh, lineage health, quality checks are lake-side loops — not an external observer. |
| **CDO Magazine** | "Digital data steward" — AI agents that maintain catalog / quality | Steward framing implies a bolt-on role; humans-with-agents. WormBase isn't a role layered on a lake; the agent IS the lake's operator from t=0. |

The vocabulary worth borrowing (because it signals shared discourse):
*continuous feedback loops*, *always-on context*, *autonomous
remediation*, *active*. The vocabulary worth avoiding (because it
re-asserts the framing we reject): *self-healing pipelines*,
*self-driving*, *data steward*, *agentic data management*.

The vocabulary we coin and load-bear ourselves: **continuous lake**,
**lake surface** / **surface**, **SurfaceDriver**, **tending**,
**co-emergent**, **two installations**, **build or connect**.

The slot is not "another observability vendor." The slot is not "yet
another lakehouse." The slot is the **agent-installable continuous
lake** — a category that did not exist before this product because the
shared assumption was that the lake comes first and the agent arrives
later. WormBase ships the inverted assumption: install the agent, get
a lake; the lake exists because the agent is tending it. That is the
positioning sentence to remember when comparing against any vendor in
this space.

---

## The two installations

A WormBase install is two acts, not one. Both must complete for the
worm to be operational; the order is chosen by the user.

### Chat install

Familiar; already in production. `@connect slack` (or `discord` /
`teams`) wires a channel adapter to the worm-core. The worm acquires a
user-side surface: the conversation stream. From the first message
forward, the worm is lurking — listening to every channel it has been
invited to, ingesting messages into bronze, threading them into silver,
synthesizing decisions / processes / mentions into gold.

The chat install is the entry point for most installs. It produces
value before any external data source is connected: a first process map,
a first decision record, a first ontology of who-asks-whom-about-what
can land within a day of lurking. Conversation is a first-class source
family, not a UX surface for a separate substrate.

### Lake install — build or connect

The lake install is the moment the worm acquires its first non-conversation
surface. It has two paths:

**Build (greenfield).** The user has no existing data lake. The worm
bootstraps a default local lake at `~/.wormbase/lake/{bronze,silver,gold}/`
(or the container-equivalent path) backed by the `csv_local`
SurfaceDriver. From t=0 the worm tends this freshly-built lake: the
medallion cascade runs, the eight lake-side loops run, drift detection
runs, classification refresh runs. The build path is intended for SMBs,
demo runs, and first-time installs where there is no pre-existing
warehouse to point at.

**Connect (brownfield).** The user already has a data lake. They pick one
of the production-ready SurfaceDrivers (`postgres`, `snowflake`,
`bigquery`, `s3_csv`, `http_csv`, `stripe`) or an MCP-bridged surface
(`notion`, `hubspot`, `linear`, `atlassian` — preview / coming-soon
status varies; see `docs/architecture/surfaces.md` for the current pin).
The worm installs into the existing lake: read-side access initially,
write-side governed by Policy. From t=0 of connect the worm begins
tending: the existing lake becomes lake-side-loop-active immediately.

**The two paths end at the same state.**

- Both produce a `Source` instance with `family` ∈ {`external`,
  `filedrop`, `conversation`, `evidence`}.
- Both trigger the `propose → execute → verify → resolve → trace` ledger
  sequence (the PEVR write primitive).
- Both activate the same eight lake-side loops (L1–L8).
- Both become equally tended.

This is what we mean by "build or connect to a data lake and install
into it." The build option is for prospects who don't yet have a lake;
the connect option is for prospects who already do. The continuous lake
is the same lake either way — the same governance, the same medallion,
the same tending behaviors.

### Hybrid is the common case

The most common shape is hybrid: a prospect installs WormBase, gets a
default local lake bootstrapped (build path), then connects their
Postgres warehouse a week later (connect path). The continuous lake
spans both surfaces; the worm tends them both equally.

The continuous lake is **federated by default.** Surfaces can live
wherever a SurfaceDriver can reach. The ledger projects state from all
surfaces uniformly. There is no privileged surface; there is no
"primary" lake. There is one continuous lake with many faces.

The PEVR sequence (`propose → execute → verify → resolve → trace`) is
the same primitive for every install act. Chat install proposes the
adapter, executes the OAuth, verifies the bot is alive, resolves the
install, traces the ledger entry. Lake install (build) proposes the
default-local surface, executes the directory bootstrap, verifies the
medallion paths exist, resolves the install, traces the ledger entry.
Lake install (connect) proposes the surface with credentials, executes
the connection, verifies discovery succeeds, resolves, traces. One
loop, three install shapes, identical audit trail.

---

## Four kinds of surfaces

A **surface** is a managed face of the continuous lake. Every surface
the worm tends belongs to one of four source families. The families
differ in how the agent acquires from them, but they do not differ in
how the agent tends them.

| Family | Examples | Implements `AcquirableSource`? | Implements `MaintainableSource`? |
|---|---|---|---|
| **external** | Postgres, Snowflake, BigQuery, S3, Stripe, Notion via MCP, HubSpot via MCP | ✅ — discoverable, profilable, samplable | ✅ — drift, classification, staleness, lineage |
| **filedrop** | CSVs dropped in Slack, evidence uploads, one-off PDFs | ✅ — discoverable per drop | ✅ — drift, classification, staleness, lineage |
| **conversation** | The chat stream itself — every message, mention, thread, decision | ❌ — not acquirable in tabular shape; read from the ledger | ✅ — drift, classification, staleness, lineage |
| **evidence** | Autoresearch-published notebooks, data products | ❌ — produced internally, not acquired from outside | ✅ — drift, classification, staleness, lineage |

The crucial property: **all four families are equally lake-resident.**
None is more "real" than the others. The conversation lake and the
evidence lake are first-class sources; they are not auxiliary streams
hanging off a primary lake of "real data." A process map mined from
six months of Slack lurking is as much a lake artifact as a Postgres
table; both produce ledger entries, both are governed, both are
tended.

The two Protocols — `AcquirableSource` and `MaintainableSource` — are
the contract every surface implements. External and filedrop surfaces
implement both: they can be discovered from outside and tended from
inside. Conversation and evidence implement only `MaintainableSource`:
they originate from the worm's own activity (lurking / publishing) and
are tended like everything else, but they are not "acquired" in the
tabular sense. The split keeps each family honest about what it
actually does — see ADR-0003 for the design rationale.

This re-articulation matters because the older OSS framing treats
"connector sources" as the source story, with chat as a separate
channel. The correct framing: **the chat stream IS a source family**
that the agent has been tending since chat-install. Lurking is bronze
ingestion. The same medallion cascade applies. The conversation surface
is the first surface in the continuous lake — the lake-install adds the
second.

---

## Eight tending behaviors

Eight lake-side loops run continuously from t=0 of install. Each is one
way the agent is tending the lake's state. They are not pipeline stages
and not background jobs in the legacy sense; they are persistent
behaviors that compose into the worm's operational character.

The deep reference is `docs/architecture/lake-side-loops.md`. The table
below is the index; click through for the per-loop spec.

| Loop | Tending behavior | Deep ref |
|---|---|---|
| **L1** | Continuously triages candidate sources mentioned in conversation → proposes new surfaces | [L1](./lake-side-loops.md#l1--source-candidate-triage) |
| **L2** | Continuously detects catalog drift in connected surfaces → acknowledges or flags | [L2](./lake-side-loops.md#l2--catalog-drift-detection) |
| **L3** | Continuously discovers lineage edges between tables and columns → confirms or revises | [L3](./lake-side-loops.md#l3--lineage-discovery) |
| **L4** | Continuously computes schema-impact when surfaces change → elevates governance | [L4](./lake-side-loops.md#l4--schema-impact-analysis) |
| **L5** | Continuously fingerprints columns → identifies semantic types across the lake | [L5](./lake-side-loops.md#l5--column-fingerprinting) |
| **L6** | Continuously classifies columns (PII / confidential / regulated) → confirms or escalates | [L6](./lake-side-loops.md#l6--column-classification) |
| **L7** | Continuously runs quality checks → emits findings to the ledger | [L7](./lake-side-loops.md#l7--quality-checks) |
| **L8** | Continuously stitches entities across surfaces → resolves identity | [L8](./lake-side-loops.md#l8--entity-stitching) |

All eight run concurrently from t=0. All eight produce ledger entries
that fold into the dashboard's `/lake/*` pages as projection views.
Cross-axis chains (L5 → L7, L6 → L4, L5 → L4, L4 ↦ L2) compose the
loops into multi-step inferences; the chains are documented in
`lake-side-loops.md`.

The loops are not aspirational. They ship in the OSS release at
varying levels of maturity (production / preview / coming-soon); the
status pins for each loop are in the deep ref. Capability honesty —
"this loop is production for external surfaces, preview for filedrop,
coming-soon for evidence" — is enforced in the same shape as for
surfaces and channel adapters.

The mental model worth carrying away: **tending is the verb; the lake
is the noun; the eight loops are the grammar.** When a vendor in this
space says "self-healing pipeline" or "AI agent" or "active metadata,"
translate to: "one of our eight lake-side loops, expressed in their
vocabulary." The mapping is usually exact. Drift detection (L2) is
their "self-healing." Classification refresh (L6) is their "active
metadata." Quality checks (L7) are their "data observability." We do
not invent the capabilities; we re-home them into the lake-side
framing so that the lake — not a bolt-on layer — is the unit of
operation.

---

## Architecture

The continuous lake is at the center. Surfaces are the four equal faces
of the lake. Worm-core is depicted as the operator inside the lake —
not a consumer reaching in from outside. Chat platforms are a tending
channel, not a separate input source. The ledger is below the lake,
the substrate that every action is hash-chained from.

```
                                ┌────────────────────────────────────────────────┐
                                │             The continuous lake                │
   ┌─────────────────┐          │                                                │
   │  Chat platforms │          │    ┌──conversation──┐    ┌────external────┐    │
   │  Slack/Discord  │←─tending→│    │ Slack/Discord  │    │ Postgres / SF  │    │
   │  Teams          │          │    │ threads        │    │ S3 / Notion(MCP)│   │
   └────────┬────────┘          │    │ decisions      │    │ Stripe / HubSpot│   │
            │                   │    │ mentions       │    └────────────────┘    │
   ┌────────▼────────┐          │    └────────────────┘                          │
   │ channel-adapter │─writes──→│    ┌────filedrop────┐    ┌────evidence────┐    │
   └─────────────────┘          │    │ dropped CSVs   │    │ notebooks      │    │
                                │    │ evidence PDFs  │    │ data products  │    │
                                │    └────────────────┘    └────────────────┘    │
                                │                                                │
                                │    ┌─────────────────────────────────────────┐ │
                                │    │           worm-core (the tender)        │ │
                                │    │  8 lake-side loops │ lake-maintainer    │ │
                                │    │  catalog-mirror │ autoresearch │ MCP    │ │
                                │    └─────────────────────────────────────────┘ │
                                └────────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │  Postgres ledger│
                                                │ append-only     │
                                                │ hash-chained    │
                                                └─────────────────┘
                                                         ▲
                                          ┌──────────────┴──────────────┐
                                          │ Dashboard │ MCP server      │
                                          │ Next.js   │ FastMCP :9911   │
                                          └─────────────────────────────┘
```

The visual properties to internalise:

- **Lake at the center**, not at the bottom of a pipe.
- **Surfaces as faces**, four equal families, none privileged.
- **Worm-core inside the lake**, the operator — not a consumer outside it.
- **Ledger below the lake**, the substrate every action chains from.
- **Chat platforms as a tending channel**, not as a separate input source
  feeding a separate pipeline.

This diagram is canonical. The same shape appears (with format
variations) in `README.md`, `ARCHITECTURE.md`, the landing page, and
this doc. If you find a diagram in the tree that places connectors as
inputs feeding worm-core from outside, treat it as stale and update it
to match.

---

## What this isn't

The continuous-lake framing is precise. It is not a synonym for any of
the following adjacent products, and the differences are load-bearing.

**Not a Fivetran / Airbyte replacement.** Those products are ELT
pipelines that move data from sources into a warehouse. WormBase
installs *into* your stack; it does not replace the movement layer. If
you already use Fivetran to land data in Snowflake, you continue to.
WormBase connects to the Snowflake surface and tends what is there. The
movement layer and the tending layer are different problems.

**Not a Snowflake / Databricks competitor.** Those products are the
warehouse / lakehouse. WormBase operates ON your warehouse or
lakehouse, not parallel to it. We do not store your data. We do not
compete on query performance, storage cost, or SQL dialect. We tend
whatever lake you have.

**Not bolt-on observability.** Monte Carlo, Bigeye, and the
data-observability category install AS a layer on top of your existing
lake — an external observer reaching in. WormBase is not an observer;
the continuous lake exists because the agent is tending it. The
tending behaviors (drift, classification, lineage, quality) are the
lake's own behaviors, not an aftermarket layer reaching in from outside.

**Not a chatbot.** The chat surface is the install channel and the
audit channel — it is where humans ask questions, give direction, and
hear about what changed. But the substrate is the lake, not the
conversation. The conversation stream is one source family among four;
the lake is everything together. A chatbot has nothing underneath it;
WormBase has a hash-chained ledger underneath every interaction.

**Not "agentic data management."** That phrase is claimed by IBM and
Acceldata and implies a bolt-on agent layer on a pre-existing platform.
WormBase is different in kind: the lake and the agent co-emerge. There
is no "data platform" that exists first, then receives an agent layer.
The two come into being together.

**Not a re-architected lakehouse.** Google's "AI-native lakehouse"
re-engineers the storage substrate for agents. WormBase does not
re-engineer your lake. Your Postgres is still Postgres; your Snowflake
is still Snowflake; your S3 buckets are still S3 buckets. We install
into them as a surface and tend them in place.

**Not a metadata catalog.** Atlan and DataHub maintain a separate
catalog database alongside your lake. WormBase has no separate catalog —
the ledger IS the metadata, and every operation is hash-chained from
it. There is no "sync between the catalog and the lake" because there
are no two things to keep in sync. One substrate, one source of truth,
one audit trail.

**Not a single-tenant product by accident.** Every object in the
continuous lake is `company_id`-scoped from t=0. The SaaS-first
deployment is the default code path; on-prem / customer-VLAN is the
same code path with different credentials. Multi-tenancy is not a
v2 feature retrofitted onto a single-tenant prototype — it is the
shape of the substrate itself.

---

## Cross-references

**Sibling architecture docs.**

- [`docs/architecture/lake-side-loops.md`](./lake-side-loops.md) — Deep
  reference for the eight tending behaviors L1–L8, the cross-axis
  chains, and how loops compose.
- [`docs/architecture/surfaces.md`](./surfaces.md) — Capability-honesty
  reference for the `SurfaceDriver` Protocol; the per-kind status pins
  (production / preview / coming-soon); the promotion bar. *(This doc
  is the post-rename successor to `connectors.md`; if your tree still
  has the latter, treat it as stale.)*
- [`docs/architecture/channel-adapters.md`](./channel-adapters.md) —
  Capability-honesty reference for the channel-adapter side; relevant
  here because channel-adapter writes the `chat_received` entries that
  the conversation surface materializes from.

**Architectural decisions.**

- [`docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md`](./decisions/ADR-0013-continuous-lake-philosophy.md)
  — The architectural commitment behind this framing: the lake exists
  because the agent is tending it; agent and lake are co-emergent;
  differentiated against bolt-on agentic layers.
- [`docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md`](./decisions/ADR-0003-lake-maintainer-pattern.md)
  — The Protocol split between `AcquirableSource` and `MaintainableSource`;
  rationale for why conversation and evidence implement only the
  maintenance face; the dispatch loop.

**Parent doc.**

- [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — The substrate (PEVR,
  ledger, projections), the worm decomposition, and how the continuous
  lake fits inside the broader architectural commitments.

**Source spec.**

- [`docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md`](../superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md)
  — The full design spec this doc distills. Read it for the wave plan,
  the rename scope (Wave D), the open decisions, and the acceptance
  criteria.
