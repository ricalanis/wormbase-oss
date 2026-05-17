# WormBase — Architecture

This document captures the durable architectural commitments of WormBase: the
substrate that every feature lands on, the worm decomposition, and the
doctrines that shape how new work fits in. It is intended for readers who
want to understand or extend the system.

For prose on **why** WormBase is shaped this way (the product thesis, the
positioning), see `README.md`. For the **how to contribute** patterns
(scoping, dispatching, reviewing, merging via agent-orchestrated waves), see
`DEVELOPERS.md`. For **distilled methodology** on running agent-orchestrated
maintenance, see `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`. Authoritative
deep dives on individual subsystems live under `docs/superpowers/specs/`.

If this document conflicts with a newer spec, the spec wins.

---

## 1. The substrate: PEVR + ledger + projections

Everything in WormBase reduces to a single write primitive and a single
read primitive.

### PEVR — the write primitive

Every persistent state change in the system passes through one of four
ledger entry shapes:

- **propose** — a candidate state change is recorded, with provenance.
- **execute** — the change is enacted against the substrate.
- **verify** — the result is checked against expectations.
- **resolve** — the outcome (keep or discard) is committed.

This is the autoresearch loop, generalized to all persistent writes. Domain-
specific entry kinds (e.g. `chat_received`, `source_proposed`,
`kpi_proposed`) are specializations of one of these shapes. The loop's gates,
metrics, and side-effects vary by domain; the structure does not.

### The ledger — the single source of truth

The ledger is an append-only, company-scoped, hash-chained sequence of
entries. Lake, memory, KPI tree, channel history, gate outcomes, person
proposals, data products — all are *materialized views* over the ledger.
Replay the ledger to timestamp T to reproduce any state.

The ledger is the substrate, not a side-channel. There is no truth that
lives outside of it. If a piece of state has no ledger backing, it cannot
be reasoned about, audited, or reproduced.

### Projections — the read primitive

Projections are deterministic functions over the ledger that materialize
the current state of a particular slice (e.g. `projection_persons`,
`projection_kpis`, `projection_data_products`). They live in Postgres for
query performance and are rebuilt by replaying the ledger.

Projections are read by:

- The dashboard (every tab reads only projections).
- The hub's accessors (HTTP and MCP endpoints).
- Downstream worms that need a stable read surface (e.g. governance gates
  reading the current resource ownership map).

Nothing writes to projection tables directly. Writes go through PEVR → the
ledger → the projection runner.

### Doctrine — kinds are forever; payloads are additive-only

Entry kinds are part of the system's durable contract. Once added, a kind
is preserved indefinitely. Payload fields can be added (with safe defaults
that preserve back-compat for older entries) but cannot be removed or
renamed in place. The schema-evolution doctrine in
`docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` records
the current registry size, the freeze-pause threshold, and the addenda
that have shipped to date. For the full audit and rationale behind the
ceiling raises and the per-family caps, see
[doctrine-schema-evolution-review.md](docs/architecture/decisions/doctrine-schema-evolution-review.md).

---

## 2. The worm decomposition

WormBase's runtime is composed of a small **hub** that wires up the world,
plus a set of named-actor **worms** packaged independently. Each worm is a
package; the hub composes them at boot time. No worm imports another worm
directly; cross-worm dependencies flow through the ledger or through
hub-level dependency injection.

### Package layout

```
packages/
├── lake-maintainer/                # lake worm — source acquisition + maintenance
├── wormbase-identity-tracker/      # identity worm — Person / PersonIdentity / Install
├── wormbase-chat-presence/         # chat worm — ingest + speak + budget
├── wormbase-research-loop/         # research worm — autoresearch propose/execute/verify/resolve
├── wormbase-process-extractor/     # process worm — process maps from conversation
├── governance/                     # governance worm — gates that compose into other worms
├── ledger/                         # substrate (entry kinds + projections + replay)
├── reactivities/                   # Reactivity Protocol — registry / runner / primitives
├── lake-surfaces/                  # lake-surface drivers (SurfaceDriver Protocol)¹
├── channel-adapters/               # channel-platform adapters (ChannelAdapter Protocol)
└── ...

apps/
└── worm-core/                      # the hub — CLI / HTTP / MCP / boot orchestration
```

