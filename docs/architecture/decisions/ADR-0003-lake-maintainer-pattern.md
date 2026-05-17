# ADR-0003: Lake-Maintainer package pattern for pluggable data-source watchers

**Status:** Accepted
**Date:** 2026-05-02

## Context

WormBase's lake spans four source families: `external` (database / SaaS API
connectors), `filedrop` (one-off files dropped into channels), `conversation`
(the message stream itself), and `evidence` (autoresearch-published
notebooks and data products). Each family carries the same operational
questions over time: has the source drifted? has its classification changed?
is it stale? is its lineage to downstream consumers healthy?

Before this decision, those questions were answered by scattered heuristics:
`topic_extractor` noticed conversation drift, `data_product_actions`
detected replay mismatches in evidence, source-side drift was an aspirational
counter on `projection_sources`. No coherent home existed for the
"maintenance" face of a source — only the "acquisition" face captured by the
existing `Connector` Protocol.

A single fat `Source` Protocol that combined both acquisition (`discover`,
`profile`, `sample`, `watch`) and maintenance (`detect_drift`,
`refresh_classification`, `staleness_signal`, `lineage_health`) was the
obvious shape, but it forced every family to lie about what it does.
`watch()` is no-op for every existing connector; `discover()` is a SQL
`SELECT` for evidence; `profile()` collapses to message counting for
conversation.

## Decision

WormBase splits the abstraction into **two composable Protocols**:

```python
class AcquirableSource(Protocol):
    """For external + filedrop families only."""
    id: SourceId
    family: Literal["external", "filedrop"]
    classification: Classification
    domain: DomainId
    owner: PersonId | None

    async def discover(self) -> list[ResourceProposal]: ...
    async def profile(self, resource_id) -> Profile: ...
    async def sample(self, resource_id, n) -> bytes: ...

class MaintainableSource(Protocol):
    """All four families implement this."""
    id: SourceId
    family: SourceFamily   # external | filedrop | conversation | evidence

    async def detect_drift(self) -> DriftReport: ...
    async def refresh_classification(self) -> ClassificationUpdate: ...
    async def staleness_signal(self) -> StalenessReport: ...
    async def lineage_health(self) -> LineageReport: ...
```

`ExternalSource` and `FiledropSource` implement both Protocols.
`ConversationSource` and `EvidenceSource` implement only
`MaintainableSource`. The dispatch loop iterates `MaintainableSource` — the
shared shape across all four families.

Critically, **lake-maintainer is not a sixth Reactivity loop**. The existing
W5a `ReactivityRegistry` and `ReactivityRunner` are the substrate. Each
maintenance method becomes a Reactivity instance registered with the
existing registry on source-connect. Lake-maintainer reduces to (a) a Source
registry, (b) a factory that produces maintenance Reactivities per Source,
(c) per-source lifecycle wiring via `wire_maintenance_for_source` invoked
from `source_builder.py`.

`watch()` is dropped from the v1 Protocol surface. It was no-op-or-collapse
for every family today, and CDC-style watching (if ever needed) becomes a
separate optional capability flag and a `StreamableSource` mixin.

A thin `LakeStore` Protocol (~50 LOC) wraps `MedallionCascade._write_bronze`
/ `_silver` / `_gold` plus SQLAlchemy reads against `projection_*`. The
substrate is portable: no Postgres-specific reach-through, no raw SQL,
SQLAlchemy generic types throughout.

## Consequences

**Positive:**

- ~70-75% of the v1 lake-maintainer surface is a rename-and-lift of existing
  code; only ~25% is genuinely new (staleness `last_seen` migration,
  per-family freshness rules, lineage-health aggregations, the Source
  registry, and the per-family Reactivity factory).
- Composition with the W5a substrate is the default, not the exception.
  No new orchestrator loop, no parallel dispatch surface, no duplication of
  W5b's phenomenon-gap detectors.
- The Protocol split keeps each family honest. `ConversationSource` does
  not pretend to `discover()` channels in tabular shape; it does what a
  lurker actually does: read the ledger.
- `LakeStore` is substrate-portable. A future swap to DuckDB or Iceberg is
  a port of the persist functions, not a rewrite of the cascade.

**Negative:**

- Two Protocols where one was originally proposed. Engineers must remember
  that only acquisition families implement `AcquirableSource`; new
  conversation-shaped sources implement only `MaintainableSource`.
- `staleness_signal` requires a `last_seen TIMESTAMPTZ` column on
  `projection_sources` that did not previously exist. This is a
  forward-only additive migration but it must ship with the wave.
- The `projection_conversations` table that the `ConversationSource`'s
  `MaintainableSource` impl reads from did not exist at decision time. The
  lake-maintainer wave includes the migration that creates it.

**Neutral:**

- `ConversationSource` does **not** replace the lurker pattern.
  `channel_adapter` continues to write `chat_received` entries; the
  conversation poller continues to fold them. Lake-maintainer composes with
  the lurker; it does not consume it.
- `Connector` (driver class, `kind="postgres"`) and `Source` (per-instance,
  `id`, `domain`, `owner`) are distinct abstractions that compose: a Source
  instance wraps a Connector driver plus per-instance metadata. The
  distinction is intentional — conflating them would re-invent one or the
  other.

## Update 2026-05-17 — Protocols rehomed

Per ADR-0013 (continuous-lake philosophy), `AcquirableSource` and
`MaintainableSource` Protocols moved from `lake-maintainer/` to
`lake-surfaces/`. Behaviorally unchanged; only import paths updated.
`lake-maintainer/` now imports the Protocols from `lake-surfaces/` and
retains the Reactivity-driven dispatch machinery
(`wire_maintenance_for_source`, per-family factory). The split rationale
in this ADR (capability faces; family-honesty) stands; the home moved
to reflect that surfaces own their capability declarations.

`ConversationSource` and `EvidenceSource` impls also moved to
`lake-surfaces/` (they implement Surface Protocols; the maintainer
consumes them).

## Cross-references

- Related ADRs: ADR-0006 (worm-core hub redefinition pins lake-maintainer's
  per-source wiring as not-at-boot, not-per-install); ADR-0009 (research
  worm's maintenance-shaped reactivities follow the same template);
  ADR-0013 (continuous-lake philosophy — surfaces own their capability
  declarations, motivating the Protocol rehoming noted above).
- Related specs: schema-evolution doctrine at
  `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`.
- Architecture: `ARCHITECTURE.md` §2 ("The worm decomposition") lists
  lake-maintainer in the package layout.
