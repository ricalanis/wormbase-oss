# ADR-0010: Deferral criteria for portfolio-adjacent cleanups

**Status:** Accepted
**Date:** 2026-05-04

## Context

After the worm-decomposition portfolio shipped (lake-maintainer through
governance consolidation), a backlog of eight portfolio-adjacent items
remained — a mix of latent bugs, structural cleanups, and one gated
feature wave (identity greenfield Reactivities). Each item was discovered
during the portfolio waves but deemed out-of-scope for its host wave
either because it crossed a package boundary that the host wave was not
authorized to touch, or because it depended on a doctrine review that
had not yet completed.

The system needed a single combined wave that could land all eight items
with correct sequencing and explicit deferral criteria — distinguishing
items that were genuinely tractable from items that needed doctrine work
first.

## Decision

The eight items consolidate into **one combined wave with three
sub-waves** dictated by hard and soft dependencies:

### Sub-wave 1 — independent prerequisites (parallel-safe)

- Pytest cross-package collection collision fix (workspace-root
  `pyproject.toml` pins `testpaths = ["tests"]`; cross-package is
  unsupported by design; `make test-all` loops per-package).
- `@runtime_checkable` audit (already-resolved; reduces to a one-line
  comment at the decorator sites).
- Helper-duplication register (intentional duplications across worm-core
  ↔ chat-presence documented with a drift detector test, not
  consolidated).

### Sub-wave 2 — bug fixes and sweep refactors (sequential)

- `InMemoryLedger.replay()` state-dict drift fix. The in-memory replay's
  seed state was a strict subset of `build_projections`'s seed; the fix
  extracts a shared `_initial_projection_state()` helper.
- Formalize `Install` dataclass on the chat-presence side. Twelve
  `SimpleNamespace` duck-typing sites — including a production wire — get
  swept to a typed `Install` shape.
- Extras-injection bridge unification. Picks **Option A (factory kwargs)**
  over **Option B (registry extras_factory)**: chat-worm Reactivities
  accept services via constructor injection rather than reading them from
  the W5a `extras` carrier. Purely chat-worm-internal; no change to the
  W5a stable contract.
- Cascade-on-file-drop restoration. The chat dispatcher gains a
  `cascade: callable | None = None` kwarg; cli.py constructs the cascade
  from the existing lake-maintainer infrastructure at the wire site. Lake
  + chat compose at the wire layer; packages stay decoupled.
- YAML setup conversations move into the chat-presence package's
  package-data directory (`importlib.resources` instead of a five-level
  parent-path traversal).

### Sub-wave 3 — gated feature work (sequential after sub-wave 2)

- **Freeze-pause review** (doctrine output, no code): audit consolidation
  candidates across seven named entry-kind families, mark
  `heuristic_experiment` as deprecated, decide on the lake-maintainer
  "kind-within-kind" asymmetry, raise the freeze-pause threshold numeral
  to 100, update the doctrine prose. Doctrine Addendum 1 mandates this
  review **before** any wave that adds new kinds.
- **Wave B.5 identity greenfield** (gated on the freeze-pause review):
  ships `PositionInferenceReactivity` and `ResourceOwnershipReactivity`
  with two new entry kinds (`emit_position_proposed`,
  `emit_resource_role_proposed`) plus a `projection_roles` migration
  variant. Both Reactivities are deliberately deferred from the
  identity-tracker package's v1 (see ADR-0007).

### Total wave envelope

~5 hrs of agent execution + ~1 hr of human review checkpoints. Three
sub-waves with review checkpoints between them.

## Consequences

**Positive:**

- One audit-and-execute pass covers eight items that would otherwise need
  eight separate dispatches. Per-item context cost amortizes across the
  wave.
- Hard dependencies are pinned: Wave B.5 cannot dispatch until the
  freeze-pause review lands, because Doctrine Addendum 1 mandates it.
- The pytest cross-package collision is addressed at the contract layer
  (workspace-root `testpaths` plus `make test-all`), not by attempting to
  unify 16+ sibling conftests under one rootdir.
- The Option A extras-injection choice keeps the W5a Protocol contract
  stable. Chat-worm's internal refactor changes only chat-worm.

**Negative:**

- The freeze-pause review is doctrine output, not code. It looks like
  procedural overhead but is load-bearing: without it, future waves that
  add entry kinds would compound the cardinality concern without a
  formal review.
- The cascade-on-file-drop fix is structurally simple but the verification
  ordering matters: the failing test must land before the fix to confirm
  the regression is real (the smoke test pre-decision only verified the
  helper was still importable, not that the cascade actually fired from
  the chat path).
- Helper duplication across worm-core ↔ chat-presence is preserved
  rather than consolidated. The asymmetry stays documented (with a drift
  detector test); a future shared-utility package can pick it up if a
  third consumer appears.

**Neutral:**

- Net entry-kind delta: +2 (only from Wave B.5).
- Net new packages: 0.
- Net file count delta: ~+8 (the Install dataclass, the freeze-pause
  review doc, the duplications register, the two B.5 Reactivities, the
  B.5 projection migration).

## Cross-references

- Related ADRs: ADR-0007 (the identity-tracker package whose v1 deferred
  the two greenfield Reactivities); ADR-0006 (the hub redefinition that
  surfaced the install-duck-typing sites); ADR-0004 (the chat-presence
  package whose extras-injection seam this wave unifies).
- Related specs: schema-evolution doctrine at
  `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`.
