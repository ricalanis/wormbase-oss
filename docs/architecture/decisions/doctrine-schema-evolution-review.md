# Schema-Evolution Doctrine Review

This document records a full audit of the entry-kind registry, the
producer/consumer mapping for every kind, the consolidation analysis
that confirms why entries are not merged, and the rationale for raising
the registry ceiling rather than retiring kinds.

It is a companion to the schema-evolution doctrine at
`docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` and
should be re-fired when the registry approaches the new review trigger.

**Methodology:** read-only audit of all 117 kinds + producer/consumer
mapping. Producer = `emit_<kind>` literal OR `<Kind>Payload(`
constructor in non-test production code. Consumer = fold handler in
`projections/builder.py`, sibling worm projections, direct `kind ==
"<k>"` checks, or reactivity triggers.

**Migrations covered:** v001..v023.

---

## TL;DR

- **117 kinds audited; four truly retire-able by Rule 1 standards.**
  Even with all four marked DEPRECATED, the registry stays at 117
  (Rule 1: kinds are forever; deprecation is a marker, not a delete).
  Net headroom does not change via deprecation. Doctrine §3 and §5
  already accept this.

- **No useful consolidation candidates.** A prior addendum already
  surveyed seven kind-families against status-field consolidation and
  rejected every one with rationale grounded in Rule 1's permanence.
  The same analysis holds here: consolidation requires forwarders and
  does not reduce registry count post-fact.

- **Projected near-term load: 117 + ~9 = ~126 within two months.**
  Lake-side compounding loops (L5/L6/L8) each add 3 kinds following
  the L3/L7/L4 template; the Phase 2 lake-maintainer adds 4-6; OSI
  manifest adds ~2. The 120 ceiling will breach at the next lake-side
  loop.

- **Recommendation: raise the ceiling to 150** with per-family cap
  updates. Lake-side compounding loops have proven the +3-kinds-per-
  loop template is the canonical institutional-AI shape (propose /
  confirm / reject for every gated artifact); each loop is a feature,
  not sprawl. 150 buys ~11 more L-axis loops of runway. Per-family
  caps absorb the lake / agent-gateway / compounding growth
  concretely. Pair with formal deprecation of four retire-candidates
  so the registry size pin tracks reality.

- **Action items.** (1) Mark three kinds DEPRECATED (`ingest_profiled`,
  `position_metric_added`, `position_question_pattern`); (2) raise
  per-family caps for `lake / catalog-mirror` (5 → 30) and add a new
  `lake-side-loops` family (cap 30) to encode the L-axis pattern;
  (3) update doctrine §2.5 with 150 ceiling + revised review-trigger
  at 140.

---

## Section 1: Kind-by-kind inventory

### Glossary

- **CORE** — write-primitive envelopes (`propose`, `execute`, `verify`,
  `resolve`). Cannot retire — they are the substrate's central
  commitment.
- **ACTIVE** — at least one production emitter AND at least one
  production consumer (fold handler, direct kind-check, or reactivity
  trigger).
- **CONSOLIDATABLE** — could be merged into another kind via status
  field. Per the prior addendum, consolidation across already-emitted
  kinds is net-additive (requires forwarder); the column flags
  candidates but does NOT recommend consolidation.
- **RETIRABLE** — zero producers in current production code AND
  retirement is consistent with Rule 1 (mark DEPRECATED; payload
  class stays forever).
- **DEMO/LEGACY** — already marked DEPRECATED or historical-only.

### Audit method note

Producer detection used two patterns in parallel: `"<kind>"` string
literal in non-test production code AND `<Kind>Payload(` constructor.
PEVR writes flow via `tool=f"emit_{<Kind>Payload>.kind}"` in
`write_actions.py`; this audit captures both the direct-emit and the
Payload-class-construction paths. Consumer detection used `tool ==
"emit_<kind>"` fold dispatch + `kind == "<kind>"` direct checks across
`projections/`, sibling worm packages, `http_api.py`, and reactivity
trigger lists.

A kind shows "0 producers" in the tables below only when *neither* a
payload class constructor *nor* an `emit_<kind>` literal appears in any
non-test production file.

### CORE (substrate-load-bearing, 4 kinds)

| Kind | Rationale |
|---|---|
| `propose` | Write-primitive envelope. |
| `execute` | Carries `tool` discriminator that dispatches to every other kind's fold. |
| `verify` | Audit anchor for "this signal landed." |
| `resolve` | Carries keep/discard outcome; terminal vs provisional. |

