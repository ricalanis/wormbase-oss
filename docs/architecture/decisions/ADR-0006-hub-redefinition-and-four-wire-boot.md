# ADR-0006: Hub redefinition and the four-wire boot path

**Status:** Accepted
**Date:** 2026-05-03

## Context

After the named-actor worms were extracted into their own packages
(identity-tracker, chat-presence, process-extractor, research-loop,
governance, lake-maintainer), the `apps/worm-core` directory needed a clear
post-decomposition shape. The original orchestration framing described
"five `wire_*_for_install` calls" at boot — one per named worm. The actual
state of the tree after each extraction was not yet pinned by a contract.

Verifying the real shape was necessary before any further consolidation:
which modules are hub-canonical? Which are shims? Which are dead-by-
architecture but still imported? What is the actual boot path versus the
orchestration-doc target?

## Decision

The `apps/worm-core` hub stabilizes at **27 modules + 3 subpackages**
(down from the original ~35), with a precisely-pinned boot path:

```python
await wire_identity_for_install(install, registry, ledger)
await wire_chat_for_install(install, registry, ledger)
await wire_process_for_install(install, registry, ledger)
await wire_research_for_install(install, registry, ledger)
```

**The boot path calls four `wire_*_for_install`s, not five.** Two
ostensibly-missing wires are intentionally absent:

- `wire_lake_for_install` does not exist. Lake-maintainer's lifecycle hook
  is `wire_maintenance_for_source` (per-source, not per-install), wired
  inside `source_builder.py` rather than at boot. The lake is
  source-shaped, not install-shaped.
- `wire_governance_for_install` does not exist. Governance gates compose
  into other wires at construction sites (relevance gate is
  constructor-injected into chat-presence; PII / warmup gates attach at
  `write_actions` sites). Governance is not a Reactivity-shaped worm; it
  has no dispatch loop to wire.

The orchestration doc's "5× wire" framing is descriptive, not contractual.
Adding the missing two wires would be net cosmetic — they'd just call into
existing per-source / per-write paths. This decision codifies the **current
4-wire boot path as correct** and pins it with a regression test
(`apps/worm-core/tests/test_boot_wires.py`).

The hub's responsibilities are precisely:

- CLI / HTTP / MCP entrypoints.
- Onboarding orchestration (cross-worm flows that span multiple worms).
- Projection runner and the canonical projection implementations
  (`composite_score`, `keep_rate`, `knowledge_ramp`, `first_knowings`).
- `write_actions.py` — the ledger write surface called by HTTP / MCP.
- `source_builder.py` — boot-time wirer that integrates lake-maintainer
  per source.
- Shared utilities consumed via DI by package-resident worms:
  `topic_extractor.py`, `resource_aggregator.py`, `data_product_actions.py`.
- Six surviving shims (`owner_lookup.py`, `team_lookup.py`, `positions.py`,
  `identity_discovery.py`, `classifier.py`, `relevance.py`) — all forward
  to their package-canonical homes. None are dead. The shims are a
  legitimate compatibility surface for external test callers and migration
  windows.

The hub redefinition wave deletes zero modules. Production direct-import
surface to legacy shims drops to zero after repointing two known callers
(research-loop's imports of `wormbase_core.positions`; cli.py's import of
`wormbase_core.owner_lookup`).

## Consequences

**Positive:**

- The boot path is now a contract, pinned by an executable test. Future
  refactors that accidentally drop a wire fail loudly at the test layer
  before they reach production.
- The "five wires" framing is corrected to "four wires by design plus two
  by-composition" — this is a more honest description of the architecture
  and is the canonical reference for new contributors.
- The hub's responsibilities are explicit and bounded. New named-actor
  worms go in their own package; the hub does not absorb them.
- Shims are kept rather than aggressively deleted. The cost of a shim is
  ~20 LOC; the cost of breaking external test callers and migration
  windows is much higher.

**Negative:**

- Six shims survive indefinitely as a compatibility surface. Each shim is a
  small ongoing cognitive tax — readers have to follow the re-export chain
  to find the canonical home.
- The "5× wire" mental model in older documentation is wrong. The
  orchestration doc, related plans, and any onboarding material that
  referenced the five-wire shape need updating.
- Hub utilities consumed via DI (`topic_extractor`, `resource_aggregator`,
  `data_product_actions`) blur the line between "hub code" and "shared
  library." They are hub-resident because their callers are heterogeneous;
  a future wave could lift them into their own packages, but only with a
  second consumer.

**Neutral:**

- Two ambiguous modules (`conversation.py`, `lurker.py`) remain in the hub.
  `ConversationContract` is consumed only by `service.build_worm_core`;
  `SlackLurker` is consumed by `service.py` and the sim-harness seed.
  Neither is dead; neither warrants a package extraction.
- Tests that pin shim contracts (`test_identity_shim_imports.py`,
  `test_boot_wires.py`) intentionally keep the legacy paths. Migrating them
  would lose the regression coverage that the shims still work.

## Cross-references

- Related ADRs: ADR-0003, ADR-0004, ADR-0005, ADR-0007, ADR-0008, ADR-0009
  (the worm-decomposition portfolio whose final shape this ADR pins).
- Architecture: `ARCHITECTURE.md` §2 ("The worm decomposition") describes
  the four-wire boot path codified by this decision.