¹ Post-Wave-D rename per [ADR-0013](docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md);
see the [design spec](docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md)
for the full rename scope, which lifts the lake-surfaces package, module,
Protocol, and registry helper into a single naming family.

### The hub's responsibilities

- CLI, HTTP, and MCP entrypoints.
- Onboarding orchestration (cross-worm flows that span multiple worms).
- Projection runner and the canonical projection implementations.
- `write_actions.py` — the ledger write surface called by HTTP and MCP.
- `source_builder.py` — boot-time wiring that integrates lake-maintainer
  per source.
- Shared utilities consumed by package-resident worms via DI:
  `topic_extractor.py`, `resource_aggregator.py`,
  `data_product_actions.py`.
- Boot wiring: one `wire_<worm>_for_<scope>` call per worm, in a fixed
  order. Boot is the only place worms get composed.

### The boot path

```python
await wire_identity_for_install(install, registry, ledger)
await wire_chat_for_install(install, registry, ledger)
await wire_process_for_install(install, registry, ledger)
await wire_research_for_install(install, registry, ledger)
# lake-maintainer is wired per-source via wire_maintenance_for_source
#                  inside source_builder.py (not at boot, not per-install).
# governance     composes into other wires at construction sites
#                  (relevance gate constructor-injected into chat presence;
#                  PII / warmup gates attach at write_actions sites).
#                  There is no wire_governance_for_install by design.
```

The boot path is pinned by an executable test
(`apps/worm-core/tests/test_boot_wires.py`). Adding a new worm means adding
a new `wire_*_for_*` call here, with a corresponding test pin.

See [ADR-0006: Hub redefinition and the four-wire boot path](docs/architecture/decisions/ADR-0006-hub-redefinition-and-four-wire-boot.md)
for why the boot is four wires (not five) by design, and
[ADR-0003](docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md)
for the package template that lake-maintainer established for every
subsequent worm extraction. For the full record of how the
decomposition was planned and executed across six waves, see
[worm-decomposition.md](docs/architecture/orchestration/worm-decomposition.md).

### Rules for new worm work

1. New named-actor work goes in `packages/wormbase-<function>/`, per the
   template established by lake-maintainer: no README, a public surface
   that re-exports from internal modules, a `make_<function>_reactivities`
   factory, a `wire_<function>_for_<event>` lifecycle hook.
2. New writes follow the schema-evolution doctrine. Kinds are forever and
   additive-only.
3. Cross-worm dependencies go through the ledger or through hub utilities
   (DI). Never package-to-package imports.
4. `IdentityResolver` is the only shared Protocol that downstream worms
   consume; instances are provided by the hub.
5. Governance gates compose at construction sites — they are not
   Reactivities and they do not have their own wire function.
6. Test ownership migrates with the module. Tests that pin shim contracts
   intentionally keep the legacy paths.

---

## 3. The continuous lake — agent-installable, co-emergent

The **continuous lake** is the unit of WormBase's operation. It is not a
substrate that pre-exists the agent and then receives an agent layer; it
is co-emergent with the agent from t=0 of install. The chat install
brings the first managed surface (the conversation stream). The lake
install — either by **building** a default local lake or by **connecting**
to an existing warehouse / lakehouse / object store — brings the second.
From that moment forward the lake is continuous and agent-tended: eight
lake-side loops run concurrently, a per-source lake-maintainer detects
drift and refreshes classification, a catalog-mirror folds discovered
structure into the ledger, and the worm-core operates inside the lake
rather than consuming from outside it.

Every tending act materializes through projections over the ledger. The
substrate (§1) and the worm decomposition (§2) are the machinery; the
continuous lake is the shape that machinery takes when the worm is
operating. For the umbrella narrative and the industry-positioning
landscape, see
[`docs/architecture/continuous-lake.md`](docs/architecture/continuous-lake.md)
and [ADR-0013](docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md).
This section is the engineering-facing index into that material.

### 3.1 What the continuous lake is