### ACTIVE families (summary)

The 117 active kinds partition into the following families. Each kind
has at least one production emitter and at least one production
consumer (or is consumer-ready with the emit-side planned).

- **chat** (8 kinds): `chat_received`, `chat_sent`, the four
  `chat_reply_*` PEVR cycle entries, plus `mentions_*` and
  `conversation_sync`.
- **identity** (9 kinds): `person_proposed`, `person_confirmed`,
  `person_archived`, `person_registered`, `person_invited`,
  `identity_linked`, `identity_unlinked`, `install_completed`,
  `install_revoked`.
- **roles & positions** (9 kinds): `role_assigned`, `role_revoked`,
  `domain_role_assigned`, `domain_pack_selected`,
  `resource_role_assigned`, `resource_role_proposed`,
  `position_proposed`, `position_confirmed`, `position_rejected`,
  `position_assigned`.
- **source-lifecycle** (7 kinds): `source_proposed`,
  `source_confirmed`, `source_connected`, `source_profiled`,
  `source_bronzed`, `source_silvered`, `source_golded`,
  `ingest_landed`.
- **data-products & notebooks** (8 kinds): `data_product_proposed`,
  `data_product_generated`, `data_product_consumed`,
  `data_product_archived`, `data_product_recommended`,
  `notebook_proposed`, `notebook_run`, `notebook_published`,
  `notebook_archived`.
- **lake-side compounding (L-axis loops)** (10 kinds):
  `lineage_edge_{proposed,confirmed,rejected}`,
  `quality_check_{proposed,confirmed,rejected}`,
  `schema_impact_{proposed,confirmed,rejected}`,
  `external_catalog_drift_detected`.
- **catalog-mirror (external sources)** (4 kinds):
  `external_{catalog,lineage,policy,metric}_imported`.
- **agent-gateway core** (8 kinds): `agent_registered`,
  `agent_grant`, `agent_metadata_updated`, `agent_query`,
  `credential`, `agent_event_delivered`,
  `agent_subscription_{created,revoked}`.
- **compounding-loop (semantic v2.B)** (5 kinds):
  `query_outcome_recorded`, `query_correction_suggested`,
  `query_template_promoted`, `semantic_gap_proposed`,
  `semantic_gap_escalated`, `bad_pattern_proposed`.
- **research / autoresearch** (5 kinds): `experiment_proposed`,
  `experiment_run`, `experiment_resolved`, `experiment_lesson`,
  `phenomenon_gap_detected`.
- **process / decision** (5 kinds): `decision_recorded`,
  `process_map_proposed`, `system_map_node`, `recurring_question`,
  `topic_proposed`.
- **governance** (4 kinds): `gate_fired`, `policy_applied`,
  `concept_proposed`, `concept_confirmed`.
- **knowledge-ramp / memory** (4 kinds): `memory_written`,
  `kpi_proposed`, `kpi_answered`, `metric_observed`.
- **reactivity** (4 kinds): `reactivity_proposed`,
  `reactivity_confirmed`, `reactivity_fired`, `reactivity_disabled`.
- **tenant / setup / MCP / inference** (10 kinds):
  `setup_mode_chosen`, `setup_completed`, `setup_step_advanced`,
  `mcp_call_received`, `inference_served`,
  `inference_cache_refreshed`, `tenant_signup_{initiated,completed}`,
  `tenant_quota_consumed`, `tenant_engine_registered`.
- **resource-conversation** (3 kinds):
  `resource_conversation_{proposed,replied,resolved}`.
- **misc / infra** (3 kinds): `clock_tick`,
  `metrics_keep_rate_published`, `lake_discovered`.

Full per-kind producer/consumer paths are in the source-of-truth
`packages/ledger/src/wormbase_ledger/entries.py` and the fold dispatch
in `packages/ledger/src/wormbase_ledger/projections/builder.py`.

---

## Section 2: Consolidation analysis

This review re-confirms the prior addendum's verdict: **no
consolidations are taken.** The detailed reasoning:

> **Rule 1 ("every kind is forever") makes consolidation net-additive
> on the registry, not net-reductive.**
>
> To consolidate kind X into a new kind Y with a status field, you
> must:
>   1. Add Y to the registry (+1).
>   2. Keep X in the registry forever (Rule 1, +0).
>   3. Write a forwarder X → Y at projection-build time.
>   4. Update every consumer (fold table, direct kind-checks,
>      reactivity triggers).
>
> The registry size goes up, not down. Consolidation is only
> worthwhile when the new kind has structural benefits (cleaner
> projections, simpler reactivities) — not when its goal is to shrink
> the registry.

Survey of consolidation candidates (in principle):

| Family | Concrete kinds | Could merge with | Verdict |
|---|---|---|---|
| `data_product_*` | proposed / generated / consumed / archived / recommended | one `data_product_event` with `phase` | Rejected — Rule 1 makes it net +1 |
| `notebook_*` | proposed / run / published / archived | one `notebook_event` with `phase` | Rejected — same |
| `setup_*` | mode_chosen / completed / step_advanced | already partitioned | Rejected — branching code still needs the discriminator |
| `chat_reply_*` | proposed / executed / verified / resolved | one `chat_reply_event` with `phase` | **Categorically rejected** — these are the canonical PEVR-cycle expression |
| `experiment_*` | proposed / run / resolved + lesson | one `experiment_event` | Rejected — same as chat_reply |
| `reactivity_*` | proposed / confirmed / fired / disabled | one `reactivity_event` | Rejected — PEVR audit-shape for reactivity-emitted writes |
| **lake-side triples** | (lineage / quality / schema_impact) × (proposed / confirmed / rejected) | one `lake_artifact_event` with `axis` + `phase` | **Categorically rejected** — per-axis projections are the design |

The four kinds with zero historical-ledger occurrences (the retire
candidates in §3) **could** be consolidated, but they have no useful
target kind to merge into — they were leftover from feature plans
that never landed. Mark-DEPRECATED is the correct action, not
consolidation.

---

## Section 3: Retire candidates

### `ingest_profiled` — HIGH confidence retire

- **Producer check:** no constructor calls, no `emit_ingest_profiled`
  literals in non-test production code.
- **Consumer check:** no fold dispatch in `builder.py`; no `kind ==
  "ingest_profiled"` direct check; no reactivity trigger; only
  registered as a payload class.
- **Test references:** `packages/ledger/tests/test_entries_payloads.py`
  (round-trip serialization test) +
  `packages/ledger/tests/test_entries_base.py` (registry pin).
- **Risk:** very low. The concept is fully subsumed by
  `source_profiled` (which carries profile data and IS actively
  folded).
- **Implementation:** add `DEPRECATED: ClassVar[bool] = True` to
  `IngestProfiledPayload`; append entry to
  `docs/superpowers/specs/entry-type-registry.md`; add row to
  `DEPRECATED_CASES` in `packages/ledger/tests/test_deprecated_kinds.py`.

### `position_metric_added` — HIGH confidence retire

- **Producer check:** only docstring mention in
  `packages/wormbase-identity-tracker/src/wormbase_identity_tracker/positions.py`.
- **Consumer check:** no fold dispatch; no direct kind-check; no
  reactivity trigger.
- **Risk:** low. The "position carries metrics" concept was a step-5
  ambition that never materialized in production. The positions module
  evolved to track position-as-role-string only.
- **Implementation:** same DEPRECATED-marker pattern as above.

### `position_question_pattern` — HIGH confidence retire

- **Producer check:** same as `position_metric_added` — only docstring
  mention.
- **Consumer check:** no fold; no direct check.
- **Risk:** low. Same fate as `position_metric_added` — step-5 intent,
  never wired.
- **Implementation:** same DEPRECATED-marker pattern.

### `heuristic_experiment` — already retired

Status: DEPRECATED marker is present; entry-type-registry.md row
exists; the prior addendum ratified this. No further action needed.

### Aggregate

- **Three kinds to formally mark DEPRECATED.** Registry size stays at
  117 (Rule 1: classes stay forever). Headroom is unchanged.
- **Why mark DEPRECATED at all if the count doesn't drop?** Because
  the DEPRECATED marker is the source-of-truth signal to future
  contributors that re-emitting these kinds is forbidden. Today the
  absence of a marker + absence of a producer means "intent never
  realized but ambiguous"; the marker makes the intent explicit.

### Cannot recommend retiring

The following also-zero-producer kinds are **consumer-ready, emit-
pending**. They belong in ACTIVE — they are part of the production
code path; only the emit side hasn't fired yet. Rule 1 fully covers
them.

