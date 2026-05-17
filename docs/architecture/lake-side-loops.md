# Lake-side loops

WormBase tends the continuous lake through eight named loops, L1 through
L8. Each loop is a continuous tending behavior — an always-on inference
the agent runs over the lake's state, producing proposals that admins
confirm or reject. None of these loops is a pipeline stage. Each is one
axis along which the lake is being kept honest, from t=0 of install.

The deep specs for every loop live in `docs/superpowers/specs/`. This
file is the public-friendly introduction; the deep specs are the
authoritative references for the ledger kinds, projections, strategies,
and Reader Protocols each loop owns.

## What a lake-side loop is

A lake-side loop is a continuous tending behavior over the lake. It
listens for a trigger (a new catalog snapshot, a freshly-connected
surface, a confirmed semantic type from a peer loop), runs one or more
strategies that produce candidate inferences, writes those candidates to
the ledger as `*_proposed` entries, and surfaces them on a `/lake/*`
dashboard page for admin disposition. Confirmed candidates become
durable lake state; rejected candidates are recorded too, so the
inference history is fully audit-replayable.

Every loop shares the same shape: trigger → strategies → proposals →
admin disposition → confirmed state. The shape is the
`LakeLoopComposite[T]` pattern (see *How loops compose* below). The
loops differ only in what `T` is and which strategies tend it. None of
them processes data in the pipeline sense — they tend the lake by
continuously proposing, deduping, and refining inferences that already
hold over the lake's existing state.

## L1 — source-candidate triage

L1 continuously triages candidate sources that the agent has noticed
but not yet adopted. Sources are noticed five ways: a file gets dropped
in a channel, a credential gets pasted in a DM, a data reference comes
up in conversation, an admin fills out an "Add source" form, or the
worm itself detects a KPI-tree gap that needs a new data source to
close. L1 watches all five trigger flows and produces a single,
deduplicated triage queue.

The point of L1 is to keep the lake's source list governed without
forcing humans to bookkeep every candidate. Strategies score each
candidate (KPI-gap demand, conversational mentions, file-drop intent)
and attach reasoning. Admins promote, reject, or ignore. Only promoted
candidates enter the existing `source_proposed → source_confirmed →
source_connected → source_profiled` lifecycle. The triage prequel is
separate from the connection pipeline so audit clarity is preserved at
each stage.

- **Trigger:** any of the five source-acquisition trigger flows emits a
  candidate signal (file drop, credential paste, conversational
  mention, dashboard form, KPI gap).
- **Deep spec:** `docs/superpowers/specs/2026-06-08-lake-side-compounding-l1-design.md`
- **Dashboard:** `/lake/source-candidates`

## L2 — catalog-drift detection

L2 continuously watches every connected surface's catalog and detects
when it has drifted from a previous baseline. Five drift cases are in
scope: a table appears, a table disappears, a column appears in an
existing table, a column disappears, or a column's type changes. The
underlying signal — `external_catalog_imported` snapshots — already
flows through the lake; L2 is the inference layer that gives each
detected drift an audit-bearing identity.

The point of L2 is to turn raw structural changes into admin-
acknowledgeable events. Drifts can be expected (a planned migration) or
unexpected (an upstream team shipped a schema change without telling
anyone); L2 doesn't presume which, it just surfaces every drift with
strategy, confidence, and reasoning so an admin can acknowledge or
reject it. L4 (schema-impact) acts on the consequences; L2 owns the
disposition record itself.

- **Trigger:** a new `external_catalog_imported` snapshot lands for any
  connected surface and differs from the previous snapshot.
- **Deep spec:** `docs/superpowers/specs/2026-06-09-lake-side-compounding-l2-design.md`
- **Dashboard:** `/lake/catalog-drift`

## L3 — lineage discovery

L3 continuously infers semantic relationships at the table and column
level — the cross-table dependencies and naming-or-overlap signals that
let the lake reason about lineage without a hand-curated map. Three
strategies feed it: column-name naming heuristics (substring + edit
distance), sample-value overlap (Jaccard similarity across sampled
rows), and explicit references parsed from any available dbt manifest.

The point of L3 is to keep a confidence-weighted lineage graph
continuously tended even when the customer has never written a single
explicit `ref()`. Every confirmed L3 edge becomes a first-class piece
of lake state that downstream loops (notably L4 schema-impact) read.
L3 is the first lake-side axis to validate that loops can compound on
each other's outputs: every L3 edge is consumed by L4 the moment it is
confirmed.

- **Trigger:** a surface emits a fresh catalog snapshot
  (`external_catalog_imported`) or finishes connecting
  (`source_connected`).
- **Deep spec:** `docs/superpowers/specs/2026-05-28-lake-side-compounding-l3-design.md`
- **Dashboard:** `/lake/lineage`

## L4 — schema-impact analysis