The continuous lake is four things at once, and the framing is precise.

**It is a lake.** Medallion-tiered (bronze / silver / gold), federated
across whatever surfaces the worm has installed into. The lake may live
locally under `~/.wormbase/lake/{bronze,silver,gold}/`, in a customer's
Snowflake account, in their Postgres warehouse, in an S3 bucket, or
across several of these at once. There is no privileged backing store;
the lake is the union of every surface the worm tends.

**It is continuous.** There is no "lake-build phase" followed by a
"lake-serve phase." From the moment of install, eight lake-side loops
run concurrently and a lake-maintainer is wired per source. The lake's
state is always being tended; "idle" is not a phase the lake passes
through.

**It is agent-operated.** The worm tends the lake; the worm does not
consume from it. Drift detection, classification refresh, lineage
discovery, schema-impact analysis, quality checks, and entity stitching
are lake-side behaviors — not bolt-on observability layers reaching in.
Humans interact with the lake through the chat surface and the
dashboard; both are reads over the same ledger that the worm's tending
behaviors write.

**It is co-emergent.** There is no pre-existing lake that the agent then
arrives to maintain. The chat install brings the first surface; the lake
install brings the second; everything thereafter is tended from t=0.
Install IS the first act of maintenance. The lake exists because the
agent is tending it.

This framing is the inversion of the 2026 industry shared assumption that
"agentic maintenance" is a bolt-on layer over a pre-existing lake. The
distinction is load-bearing — it shapes the install flow, the source
families, and the rename scope.

### 3.2 The two installations

A WormBase install is two acts, not one. Both must complete before the
worm is operational; the order is the user's choice.

**Chat install** wires a `ChannelAdapter` to the worm-core. After the
adapter's OAuth completes, the conversation stream becomes the first
managed surface of the continuous lake. Lurking is bronze ingestion;
threads become silver topics; decisions / processes / mentions become
gold. See §4.

**Lake install** acquires the first non-conversation surface, and has
two paths.

*Build (greenfield).* The default `csv_local` `SurfaceDriver` bootstraps
`~/.wormbase/lake/{bronze,silver,gold}/` (or the container-equivalent
path). Intended for prospects who don't yet have a warehouse — most
SMBs, demo runs, first-time installs.

*Connect (brownfield).* A production-ready `SurfaceDriver` (`postgres`,
`snowflake`, `bigquery`, `s3_csv`, `http_csv`, `stripe`) or an
MCP-bridged surface (`notion`, `hubspot`, `linear`, `atlassian`)
acquires read-side access to an existing lake. Write-side is governed
by Policy.

**Both paths end at the same substrate state.**

- Both produce a `Source` instance with `family` ∈ {`external`,
  `filedrop`, `conversation`, `evidence`}.
- Both trigger the `propose → execute → verify → resolve → trace`
  ledger sequence (the PEVR primitive from §1).
- Both activate the same eight lake-side loops (L1–L8).
- Both become equally tended from t=0 of install.

The hybrid case (default-local lake bootstrapped on day 1, customer's
Postgres connected on day 8) is the common one. The continuous lake
spans both surfaces; the worm tends both equally. The lake is
**federated by default** — surfaces can live wherever a `SurfaceDriver`
can reach, and the ledger projects state from all surfaces uniformly.
There is no privileged surface and no "primary" lake; the continuous
lake is the union of every surface the worm has installed into, and
the ledger is the only thing that knows the union.

The engineering implication of "same end-state, same code-path" is
concrete: the install lifecycle (§7), the role grant defaults (§6),
the projection runners (§1), and every ledger entry written during
install are identical across build and connect. There is no
"greenfield-only" path through the code and no "brownfield-only"
path. A demo run hitting `csv_local` exercises the same code that a
pilot connecting Snowflake does. This is why hybrid is the common case
without requiring a separate code branch: the build path and the
connect path produce the same `Source` shape with the same
provenance.

### 3.3 Four kinds of surfaces

A **surface** is a managed face of the continuous lake. Every surface
the worm tends belongs to one of four source families. They differ in
how the worm *acquires* from them; they do not differ in how the worm
*tends* them.