- `install_revoked` — fold + http_api route ready; future revoke-flow
  path.
- `person_registered` — folded by governance, identity-tracker,
  research-loop. Pre-Wave-A legacy; historical entries exist in any
  tenant predating Wave A.
- `position_assigned` — folded; pre-Wave-A confirm-step path; admin-
  override consumer ready.
- `resource_conversation_replied` — fold ready; reply path planned but
  not yet wired.
- `resource_conversation_resolved` — fold ready; resolve path planned
  but not yet wired.
- `tenant_engine_registered` — heavy consumer surface in `tenancy.py`
  + `tenant_engine_validator.py`. Phase 2 engine-per-tenant Shape B
  activation gated behind operator tooling.

---

## Section 4: Ceiling-raise rationale

### Current state

- KIND_REGISTRY: **117**
- Ceiling: **120** (raised twice in prior addenda, with per-family
  caps and a next-review-at-110)
- Headroom: **3 kinds**

### Projected near-term load

| Source | Kinds | Pattern |
|---|---|---|
| L5 lake-side loop | +3 | propose / confirm / reject (same template as L3/L7/L4) |
| L6 lake-side loop | +3 | same template |
| L8 lake-side loop | +3 | same template |
| Phase 2 lake-maintainer | +4-6 | new observation-only kinds |
| OSI manifest import/export | +2 | catalog-mirror extension |
| **Subtotal 2-3 months** | **+15-17** | — |
| **Total after** | **132-134** | — |

### 12-month projection

| Source | Kinds |
|---|---|
| 2-3 more lake-side loops beyond L5/L6/L8 | +9 |
| 1-2 more named-actor worms (if portfolio expands) | +5-10 |
| Misc per-feature additions | +3-5 |
| **Subtotal 12 months** | **+17-24** |
| **Total** | **~150-160** |

### Recommendation: raise ceiling to **150**

Math:

- Current: 117.
- Reasonable 12-month projection: 150-160.
- Setting ceiling at 150 gives **33 kinds runway** (≈11 more L-axis
  loops worth of headroom).
- If the 12-month projection runs hot (160+), the next freeze-pause
  review at the new-trigger-of-140 catches it cleanly.

Per-family cap revisions to match the lake-side compounding template:

| Family | Old cap | Current count | Recommended new cap | Headroom |
|---|---|---|---|---|
| chat | 12 | 11 | 14 | 3 |
| identity | 10 | 9 | 12 | 3 |
| process | 10 | 5 | 10 | 5 |
| research / autoresearch | 14 | 5 | 14 | 9 |
| governance | 6 | 4 | 8 | 4 |
| **lake / catalog-mirror** | 10 | 9 | **15** | 6 |
| agent-gateway | 10 | 8 | 14 | 6 |
| compounding-loop | 6 | 6 | 10 | 4 |
| **lake-side-loops** (NEW) | — | 9 | **30** | 21 |
| roles / positions / setup | aggregate | 12 | 14 | 2 |
| data-products / notebooks | aggregate | 9 | 12 | 3 |
| tenant / MCP / inference / misc | aggregate | ~19 | 20 | 1 |
| **TOTAL CEILING** | **120** | **117** | **150** | **33** |

The new `lake-side-loops` family explicitly captures the L-axis pattern
(propose / confirm / reject × N axes) which is the canonical
compounding-loop shape going forward. This cap is the operative signal
that L5/L6/L8 etc. are **expected additions** — they are the
architecture's growth axis, not sprawl.

### Doctrine update needed

- §2.5 prose: "current count is 117 (verified post-L4); ceiling 150
  with per-family caps."
- New addendum documents: the 117 verification, the per-family cap
  revisions above, the three retire-actions (`ingest_profiled`,
  `position_metric_added`, `position_question_pattern`), the new
  lake-side-loops family explicit cap of 30, the new review-trigger
  at 140.

---

## Section 5: Decision

**Recommended path: raise ceiling to 150 with per-family cap updates,
paired with formal DEPRECATED marking for three currently-unused
kinds.**

### Rationale

