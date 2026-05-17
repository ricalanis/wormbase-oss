# Worm Decomposition

WormBase's runtime began as a single application — `apps/worm-core` — that
absorbed every responsibility the system had: chat ingest, identity
resolution, autoresearch, process extraction, source maintenance,
governance gates, and the orchestrating glue between them. The
decomposition described here split that monolith into a small hub plus
five named-actor worms packaged independently, with governance
consolidated as its own concern. The end result is the architecture
visible today under `packages/` and `apps/worm-core/`.

This document records why the decomposition happened, the template that
shaped every extraction, the per-worm scope decisions, and the calibration
findings that updated long-standing assumptions about the codebase.

---

## Why decompose

A single-package monolith made the worm's pitch ambiguous. Was WormBase a
chat assistant? An institutional-AI substrate? A data-source watcher? The
codebase did all three but the directory structure said only one — and the
pitch oscillated.

The lake-maintainer extraction (the first worm carved out of `worm-core`)
proved the worms-as-packages pattern was tractable. That extraction
produced ~1,400 LOC of net new code, 75% lift and 25% rewrite, across 19
atomic commits and 9 plan blocks, with zero regressions across 2,725+
tests. It composed cleanly with the existing `ReactivityRegistry` and
`ReactivityRunner` — no new orchestrator loop was required.

The argument for finishing the decomposition followed directly: while the
pattern was fresh and the calibration was sharp, extract every remaining
named-actor concern. The product of the decomposition — six packages on
a shared ledger substrate — becomes the architecture diagram, which
becomes the pitch deck's first slide.

---

## The portfolio

Six worms shipped across the decomposition. Each became its own package
under `packages/`.

| Worm | Package | Scope |
|---|---|---|
| lake-worm | `packages/lake-maintainer` | Per-source acquisition + maintenance; composes with the W5a Reactivity registry. |
| chat-worm | `packages/wormbase-chat-presence` | Chat ingest, relevance, mention-response, interjection budget, the `ChatReply` PEVR primitive. |
| identity-worm | `packages/wormbase-identity-tracker` | Person, PersonIdentity, Install; the frozen `IdentityResolver` Protocol that downstream worms consume. |
| research-worm | `packages/wormbase-research-loop` | Autoresearch propose/execute/verify/resolve; phenomenon-gap composition with W5b detectors. |
| process-worm | `packages/wormbase-process-extractor` | Topic synthesis, recurring-question mapping, decision recording, system-map nodes. |
| governance-worm | `packages/governance` | PII, warmup, interjection, relevance, knowledge gates consolidated under one `PolicyGate` Protocol. |

The hub — `apps/worm-core` — became the runtime composer: CLI / HTTP /
MCP entrypoints, onboarding orchestration across worms, the projection
runner, the `write_actions.py` write surface, and a few shared utilities
consumed via dependency injection.

---

## The canonical extraction template

Every worm extraction conformed to one structural template, derived from
the lake-maintainer wave. Deviating from the template wasted the lessons
already paid for. The template has three layers: package shape, plan
shape, and the pre-execution ritual.

### Package shape

```
packages/wormbase-<function>/
├── pyproject.toml                       # workspace package
├── src/wormbase_<function>/
│   ├── __init__.py                      # public surface re-exports only
│   ├── types.py                         # dataclasses + Protocols
│   ├── reactivities.py                  # one Reactivity per agent action
│   ├── factory.py                       # make_<function>_reactivities(ctx)
│   ├── lifecycle.py                     # wire_<function>_for_<event>(...)
│   └── <domain>.py                      # heuristics/logic lifted from worm-core
└── tests/
    ├── test_types.py
    ├── test_factory.py
    ├── test_reactivities.py             # one test per Reactivity, real InMemoryLedger
    └── conformance/test_<function>_conformance.py
```

No README per package. Public surface lives in `__init__.py` re-exports
only. Tests live with the package they pin.

### Plan shape — nine blocks

Each extraction's written plan followed the same nine-block structure:

| Block | Purpose |
|---|---|
| A | Migrations (new projections or columns, if any) |
| B | Protocols + types + package scaffolding |
| C | Core implementation class(es) replacing worm-core modules |
| D | Family-specific implementations where heterogeneous |
| E | Storage / projection-read helpers |
| F | Reactivities — one class per agent action |
| G | Factory + hub-side `wire_…` integration |
| H | Optional ports (additional Protocol surfaces) |
| I | Integration tests (end-to-end: ledger → reactivity → output) |

### Pre-execution ritual

Three steps, in order, before any subagent dispatch:

1. **Live API verification pass.** Read live shapes for everything the
   plan references — Protocols, projection columns, ledger primitives,
   registry signatures. This step caught nine or more API mismatches in
   the lake-maintainer plan alone.