| Family | Examples | `AcquirableSource` | `MaintainableSource` |
|---|---|---|---|
| **external** | Postgres, Snowflake, BigQuery, S3, Stripe, Notion via MCP, HubSpot via MCP | ✅ | ✅ |
| **filedrop** | CSVs / PDFs dropped in channels, one-off evidence uploads | ✅ | ✅ |
| **conversation** | The chat stream itself — every message, mention, thread, decision | ❌ (read from the ledger, not tabular-acquirable) | ✅ |
| **evidence** | Autoresearch-published notebooks, data products | ❌ (produced internally, not acquired) | ✅ |

All four families are equally lake-resident. None is more "real" than
the others — the conversation lake and the evidence lake are first-class
sources, not auxiliary streams hanging off a primary lake of "real
data." A process map mined from six months of Slack lurking is as much
a lake artifact as a Postgres table; both produce ledger entries, both
are governed, both are tended by the same eight loops.

The critical engineering consequence: **the chat stream IS a source
family**, not an auxiliary channel. Lurking is bronze ingestion. The
same medallion cascade applies. The conversation surface is the first
surface in the continuous lake; the lake install adds the second. The
older OSS framing that put "connector sources" on one side and "chat"
on the other is wrong by this design.

### 3.4 Eight tending behaviors

Eight lake-side loops run continuously from t=0 of install. Each is one
way the worm is tending the lake's state. None of them is a pipeline
stage; none is a background job in the legacy sense. Each is a persistent
behavior that the lake exhibits because the worm is operating inside it.
The deep reference is
[`docs/architecture/lake-side-loops.md`](docs/architecture/lake-side-loops.md);
the table below is the index.