The lake-side L-axis architecture (L3/L7/L4 shipped; L5/L6/L8 planned)
is the institutional-AI growth surface — every loop is +3 kinds
(propose / confirm / reject) and each adds a new compounding axis the
worm grows along. The alternative "retire enough to stay under 110" is
structurally impossible because Rule 1 makes deprecation registry-
size-neutral and consolidation is net-additive. A "mix" path (retire
some + smaller ceiling raise) contributes no net headroom because the
three retire-candidates only change documentation, not registry count.
A clean ceiling raise paired with DEPRECATED marking is more honest
and matches Rule 1's spirit.

### Comparison

| Path | Registry | Headroom | Cost | Honesty |
|---|---|---|---|---|
| Retire enough to stay under 110 | -0 | +0 | High (requires Rule-1 exception) | LOW |
| Raise ceiling to 150 + per-family caps | +0 | +33 | Low (doctrine spec update + 3 DEPRECATED markers) | HIGH |
| Mix: retire some + smaller ceiling raise | +0 | depends | Same as #2 | Same as #2 but obscures that retire doesn't buy headroom |

**Path 2 chosen.** It accepts the operational reality (Rule 1 +
consolidation analysis both rule out registry shrinkage) and reframes
the ceiling as a sized runway for the L-axis growth pattern the
architecture is actively expressing. The +33 headroom buys ~11 more
L-axis loops without re-firing this review; the next-review-trigger at
140 gives a soft reminder before the new ceiling.

---

## Section 6: Implementation arc

### Phase 1 — Doctrine update

**Files to touch:**

- `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` —
  append addendum documenting:
  - 117 verification.
  - Ceiling raise to 150 with per-family caps (table from §4).
  - New `lake-side-loops` family with cap 30.
  - Three DEPRECATED markers landing in this same arc.
  - Next-review-trigger at 140.
- `docs/superpowers/specs/entry-type-registry.md` — append three
  retirement entries following the `heuristic_experiment` template
  (date, reason, replacement, forwarder = none, contract-test
  obligation).

**Estimated wall-clock:** 20-30 min.

### Phase 2 — DEPRECATED markers

**Files to touch:**

- `packages/ledger/src/wormbase_ledger/entries.py`:
  - `IngestProfiledPayload`: add `DEPRECATED: ClassVar[bool] = True`
    + docstring update.
  - `PositionMetricAddedPayload`: same.
  - `PositionQuestionPatternPayload`: same.
- `packages/wormbase-identity-tracker/src/wormbase_identity_tracker/positions.py`
  — update docstring to reflect that the intent-statement for the two
  position kinds is now retired; preserve the line so historical
  readers understand context.
- `packages/ledger/tests/test_deprecated_kinds.py` — add three entries
  to `DEPRECATED_CASES`.

**Estimated wall-clock:** 15-20 min.

### Phase 3 — Optional, recommended: contract test for non-re-emission

Per a prior addendum's still-open action item:

- Create `packages/ledger/tests/test_deprecated_kinds_not_emitted.py`
  — scans the codebase for `kind == "<deprecated_kind>"` literal
  emissions in non-test, non-deprecation-marker production code. Fails
  if any deprecated kind appears in an emit position.

**Estimated wall-clock:** 20-30 min.

### Total estimated wall-clock: 55-80 min

### Migrations

**None.** The DEPRECATED marker is a class-level boolean only; no
projection-table change, no `ALTER TABLE`.

### Tests

- `test_entry_kind_registration.py` size pin stays at 117 (registry
  size does not change; classes still register).
- `test_deprecated_kinds.py` grows by three parametrized cases (round-
  trip validation for each new DEPRECATED kind).
- Existing round-trip tests in `test_entries_payloads.py` and
  `test_entries_step5.py` unchanged.

### Risks

- **Low.** All three retire-candidates have zero production
  producers; marking DEPRECATED only changes their `DEPRECATED` flag
  from absent → True. No behavior change for any consumer.
- The `positions.py` docstring mentions retired emitters as intent-
  statements. Update to mark them retired so future readers don't try
  to wire them.

---

## Cross-references

- `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` —
  the governing doctrine (Rules 1-5 and the addenda).
- `docs/superpowers/specs/entry-type-registry.md` — the retirement
  side-artifact created by a prior addendum.
- [worm-decomposition.md](../orchestration/worm-decomposition.md) —
  the decomposition portfolio whose +4 chat_reply kinds shifted the
  registry past the earlier freeze-pause threshold and triggered the
  doctrine evolution.
- [`ARCHITECTURE.md` §1](../../../ARCHITECTURE.md) — the "kinds are
  forever; payloads are additive-only" doctrine summary.
