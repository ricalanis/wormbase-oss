# wormbase-governance

Five governance entities (Person, Domain, Resource, Classification, Policy) implemented as ledger-derived projections, plus the gate implementations (`pii_redaction`, `warmup_required`, `interjection_budget`, `knowledge_threshold`). Every gate reads tenant-scoped state via `wormbase-ledger` and either permits or denies an action, emitting a `gate_fired` entry on denial. Python-only; depended on by `worm-core` (gates run in the reactivity triad) and read by `apps/dashboard` (governance lenses).
