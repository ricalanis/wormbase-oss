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
├── connectors/                     # data-source adapters (Connector Protocol)
├── channel-adapters/               # channel-platform adapters (ChannelAdapter Protocol)
└── ...

apps/
└── worm-core/                      # the hub — CLI / HTTP / MCP / boot orchestration
```

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

## 3. The Connector contract — data sources are pluggable

Every data source implements one Protocol:

```python
class Connector(Protocol):
    kind: str                          # "stripe" | "snowflake" | "csv" | ...
    capability: set[Capability]        # {discover, profile, sample, watch}
    classification_hints: list[Hint]

    async def authenticate(self, secrets) -> AuthHandle: ...
    async def discover(self, handle) -> list[ResourceProposal]: ...
    async def profile(self, handle, resource_id) -> Profile: ...
    async def sample(self, handle, resource_id, n) -> bytes: ...
    async def watch(self, handle, resource_id) -> AsyncIterator[Change]: ...
```

Implementations live in `packages/connectors/`. Day-one connectors include
`csv_local`, `postgres`, `snowflake`, `bigquery`, `s3_csv`, `stripe`,
`salesforce`, `hubspot`, `gsheets`, `http_csv`.

Adding a new connector means adding a class, a JSON-schema config, and a
registry entry. No core code changes to add a connector. The source-building
flows (drop-and-profile, credential-in-DM, mentioned-in-conversation,
dashboard-form, KPI-gap-triggered, lake-discovery) are connector-agnostic.

For the broader semantic-layer story that the connector contract feeds
— the agent-gateway MCP surface, `QuerySpec`, the compounding query
loop, and how the design relates to the 2026 industry zeitgeist — see
[semantic-layer-best-practices.md](docs/architecture/synthesis/semantic-layer-best-practices.md).

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
- `/sources` and `/sources/new` — source list and a connector picker
  generated from the `Connector` registry.
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
  `Connector` implementations.
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