| Loop | Tending behavior |
|---|---|
| [**L1**](docs/architecture/lake-side-loops.md#l1--source-candidate-triage) | Continuously triages candidate sources mentioned in conversation → proposes new surfaces |
| [**L2**](docs/architecture/lake-side-loops.md#l2--catalog-drift-detection) | Continuously detects catalog drift in connected surfaces → acknowledges or flags |
| [**L3**](docs/architecture/lake-side-loops.md#l3--lineage-discovery) | Continuously discovers lineage edges between tables and columns → confirms or revises |
| [**L4**](docs/architecture/lake-side-loops.md#l4--schema-impact-analysis) | Continuously computes schema-impact when surfaces change → elevates governance |
| [**L5**](docs/architecture/lake-side-loops.md#l5--column-fingerprinting) | Continuously fingerprints columns → identifies semantic types across the lake |
| [**L6**](docs/architecture/lake-side-loops.md#l6--column-classification) | Continuously classifies columns (PII / confidential / regulated) → confirms or escalates |
| [**L7**](docs/architecture/lake-side-loops.md#l7--quality-checks) | Continuously runs quality checks → emits findings to the ledger |
| [**L8**](docs/architecture/lake-side-loops.md#l8--entity-stitching) | Continuously stitches entities across surfaces → resolves identity |

All eight run concurrently from t=0. All eight write ledger entries that
fold into the dashboard's `/lake/*` pages as projection views. Each loop
shares the same shape: trigger → strategies → proposals → admin
disposition → confirmed state. The `LakeLoopComposite[T]` pattern is the
implementation surface; the loops differ only in what `T` is and which
strategies tend it.

**Cross-axis chains are the point.** L5 → L7 means "a confirmed
semantic type for a column enables sharper quality checks on it." L6 →
L4 means "a column reclassified as PII elevates the schema-impact of
any change to it." L5 → L4 means "a confirmed semantic type changes
what counts as a schema-impact event." L4 ↦ L2 means "schema-impact
findings inform what counts as drift worth flagging." The loops are
not independent agents running in parallel — they are continuous
tending behaviors that compose, and the composition is what produces
the lake's compounding intelligence over time. The full chain
documentation lives in `lake-side-loops.md`.

The translation against the industry vocabulary is exact and worth
naming. Drift detection (L2) is the underlying primitive vendors call
"self-healing." Classification refresh (L6) is what "active metadata"
vendors describe. Quality checks (L7) are "data observability." Lineage
discovery (L3) and schema-impact (L4) together are what "active lineage"
products sell. WormBase does not invent the capabilities; it re-homes
them into the lake-side framing, so that the lake — not a bolt-on layer
on top of the lake — is the unit of operation. The chains then compose
behaviors that no bolt-on vendor can compose, because the bolt-on
products do not share a substrate.

### 3.5 The SurfaceDriver Protocol

Every external or filedrop surface is acquired through one Protocol:

```python
class SurfaceDriver(Protocol):
    kind: str                          # "stripe" | "postgres" | "snowflake" | ...

    async def authenticate(self, config: Config) -> Handle: ...
    async def discover(self, handle) -> list[ResourceProposal]: ...
    async def profile(self, handle, resource_id) -> Profile: ...
    async def sample(self, handle, resource_id, n) -> bytes: ...
```

Implementations live in `packages/lake-surfaces/` (post-Wave-D rename
per ADR-0013; see the [design spec](docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md)
for the rename scope). Day-one drivers shipping in the OSS release:

- **Production**: `csv_local`, `postgres`, `snowflake`, `s3_csv`,
  `http_csv`, `stripe`.
- **Coming-soon skeletons**: `bigquery`, `salesforce`, `hubspot`,
  `gsheets`, `notion`, `linear`.
- **MCP presets**: `atlassian`, `gworkspace`, `notion`, `hubspot`,
  `github`, `linear` — each a SurfaceDriver wired against a specific
  MCP server, surfaced as an external-family surface.

Adding a new lake surface is a class + JSON-schema config + a registry
entry in `register_surface_driver(...)`. No core code changes. The
lake-install flows — drop-and-profile, credential-in-DM,
mentioned-in-conversation, dashboard "Add a lake surface" form,
KPI-gap-triggered, lake-discovery — are SurfaceDriver-agnostic. Every
flow writes the same `source_proposed → source_confirmed →
source_connected → source_profiled` ledger sequence; every source
carries provenance reconstructable from the ledger.

The capability-honesty discipline (which `SurfaceDriver` is production
vs. preview vs. coming-soon, and what the promotion bar is for each)
lives in [`docs/architecture/surfaces.md`](docs/architecture/surfaces.md)
(post-Wave-C rename name). For the broader semantic-layer story —
agent-gateway MCP surface, `QuerySpec`, the compounding query loop, and
how the design relates to the 2026 industry zeitgeist — see
[semantic-layer-best-practices.md](docs/architecture/synthesis/semantic-layer-best-practices.md).

### 3.6 Composition with lake-maintainer

The split between *acquisition* and *maintenance* was made explicit in
[ADR-0003](docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md)
and is what lets the four source families share one tending machinery
without conflating their acquisition faces. Before the split,
"connector" and "maintainer" were entangled in a single Protocol that
made sense for external surfaces but not for conversation or evidence
— neither of which is "acquired" in the tabular sense. After the split,
each family is honest about what it can do.

Two Protocols, both home in `packages/lake-surfaces/` (post-Wave-D per
ADR-0013):

- **`AcquirableSource`** — the acquisition face. External and filedrop
  surfaces implement it; conversation and evidence do not.
- **`MaintainableSource`** — the universal tending face. All four
  families implement it. Methods include `detect_drift`,
  `refresh_classification`, `staleness_signal`, and `lineage_health`.

The `SurfaceDriver` is the *driver* — kind="stripe", stateless, owns
the wire protocol against a specific provider. A `Source` instance
(per-instance metadata: id, domain, owner) wraps the driver with the
governance attributes that make the surface auditable. Sources implement
zero or both Protocols depending on family.

The `lake-maintainer` package (still home of the Reactivity-driven
dispatch machinery) imports both Protocols from `lake-surfaces/`,
iterates `MaintainableSource` instances per source, and runs the
tending loop. The dependency direction is one-way:
`lake-maintainer/` depends on `lake-surfaces/`, never the reverse.
`wire_maintenance_for_source` (the per-source factory inside
`source_builder.py`) is the hub-level hookpoint that activates
maintenance for every `Source` produced by every install path. There
is no `wire_maintainer_for_install` because maintenance is a
per-source concern, not a per-install concern; the boot path (§2)
intentionally omits it for that reason.

The composition matters because it is what makes the four source
families uniformly tendable. The lake-maintainer does not know — or
need to know — whether the `MaintainableSource` it is iterating is a
Postgres table, a dropped CSV, a Slack channel's conversation, or an
autoresearch-published notebook. The tending behaviors fire identically
across all four; the acquisition shape (or its absence) is the
family-specific concern, factored out into `AcquirableSource` where it
belongs. This is the engineering expression of "all four families are
equally lake-resident" from §3.3.

See [ADR-0003](docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md)
for the Protocol-split rationale and
[ADR-0013](docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md)
for why the Protocols' home is `lake-surfaces/` post-rename.

---

## 4. The ChannelAdapter contract — chat platforms are pluggable

```python
class ChannelAdapter(Protocol):
    platform: Platform              # "slack" | "discord" | "teams" | "whatsapp" | ...
    capability: set[ChannelCap]     # {ingest, send, file_upload, dm, voice}

    async def authenticate(self, secrets) -> AuthHandle: ...
    async def install(self, handle) -> InstallRecord: ...
    async def listen(self, handle) -> AsyncIterator[InfraEvent]: ...
    async def send(self, handle, channel, msg) -> MessageRef: ...
    async def list_workspace_members(self, handle) -> list[PlatformMember]: ...
```

Every wire event normalizes to a single `InfraEvent` shape carrying both
the platform-native ids and the WormBase-internal `channel_id` /
`person_id` (resolved at ingest time). Downstream code reasons about the
internal ids, never about platform-native ids — except in the merge
surfaces on `/channels` and `/people`.

See [ADR-0001: Listener-shaped channel adapter](docs/architecture/decisions/ADR-0001-listener-shaped-channel-adapter.md)
for the decision behind the listener-shaped capture path, and
[ADR-0004: Chat Presence reactivity](docs/architecture/decisions/ADR-0004-chat-presence-package.md)
for the package that consumes the captured stream. For a deep dive on
OpenClaw's onboarding pattern (the gateway WormBase uses) and how its
load-bearing primitives translate to an institutional analog, see
[openclaw-integration-patterns.md](docs/architecture/case-studies/openclaw-integration-patterns.md).

### Conversation provenance

Every `InfraEvent` and `ChatReceivedPayload` carries three additive
provenance fields (defaults preserve back-compat for older entries):

- `delivery_mode: Literal["push", "history_sync"] = "push"` — was this a
  live wire event, or part of a bulk replay?
- `platform_ts: datetime | None = None` — platform-clock authorship time,
  distinct from the ledger-ingest `entry.ts`.
- `history_sync_id: str | None = None` — when `delivery_mode == "history_sync"`,
  the str-UUID of the parent `conversation_sync` ledger entry's `sync_id`.

`conversation_sync` is the per-session lineage entry kind. One PEVR cycle
per reconnect, initial-connect, or channel-join; written at session end
with accumulated `channels`, `message_count`, `earliest_ts`, `latest_ts`,
and `status ∈ {completed, interrupted}`. Per-message `chat_received`
entries from the same session reference it via `history_sync_id`.

`is_live` is a derived predicate, not a stored flag. It is computed from
`delivery_mode == "push" AND (entry.ts - platform_ts) < freshness_window`
(default 60 s).

### Speak vs. ingest

The bronze-cascade ingest path accepts all delivery modes — the conversation
lake must include history-replayed messages, or a freshly-installed worm
gets only post-install conversation. The speak path is filtered: speak
reactivities compose `LiveOnly() & DomainEnabled()` (or similar) and do
not fire on history-replay or stale push events.

The full architectural spec for conversation provenance is at
`docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md`.

---

## 5. Identity model

Three durable concepts, each backed by a ledger-projected table:

```
Person {id, tenant_id, name, email, position, status, created_at,
        proposed_by, confirmed_by}

PersonIdentity {id, person_id, platform, platform_user_id, display_name,
                email_at_platform, avatar_url, added_at}

Install {id, tenant_id, platform, installer_person_id, oauth_grant,
         installed_at, status, scopes, bot_user_id}
```

One `Person` per real human (or service account). `PersonIdentity` is the
multi-platform fan-out: `@bob` on Slack and `bob#1234` on Discord are two
`PersonIdentity` rows pointing at one `person_id`. `Install` is the OAuth
grant, one per `(tenant, platform)`, with the installer's `person_id`
linked.

**Auto-discovery.** Any unknown `platform_user_id` in a wire event triggers
`emit_person_proposed`. The discovery loop fetches the platform's
workspace member metadata, attempts an email-match against existing
`Person` rows, and either proposes a new `Person + PersonIdentity` or
proposes an identity link to an existing `Person`. Administrators confirm
via the `/people` surface.

**Identity merge and split.** Administrator-only operations on `/people`.
Both write ledger entries (`emit_identity_linked` / `emit_identity_unlinked`)
with a full audit trail.

See [ADR-0007: IdentityResolver Protocol](docs/architecture/decisions/ADR-0007-identity-resolver-protocol.md)
for the frozen Protocol surface that downstream worms consume via DI from
the hub.

---

## 6. Roles — three independent facets

| Facet | Roles | Ledger entry |
|---|---|---|
| **Tenancy** | installer / admin / member / observer | `emit_role_assigned` |
| **Domain** | owner / contributor | `emit_domain_role_assigned` |
| **Resource** | maintainer / contributor | `emit_resource_role_assigned` |

A Person holds **N grants** across all three facets simultaneously. The
facets are independent and composable: Carol can be
`tenancy.admin + domain.owner(finance) + resource.maintainer(kpi.q3_net_revenue)`
as three independent grants. The `/people` surface renders a Person's full
role surface as a flat join.

**Defaults.** The installer auto-receives
`tenancy.installer + tenancy.admin + domain.owner(every domain in the picked
pack)`. A confirmed Person defaults to `tenancy.member`. The worm proposes
`resource.maintainer` grants from chatter signal; administrators confirm.

**Revocation.** `emit_role_revoked`, `emit_domain_role_revoked`,
`emit_resource_role_revoked`. All revocations leave audit trails.

---

## 7. Install lifecycle

| Tier | What happens | Target SLA |
|---|---|---|
| 0 | Landing page; "Connect to <platform>" per supported `ChannelAdapter`. | — |
| 1 | OAuth → tenant created → installer `Person` created → `Install` row → role grants written. | ≤ 30 s |
| 2 | Domain-pack picker + co-admin invites + classification defaults. | ≤ 20 s |
| 3 | First source connect + first KPI proposed. | ≤ 10 s |
| Aha | Worm posted in channel + bronze cascade visible + KPI proposed + ramp first-moved. | ≤ 60 s total |

Auto-team-discovery runs from the first wire event onward. Within seven
days, every chatter in every connected channel has a proposed `Person`
row. Position assignment auto-proposes from chatter signal; administrators
confirm. Once a Person has a position, autoresearch starts firing for
them.

For a stage-by-stage walkthrough of the customer journey from discovery
through day-100 operating state (including the seams between Tier 0 and
the semantic-layer agent surface), see
[customer-journey.md](docs/architecture/product/customer-journey.md).
For the architectural proposal that extends the OpenClaw onboarding
pattern across the full institutional ontology, see
[institutional-onboarding-proposal.md](docs/architecture/product/institutional-onboarding-proposal.md).

---

## 8. The dashboard — production surface, not a demo screen

The dashboard is the product surface. Every tab:

- Reads only ledger projections.
- Is multi-tenant safe.
- Renders correctly under each role lens (installer / admin / member /
  observer).
- Has at least one daily-use surface for at least one role.
- Carries no fixture loads, no hardcoded persona lists, no platform-only
  assumptions.

Core surfaces include:

- `/people` — Person CRUD, pending proposals, identity merge/split, role
  grants across all three facets, audit log.
- `/channels` — install per platform, channel roster, lurk-vs-respond per
  channel.
- `/sources` and `/sources/new` — source list and a lake-surface picker
  generated from the `SurfaceDriver` registry.
- `/kpis`, `/domains`, `/policies`, `/decisions`, `/processes`,
  `/system-map`, `/research`, `/activity`, `/trace`, `/dashboard`,
  `/onboarding` — the substrate views.
- Tenant + Person + role chip in the header on every page; role-aware
  navigation chrome.

Every tab is filtered by the current Person's role grants and exposes a
role-aware header chip.

---

## 9. Sim — production-shaped staging

Sim-harness drives **real channel platforms** with real bot accounts.
Personas post real messages, upload real files, send real DMs. Person
provisioning happens through the dashboard's Person API — the same path a
real install uses.

The deterministic backstop for testing and demos is `wire-replay`. It
loads a recorded JSONL of `InfraEvent`s and feeds them through the
channel-adapter at production speed. Same code path; different input
source. There are no flow-bypass shortcuts in the repo; if a flow does
not fire end-to-end on the live wire, fix the wire.

---

## 10. Hygiene invariants

A handful of patterns leak the demo-only mindset into the production code
path; the codebase actively pushes back on them. Standing invariants:

- No `_private` attributes reached from outside their owning module.
  Promote to public methods or extract a public view class.
- No platform-specific assumptions in code that claims to be
  channel-agnostic. Extract to the relevant `ChannelAdapter`.
- No source-type-specific code paths in source-builders. Extract to
  `SurfaceDriver` implementations.
- No hardcoded persona or user lists in the dashboard. Read from the
  ledger.
- No `fixtures/` references in production code. Fixtures are sim-only or
  replay-only; never production.
- No "TODO demo" / "mock for demo" / "fake for now" comments.
- No unconditional fixture returns from production read accessors. Return
  `[]` and let the panel render an honest empty state. Conditional
  `if (rows.length === 0) return FALLBACK` is sanctioned (Postgres-empty
  fallback); unconditional `return FALLBACK` is not.
- No self-grant placeholders in role-grant POSTs. Thread the current
  administrator's Person id through from `getCurrentPerson(companyId)`;
  never record the target as the granter.
- Every tab carries a visible empty state when its read accessor returns
  `[]`. Silent panels are demo seams disguised as design.

These invariants are enforced at commit time by gates under `tests/demo/`
(see `tests/demo/test_N2_no_placeholders_on_screen.py`).

For empirical numbers on the load-bearing hot paths (ledger-scan
gather, projection-promoted gather, cosine vs substring clustering,
EmbeddingService cache + concurrency, ReactivityRunner dispatch), see
[performance/baseline.md](docs/architecture/performance/baseline.md).
Operator runbooks for the pgvector HNSW index and cross-model embedding
migration live alongside it.

---

## 10.5. Test invocation

Cross-package `pytest packages/` from the workspace root is unsupported by
design. Each package owns its own `tests/conftest.py`, and pytest cannot
load many sibling conftests under one rootdir without colliding on the
`tests.conftest` module name. The workspace-root `pyproject.toml` pins
`testpaths = ["tests"]` to keep a bare `uv run pytest` from triggering the
collision.

Supported invocations:

- `make test-all` — loops every package, app, and the workspace `tests/`
  and runs pytest in each with `--extra dev`. Use this for the full suite.
- `uv run pytest packages/<name>/tests/` — single-package run from the
  workspace root. The `--package wormbase-<name>` flag is preferred when
  the package needs its own resolved dependencies.
- `uv run pytest tests/` — workspace-only suite (contract, integration,
  demo, property, chaos, multi-tenant; lives outside any package).
- `make test`, `make qa`, `make qa-fast` — curated layer-targeted runs
  used in CI; each loops the right per-package commands internally.

If you need cross-package collection from the workspace root, extend
`make test-all`; do not run `pytest packages/`.

---

## When in doubt

1. Read the relevant spec under `docs/superpowers/specs/`.
2. Read the latest close-out for the area you are touching under
   `docs/superpowers/notes/`.
3. Ship the production path; fix the wire; no toys.