2. **Patch the corrections preamble** at the top of the plan with verified
   shapes and a "test-code correction principle" if mechanical type
   renames are pervasive.
3. **Dispatch.** Subagents adapt to the preamble faithfully.

This pre-flight check is the single highest-leverage move in the
extraction template. Skipping it costs hours of subagent rework.

---

## Module-ownership decisions

The portfolio's hardest design question was not "what is a worm" but "who
owns this specific module." Several modules looked like they belonged to
one worm at first read and another worm on second read. The decomposition
locked these decisions before dispatching plan-writers so no extraction
could second-guess module ownership mid-flight.

| Module / concept | Decision | Rationale |
|---|---|---|
| `topic_extractor.py` | Stays in worm-core hub | Used by both `owner_lookup.py` (identity-worm consumer) and chat flows. Hub utility consumed via DI by both worms. |
| `resource_aggregator.py` | Stays in worm-core hub | Aggregates ledger reads across KPIs, sources, decisions, processes, and data products by domain. Hub utility shared by multiple consumers. |
| `data_product_actions.py` | Stays in worm-core hub | 621 LOC of pure PEVR emission helpers; no synthesis logic. Synthesis lives at call sites. |
| `setup_conversation.py` | Splits at the `wormbase_core.write_actions` import line | DM driver lifts into chat-worm; orchestration stays in `worm-core/onboarding`. |
| `lurker.py` (`SlackLurker`) | Stays in worm-core | Hard `slack_bolt` dependency; the channel-adapter log-tail path is canonical. |
| `classifier.py` | Moves to chat-worm package, internal | The `inference-router` package was empty at extraction time; empty-package instantiation on a critical path is the wrong trade-off. |
| `heuristic_loop.py` | Deleted entirely | Test-only consumers; zero production callers. |
| `process_extractor.py` (~970 LOC) | Deleted after lifting synthesis to Reactivities | The signature commit of the process-worm wave. |
| P10 `RecurringQuestionProcessMapperReactivity` | Wire existing implementation | Already extracted into `packages/reactivities/`; the wave registers it, doesn't lift it. |
| `IdentityResolver` Protocol | Frozen at four methods with revised shape | `propose_person` returns `ProposalRef`; `lookup_owner` takes a `Topic`; `lookup_team` returns typed `TeamMembership` rows. |
| Identity merge / split | Stays in worm-core as admin HTTP routes | Not Reactivity-shaped; admin-only orchestration of unlink/link/archive primitives. |

The recurring lesson: **inter-worm dependencies are dependencies on the
ledger or on hub utilities, never on another worm's package.** Modules
that would create cross-package imports stay in the hub and are consumed
via dependency injection.

---

## Boot path

The boot path is pinned by `apps/worm-core/tests/test_boot_wires.py`.
Adding a new worm means adding a new `wire_*_for_install` call here, with
a corresponding test pin.

```python
async def boot(install: Install, registry: ReactivityRegistry, ledger: Ledger) -> None:
    await wire_identity_for_install(install, registry, ledger)
    await wire_chat_for_install(install, registry, ledger)
    await wire_process_for_install(install, registry, ledger)
    await wire_research_for_install(install, registry, ledger)
    # lake-maintainer wires per-source via wire_maintenance_for_source
    #                  inside source_builder.py, not at boot, not per-install.
    # governance     composes into other wires at construction sites
    #                  (relevance gate constructor-injected into chat presence;
    #                  PII / warmup gates attach at write_actions sites).
    #                  There is no wire_governance_for_install by design.
```

The decomposition's working assumption — encoded in early plans — was
that the boot path would settle on five wires (one per worm). The actual
shape is four. Lake-maintainer wires per-source rather than per-install,
and governance does not wire at all — it composes into other wires at
construction sites. Both deviations are intentional and documented in
[ADR-0006](../decisions/ADR-0006-hub-redefinition-and-four-wire-boot.md).

---

## Hub responsibilities

After the decomposition, the hub stabilized at 27 modules and 3
subpackages. Its responsibilities reduce to five categories:

- **Entrypoints** — `cli.py`, `http_api.py`, `mcp_server.py`,
  `mcp_tools/`.
- **Onboarding orchestration** — `onboarding/` for cross-worm flows that
  span multiple worms.
- **Projection runner + projections** — `projection_runner.py`,
  `projections/` including `composite_score`, `keep_rate`,
  `knowledge_ramp`, `first_knowings`.
- **Write surface** — `write_actions.py` is the ledger-write surface
  called by HTTP and MCP.
- **Boot-time wiring** — `source_builder.py` integrates lake-maintainer
  per source.

Three hub utilities are consumed by package-resident worms via
dependency injection: `topic_extractor.py`, `resource_aggregator.py`,
`data_product_actions.py`.