L4 continuously computes the downstream impact of any column change in
any connected surface. When a column's type changes, when a column
disappears, or when a column shows up in a new place, L4 reads L3's
confirmed lineage edges to determine which downstream tables and
columns are affected, and proposes impact entries for admin review. It
is the first lake-side loop that explicitly consumes a peer loop's
confirmed-state output.

The point of L4 is to make schema change a governed, traced event
rather than a quiet break that surfaces hours later as a failing
dashboard. Strategies attach reasoning — which lineage edge mattered,
which dbt test would fire, which type coercion is involved — so the
admin doesn't have to derive the consequences. L4 is also where
governance elevation lives: a drift on a `regulated`-classified column
gets visibly higher severity than the same drift on a `public` column.

- **Trigger:** a column-level catalog change is observed in an
  `external_catalog_imported` snapshot for a surface that already has
  confirmed L3 lineage edges, confirmed L5 semantic types, or
  confirmed L6 classifications attached.
- **Deep spec:** `docs/superpowers/specs/2026-06-02-lake-side-compounding-l4-design.md`
- **Dashboard:** `/lake/schema-impact`

## L5 — column fingerprinting

L5 continuously fingerprints every column in every connected surface
and proposes a semantic type for it: `email`, `iso_date`, `pii_ssn`,
`phone_e164`, and so on. Three strategies do the work: column-name
regexes (productive on Day 1), value-pattern matching against sampled
rows (productive when the sampler is wired), and distribution
fingerprinting against column statistics. Even when a column's name is
uninformative (`col_17`, `attr_x`), L5 can often still propose a useful
semantic type from values and shape.

The point of L5 is to give the rest of the lake — quality checks,
governance classification, entity stitching — a stable column-level
vocabulary that downstream loops can chain off. Confirmed L5 types
become first-class state. Two cross-axis chains depend on them: L5→L7
auto-proposes quality checks tied to the semantic type (a confirmed
`email` immediately attracts `not_null` and `unique`); L5→L4 elevates
impact severity for changes to columns that carry sensitive semantic
types.

- **Trigger:** a fresh `external_catalog_imported` snapshot lands for
  any surface; gather enumerates that surface's columns.
- **Deep spec:** `docs/superpowers/specs/2026-06-05-lake-side-compounding-l5-design.md`
- **Dashboard:** `/lake/semantic-types`

## L6 — column-classification

L6 continuously proposes column-level governance classifications:
`public`, `internal`, `confidential`, `pii`, `regulated`. It reads
L5's confirmed semantic types as its strongest signal — a confirmed
`pii_ssn` semantic type proposes a `regulated` classification with
high confidence — and also weights domain-pack defaults, column-name
heuristics, and any policy baselines attached to the resource's
domain.

The point of L6 is to keep governance classification continuously
tended at column granularity rather than left as a coarse per-domain
default. Where the onboarding wave's domain-pack picker assigns
classification per domain, L6 refines per column with confidence,
strategy, and reasoning. Admin confirms become audit-grade evidence
that a column was reviewed; admin rejects record the reasoning. L6
closes the L5→L6 chain that the PII chip on `/lake/semantic-types`
foreshadows.

- **Trigger:** a confirmed L5 semantic type lands, or a fresh
  `external_catalog_imported` snapshot lands for a surface.
- **Deep spec:** `docs/superpowers/specs/2026-06-06-lake-side-compounding-l6-design.md`
- **Dashboard:** `/lake/column-classification`

## L7 — quality checks

L7 continuously proposes candidate quality checks against every newly-
arrived table and column: null guards, uniqueness constraints,
freshness windows, row-count bounds, type-stability, enum-membership.
Three strategies feed proposals: schema-pattern heuristics (productive
from Wave 1 catalog metadata), dbt-test extraction (productive from
the dbt manifest), and historical-statistics inference (productive
once the sampler is wired).

The point of L7 is to keep the lake's quality baseline growing
automatically rather than leaving it to humans-with-spreadsheets.
Confirmed checks become the audit-visible quality baseline; rejected
ones record the reasoning so the same proposal doesn't keep re-firing.
The cross-axis L5→L7 chain extends this: as L5 confirms semantic
types, L7 auto-proposes the conventional checks for that type
(`email` → `not_null` + `unique`; `iso_date` → freshness; `pii_ssn` →
masking-presence verification).

- **Trigger:** `source_connected` or `external_catalog_imported` lands
  for a surface, or a confirmed L5 semantic type fires the SemanticType
  chain.
- **Deep spec:** `docs/superpowers/specs/2026-05-30-lake-side-compounding-l7-design.md`
- **Dashboard:** `/lake/quality`

## L8 — entity-stitching

L8 continuously proposes that columns in different connected surfaces
refer to the same business entity — `crm.contacts.email` and
`app.users.email_address` both identify the same Person, or
`finance.invoices.customer_id` and `ops.tickets.account_id` both
identify the same Organization. Three strategies do the work:
name-match with L5 semantic-type anchoring, sample-value overlap, and
schema-shape similarity (column-count and type-pattern matching).

