# ADR-0007: IdentityResolver Protocol and identity-tracker package

**Status:** Accepted
**Date:** 2026-05-03

## Context

Identity in WormBase is the most cross-cutting concept after the ledger
itself: `Person` (a real human or service account), `PersonIdentity` (the
multi-platform fan-out — `@bob` on Slack, `bob#1234` on Discord), and
`Install` (one OAuth grant per `(tenant, platform)`). Three downstream
worms (chat, process, research) and two existing Reactivities
(`StatementToOwnerReactivity`, `team_loop_runner`) need to read identity
state without each re-folding the ledger.

Before this decision, identity logic was scattered across worm-core:
`identity_discovery.py` (the auto-discovery loop, already shipped as a W5a
Reactivity), `owner_lookup.py` (an async function), `team_lookup.py` (three
async functions), `positions.py` (a static registry of canonical positions),
and `resource_aggregator.py` (which aggregates KPIs / sources / decisions
by domain). The identity write surface — `propose_person`, `confirm_person`,
`merge_persons`, `split_person`, `link_identity`, `unlink_identity` — lived
in `write_actions.py`, called by HTTP routes and the onboarding orchestrator.

The system needed a single Protocol surface that downstream worms could
consume via dependency injection from the hub, without each re-implementing
the ledger folds that resolve `(platform, platform_user_id)` to a `Person`.

## Decision

WormBase ships **`packages/wormbase-identity-tracker`** with a frozen
`IdentityResolver` Protocol as its public surface:

```python
@runtime_checkable
class IdentityResolver(Protocol):
    async def resolve_platform_id(
        self, *, platform: str, platform_user_id: str,
    ) -> Person | None: ...

    async def propose_person(
        self, hint: PersonHint, *, proposed_by: str,
    ) -> ProposalRef: ...

    async def lookup_owner(self, topic: Topic) -> Person | None: ...

    async def lookup_team(self, person_id: UUID) -> list[TeamMembership]: ...
```

Value types (`Person`, `PersonHint`, `ProposalRef`, `TeamMembership`) are
frozen dataclasses; `ProposalRef` carries both `person_id` and the
`entry_ids` tuple so the trace surface and any wire-replay determinism
check can attribute the fan-out.

The implementation is **ledger-backed**, not projection-table-backed:
`_LedgerBackedIdentityResolver` fetches via `ledger.fetch(company_id)` and
folds rows. This keeps test/production path symmetry — `InMemoryLedger`
satisfies the resolver contract identically to the Postgres `Ledger`. SQL
projection-table reads are a future optimization once a production tenant
accumulates many identity-related rows.

The package lifts four read-side modules verbatim:

- `IdentityDiscoveryReactivity` (renamed `UnknownPlatformIdReactivity`) —
  the production-grade W5a Reactivity that fires on unknown
  `platform_user_id` events.
- `owner_lookup.lookup_owner` and the `Person` dataclass.
- `team_lookup.{team_for_person, members_of_team, all_teams}`.
- `positions.py` — a static registry of canonical positions (CFO, CMO,
  data_engineer, ...), data-only.

`wire_identity_for_install(install, member_lookup, registry, ledger,
company_id)` registers `UnknownPlatformIdReactivity` and returns an
`IdentityResolver` impl that the hub then injects into chat / process /
research worms.

Scope tightenings versus the original ambition:

- `resource_aggregator.py` does **not** lift to identity-tracker. It is a
  domain-aggregation utility (KPIs / sources / decisions / processes / data
  products), not identity logic. Co-locating it with identity is a category
  error; it belongs as a hub utility (DI'd into chat-presence's
  `StatementToOwnerReactivity`) or in its own future package.
- `merge_persons` / `split_person` stay in `write_actions.py` and the
  HTTP layer. They are admin-only operations that orchestrate sequences of
  link/unlink/archive PEVR cycles, not Reactivities consumed by downstream
  worms.
- Two greenfield Reactivities (`PositionInferenceReactivity`,
  `ResourceOwnershipReactivity`) that would require new entry kinds
  (`emit_position_proposed`, `emit_resource_role_proposed`) are deferred to
  a follow-up wave. They have no precedent code to lift; designing them
  with the entry-kind permanence rule in mind warrants its own decision.

The Protocol shape is **frozen at the package landing**. After Wave B,
three downstream worms and two existing Reactivities consume this surface
via DI from the hub. Any signature change requires coordinated refactoring
across those consumers.

## Consequences

**Positive:**

- One Protocol, one DI surface, one canonical home for identity reads.
  Downstream worms call `identity.lookup_owner(topic)` instead of
  hand-rolling the ledger fold each time.
- `_LedgerBackedIdentityResolver` works against both `InMemoryLedger` and
  the Postgres `Ledger` — test/production parity is preserved without
  projection-specific code paths.
- ~75% of the v1 surface lifts directly; ~25% is genuinely new (the
  Protocol, value types, the `wire_identity_for_install` factory, the
  `resolve_platform_id` ledger fold).
- The Protocol's frozen contract gives downstream worms a stable
  consumption surface and forces any future signature change to be a
  coordinated, deliberate move.

**Negative:**

- The `resolve_platform_id` fold is genuinely new code (not lifted).
  Today's `_rehydrate_known_set` returns a set of `(platform,
  platform_user_id)` tuples; resolving back to a `person_id` requires a
  separate fold of `emit_person_proposed` + `emit_identity_linked` entries.
- Position auto-proposal from chatter signal — the "the worm proposes
  positions" promise — is aspirational. Shipping it requires designing the
  entry-kind shape, the dedup rule, the admin-confirmation flow, and the
  scoring heuristic. Deferred to a follow-up wave.
- Resource-ownership auto-proposal requires a new
  `emit_resource_role_proposed` entry kind plus a `projection_roles`
  migration variant and an HTTP confirm route. Same deferral rationale.

**Neutral:**

- `IdentityDiscoveryLoop` (the pre-Reactivity legacy class) lifts as
  `wormbase_identity_tracker.legacy.IdentityDiscoveryLoop` with a
  `DeprecationWarning`. It exists only for byte-equivalence regression
  testing and can be dropped in v2.
- Two `lookup_team` variants exist: the package-private
  `team_for_person → set[UUID]` (for autoresearch_loop's
  team_loop_runner that only needs the IDs) and the Protocol-exposed
  `lookup_team → list[TeamMembership]` (carries `role` and `granted_at`).
  Both are correct; the asymmetry serves both consumers without forcing
  re-folds.

## Cross-references

- Related ADRs: ADR-0006 (the hub's four-wire boot includes
  `wire_identity_for_install`); ADR-0004 (chat-presence's
  `ConversationContext` is populated via `identity.resolve_platform_id`);
  ADR-0008 and ADR-0009 (process and research worms consume the resolver
  via DI).
- Architecture: `ARCHITECTURE.md` §5 ("Identity model") describes the three
  durable concepts; the resolver is how downstream worms read them.