Six surviving shims (`owner_lookup.py`, `team_lookup.py`, `positions.py`,
`identity_discovery.py`, `classifier.py`, `relevance.py`) all forward to
their package-canonical homes. They exist as legitimate compatibility
surfaces for external test callers and migration windows; each has at
least one active caller.

---

## Rules for new worm work

The decomposition produced six durable rules that govern every new piece
of named-actor work:

1. **New named-actor work goes in `packages/wormbase-<function>/`** per
   the lake-maintainer template — no README, public surface re-exports,
   `make_<function>_reactivities` factory, `wire_<function>_for_<event>`
   lifecycle hook.
2. **New writes follow the schema-evolution doctrine.** Kinds are forever
   and additive-only. See
   `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`.
3. **Cross-worm dependencies go through the ledger or hub utilities (DI),
   never package-to-package imports.**
4. **`IdentityResolver` is the only shared Protocol** that downstream
   worms consume; instances come from the hub.
5. **Governance gates compose at construction sites** — they are not
   Reactivities and do not have their own wire function.
6. **Test ownership migrates with the module.** Tests that pin shim
   contracts intentionally keep the legacy paths.

---

## Calibration findings

Several assumptions baked into early plans turned out to be off when
measured against the actual code. The decomposition surfaced four
calibrations worth noting because they affect future scoping:

| Finding | Original claim | Actual |
|---|---|---|
| Wires at boot | Five `wire_*_for_install` calls | Four; lake per-source; governance via construction |
| Registry size pre-decomposition | "~28 kinds" (doctrine §2.5 at writing) | 71 concrete kinds |
| Registry size post-decomposition | "~32 → ~34" projection | 74 concrete kinds (chat-worm added four `chat_reply_*` kinds) |
| Hub module count pre-decomposition | "~35 modules" | 27 modules + 3 subpackages |
| Process-worm net code change | "net negative" projection | -1,333 LOC verified |

The biggest implication: the schema-evolution doctrine's freeze-pause
threshold of 50 kinds was already breached before the decomposition
started. The portfolio took the registry to 74 and the doctrine was
amended (Addendum 1) to raise the threshold to ~100. A subsequent review
(see [Schema Evolution Doctrine Review](../decisions/doctrine-schema-evolution-review.md))
raised it further. The L-axis compounding-loop pattern that drives
ongoing kind growth is now explicitly named in the doctrine as
architecture, not sprawl.

---

## What this changed

**Architecturally**, the codebase now has a directory that doubles as a
pitch slide. The chat-vs-institutional-AI tension dissolves at the
`packages/` level: lake-maintainer, identity-tracker, chat-presence,
research-loop, process-extractor, and governance are six named agents on
a shared ledger substrate.

**Operationally**, the hub is small and stable enough that new feature
work no longer pressures it. New worm-shaped responsibilities ship as
their own packages following the canonical template; the hub does not
absorb them.

**Engineering-process-wise**, the decomposition validated three patterns:

- **Pre-execution verification ritual** is non-negotiable. It saves more
  time than it costs by an order of magnitude.
- **Parallel dispatch** is genuinely parallel for file-disjoint waves —
  research-worm and process-worm extractions ran concurrently with zero
  conflicts. The cost is human review bandwidth, not engineering risk.
- **Cross-worm circular dependencies are structurally prevented** by the
  ledger-as-substrate commitment. Worms read each other's writes
  through the ledger; no worm imports another worm's package.

---

## Cross-references

- [ADR-0003: Lake-Maintainer package pattern](../decisions/ADR-0003-lake-maintainer-pattern.md)
  — the originating template every other worm followed.
- [ADR-0004: Chat Presence reactivity package](../decisions/ADR-0004-chat-presence-package.md)
- [ADR-0005: Composable governance gates](../decisions/ADR-0005-composable-governance-gates.md)
- [ADR-0006: Hub redefinition and four-wire boot path](../decisions/ADR-0006-hub-redefinition-and-four-wire-boot.md)
- [ADR-0007: IdentityResolver Protocol](../decisions/ADR-0007-identity-resolver-protocol.md)
- [ADR-0008: Process extractor as Reactivities](../decisions/ADR-0008-process-extractor-as-reactivities.md)
- [ADR-0009: Research loop as Reactivities](../decisions/ADR-0009-research-loop-as-reactivities.md)
- [Schema-evolution doctrine](../../superpowers/specs/2026-05-03-schema-evolution-doctrine.md)
- [Schema-evolution doctrine review](../decisions/doctrine-schema-evolution-review.md)
- [`ARCHITECTURE.md` §2](../../../ARCHITECTURE.md) — the durable architectural shape this decomposition produced.