The point of L8 is to keep cross-surface entity identity continuously
tended even when the customer has never declared a single explicit
join. The lake compounds: every new surface increases the entity
graph's coverage; every confirmed stitch becomes durable state that
downstream query work (and future federated-query work) can use.
L8 is the third lake-side loop to consume L5's confirmed semantic
types as a cross-axis input.

- **Trigger:** an `external_catalog_imported` snapshot lands for any
  surface; gather enumerates candidate column-pairs across surfaces
  filtered by source-id distinct.
- **Deep spec:** `docs/superpowers/specs/2026-06-07-lake-side-compounding-l8-design.md`
- **Dashboard:** `/lake/entity-stitches`

## Cross-axis chains

Lake-side loops are designed to compound on each other. A chain is the
relationship where one loop's confirmed-state output is read by another
loop as input. Four chains are in production today:

- **L5 → L7 (SemanticTypeQualityCheckStrategy)** — L7 reads confirmed L5
  semantic types; when an `email` lands, L7 auto-proposes `not_null` and
  `unique` checks for the column. The combined inference produces
  type-appropriate quality guards without admin authoring. Visible at
  `/lake/quality` with provenance back to the originating L5 confirm.
- **L6 → L4 (governance-classification impact elevation)** — L4 reads
  confirmed L6 classifications; when a `regulated` column drifts, L4
  raises the impact entry's severity. The combined inference produces
  governance-aware impact analysis. Visible at `/lake/schema-impact`
  with a "regulated" badge on the elevated row.
- **L5 → L4 (SemanticTypeImpactStrategy)** — L4 reads confirmed L5
  semantic types; when a `pii_ssn`-typed column changes type, L4
  elevates the impact entry's severity even before L6 has classified
  it. The combined inference produces type-aware impact pre-staging.
  Visible at `/lake/schema-impact` with the L5 type chip on the row.
- **L4 ↦ L2 (bidirectional acknowledged-drift ↔ impact)** — L4 reads
  L2's `catalog_drift_acknowledged` entries to suppress impact noise
  for admin-acknowledged drifts; L2 reads L4's impact severity to
  prioritize unresolved drifts higher in the triage queue. The
  combined inference produces a drift-impact loop that compounds
  acknowledgement and remediation evidence. Visible across
  `/lake/catalog-drift` and `/lake/schema-impact` with cross-links.

## How loops compose

Every lake-side loop is implemented as a `LakeLoopComposite[T]`. The
composite is a generic that owns three things: a set of strategies
that produce candidate `T`s, a set of Reader Protocols that the
strategies pull state from, and the dedup-and-promote rule that turns
candidates into ledger entries. Strategies are pluggable; they don't
know about each other; multiple strategies can produce the same
canonical tuple and the composite dedups them on a deterministic hash
of the candidate's identity fields. This is what lets the composite
ship in fewer than 14 lines of orchestration code.

Cross-axis chains are realized as additional strategies plugged into
existing composites. The L5→L7 chain, for example, is a
`SemanticTypeQualityCheckStrategy` registered with L7's composite that
reads L5's confirmed projection through a `ConfirmedSemanticTypeReader`
Protocol. L7's composite doesn't know L5 exists; it just calls the
strategies it owns. Adding a new chain is therefore additive — it does
not modify the upstream loop, the downstream loop, or any other
strategy already in the composite. Chains compose; they do not couple.

Readers are the seam between loops. A Reader Protocol is a narrow
read-only interface that a strategy depends on; concrete readers are
provided by the composite's wiring, usually backed by a projection
table in Postgres. When a downstream loop wants to consume an upstream
loop's output, it depends on the Reader Protocol rather than on the
upstream composite directly. This keeps the dependency graph between
loops thin and testable: every cross-axis chain has a single, named
Reader at its seam, and that Reader can be faked in tests for either
side independently.

The result is a substrate where new loops are cheap to add (a new
`LakeLoopComposite[T]` plus three strategies plus a `/lake/*` page)
and new cross-axis chains are even cheaper (a single new strategy on
an existing composite that depends on a new Reader Protocol). The
8 loops shipped here are the first wave; the architecture is built to
keep growing without restructuring what is already tending the lake.

## Cross-references

- `docs/architecture/continuous-lake.md` — Umbrella narrative.
  Positions WormBase as the agent-installable continuous lake; surfaces
  the eight tending behaviors as the lake's continuous-tending
  machinery alongside lake-maintainer and catalog-mirror.
- `docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md`
  — Architectural commitment. The lake exists because the agent is
  tending it; the loops are how the agent tends it.
- `docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md` —
  Source Protocol split. Every loop's strategies pull from surfaces
  via the AcquirableSource / MaintainableSource Protocols defined
  there.
- The eight deep specs in `docs/superpowers/specs/` (linked per L#
  section above) — Authoritative references for the ledger kinds,
  projections, strategies, Reader Protocols, and Optional-Effect
  Injection cases each loop owns.
