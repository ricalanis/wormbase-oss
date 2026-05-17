# ADR-0005: Composable governance gates and policy-as-code

**Status:** Accepted
**Date:** 2026-05-03

## Context

Governance in WormBase is policy-as-code: every rule that touches a
persistent write is expressed as a gate that fires through the same PEVR
substrate as every other action. By mid-2026, four gates lived in
`packages/governance` (`PIIGate`, `WarmupGate`, `InterjectionGate`,
`KnowledgeGate`, `MaskedColumnRefusalGate`), but a fifth gate
(`RulesBasedRelevanceGate`) lived in two byte-for-byte duplicate copies —
one in `apps/worm-core/src/wormbase_core/relevance.py` and one in
`packages/wormbase-chat-presence/src/wormbase_chat_presence/relevance.py`.
Neither was canonical; both were live; the chat-presence copy was injected
via the W5a `extras` carrier while the worm-core copy was wired through
`build_worm_core`.

Two governance result types (`GateDecision`, `PIIGateResult`) lived in
worm-core's general `types.py`. Two narrow Protocols (`_PIIGateProto`,
`_InterjectionGateProto`) lived as private structural typings inside
chat-presence's `chat_flows/_shared.py`, with a module docstring explicitly
naming "post-Wave-D governance consolidation" as the cleanup target.

The system needed a single canonical home for governance types, gates, and
the Protocol surface that downstream worms consume — without forcing every
gate to inherit a common base class that would constrain their
heterogeneous `check()` signatures.

## Decision

The `packages/governance` package becomes the canonical home for every gate,
every governance result type, and every Protocol that documents a gate's
shape. The consolidation lands in five focused moves:

1. **Lift `RulesBasedRelevanceGate` to
   `packages/governance/src/wormbase_governance/relevance.py`.** Both old
   homes (worm-core and chat-presence) become re-export shims that preserve
   the public name. Chat-presence consumes the relevance gate via dependency
   injection, mirroring the existing PII / interjection consumption
   pattern.
2. **Move `GateDecision` and `PIIGateResult` to
   `packages/governance/src/wormbase_governance/types.py`.** Both stay
   re-exported from `wormbase_core.types` for backward compatibility.
3. **Promote `_PIIGateProto` and `_InterjectionGateProto` to public
   `PIIGateProtocol` and `InterjectionGateProtocol`** in the governance
   types module. The underscore-private aliases stay as backward-compat
   imports so chat-flows files do not need an import sweep.
4. **Introduce `PolicyGate` as a typing-only Protocol.** It documents the
   minimum structural shape every concrete gate satisfies (an async
   `check`), without forcing a common ABC. Concrete gates may have
   heterogeneous signatures; `runtime_checkable` enables `isinstance(gate,
   PolicyGate)` for conformance tests.
5. **Replace the `__slots__` `PIIGateResult` inside `gates.py` with an
   import of the Pydantic model from the governance types module.**

`RulesBasedRelevanceGate.handle()` continues to record via
`emit_memory_written` with tags `["relevance_decision", ...]` rather than
`emit_gate_fired` — relevance decisions are observation-grade, not
governance-grade. The distinction is intentional and preserved verbatim.

What this decision explicitly does **not** do:

- It does not promote relevance decisions to `gate_fired` entries (that
  would break the dashboard's gate-vs-memory split; it is a separate
  decision deferred to a future wave).
- It does not introduce a new runtime gate registry. `gate_impl` dotted-path
  resolution via `policy_templates.yaml` continues unchanged.
- It does not extend gate logic into `write_actions.py` or
  `data_product_actions.py` — those modules carry zero inline gate calls;
  the original scoping that implied otherwise was incorrect.

## Consequences

**Positive:**

- One canonical home for every governance gate. The duplicate
  `relevance.py` problem is eliminated by lift-and-shim rather than by
  pick-a-winner.
- `PolicyGate` documents the gate contract without imposing inheritance.
  Concrete gates remain free to accept heterogeneous arguments while still
  passing `isinstance(gate, PolicyGate)` conformance checks.
- Backward-compat re-exports mean external test callers and chat-flows
  imports don't need a sweep; the consolidation is doctrine-improving
  without a coordinated cross-package refactor.
- The `policy_templates.yaml` indirection layer stays as the canonical
  configuration surface. New policies don't require new code; they require
  a new YAML stanza pointing at a `gate_impl` dotted path.

**Negative:**

- The governance package gains a transitive dependency on
  `wormbase_core.reactivity` via the relocated relevance module. This
  dependency direction (governance → worm-core) already existed
  implicitly; consolidation makes it explicit. Reactivity primitive
  co-relocation is a future hub-redefinition concern.
- The `__slots__` and Pydantic `PIIGateResult` representations existed in
  parallel before consolidation. Replacing the `__slots__` form with the
  Pydantic import is correct but means a subtle shape unification at the
  internal `_record_gate_fired` boundary.

**Neutral:**

- Net new entry kinds: zero. The doctrine's freeze-pause threshold is not
  affected by this decision.
- Direct-import sweep of `wormbase_core.relevance` consumers is deferred to
  a follow-up hub-redefinition wave. The shims keep the old paths working
  indefinitely.

## Cross-references

- Related ADRs: ADR-0004 (chat-presence consumes relevance via DI rather
  than owning a duplicate); ADR-0006 (the hub-redefinition wave that removes
  the relevance shim from worm-core direct callers).
- Related specs: schema-evolution doctrine at
  `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`.
- Architecture: `ARCHITECTURE.md` §2 lists `governance/` as a peer package
  to the named-actor worms.
