# WormBase Schema Evolution Doctrine

**Date:** 2026-05-03
**Status:** Authoritative
**Supersedes:** Implicit per-wave entry-type addition policy

This doctrine governs how ledger entry kinds, projection schemas, and Reactivity contracts evolve over time. Every wave that adds or modifies an entry kind must comply with the rules below. The N2 demo gate and contract-test layer enforce most rules at commit time; rules that cannot be mechanically enforced are reviewed at plan-write time.

---

## 1. Why this doctrine exists now

The lake-maintainer wave (2026-05-03) added 4 new entry kinds (`source_drift_detected`, `source_staleness_signaled`, `source_classification_refreshed`, `source_lineage_break_detected`). With the full PEVR cycle, that's 16 ledger entries per maintenance "observation." The worm-decomposition portfolio plan (chat / identity / research / process / governance extractions) will add an estimated 12-20 more entry kinds, and the planned Phase 2 work on lake-maintainer will add 4-6 more.

**Without a doctrine, entry-type sprawl outruns replay/schema evolution within ~2 quarters.** Replay-to-T from a timestamp before kind X's introduction must still work. The number of kinds an entry router must dispatch to grows monotonically and forever. This doctrine draws the lines.

---

## 2. The five rules

### Rule 1 — Every entry kind is forever.

Once an `emit_<x>` kind has been written to the ledger in production (including pilot-customer ledgers and the demo tenant), the kind is permanent. It cannot be renamed, repurposed, or removed. New uses of the concept get new kinds; old kinds remain readable.

**Why:** the hash chain replays from genesis. Any kind that ever landed must remain handleable, or replay-to-T breaks for any timestamp after that kind's first appearance.

**How to apply:** before adding a new kind, ask "does an existing kind cover this with one extra field?" If yes, prefer the additive change. If no, add the new kind and accept that it joins the permanent registry.

### Rule 2 — Field changes are additive only.

Existing fields on existing kinds cannot be renamed, retyped, or removed. New fields may be added with explicit defaults. Pydantic models keep `extra = allow` (or equivalent) to tolerate unknown fields from older entries.

**Why:** a replay of older entries must construct payloads even if newer code expects more fields. Defaults make this safe.

**How to apply:** schema migrations on projection tables follow the same rule — `ALTER TABLE … ADD COLUMN` only; no `DROP` or `RENAME` columns that ledger-readable code depends on.

### Rule 3 — Deprecation is retired-not-deleted.

A kind that is no longer emitted by current code but exists in historical ledgers gets a `@deprecated` marker in the entry-type registry, a deprecation date, and a forwarder (if applicable) that translates it into the canonical replacement at read time. The registry never shrinks.

**Why:** Rule 1 implies retirement is the only deprecation that survives replay. Forwarders are how new projections handle old kinds.

**How to apply:** when retiring a kind, write the forwarder + a note in `docs/superpowers/specs/entry-type-registry.md` (TODO: create as a side artifact when the first kind is retired) explaining why and when.

### Rule 4 — Replay is graceful for unknown kinds.

The replay engine and projection builders must no-op (with a logged warning) on unknown kinds, never crash. This protects forward-compatibility for older binaries reading newer ledgers, and reverse-compatibility for newer binaries reading sparse historical ledgers.

**Why:** without graceful unknowns, every binary upgrade is a coordinated cluster event. Graceful unknowns mean rolling upgrades work.

**How to apply:** the kind dispatcher returns a "skipped: unknown kind" status; the entry counts toward `ledger_entries_skipped_unknown` telemetry but does not raise.

### Rule 5 — Freeze pause at 50 distinct kinds.

When the registry reaches 50 distinct kinds, **stop adding** until a quarterly review establishes which kinds collapse to which (Rule 3 retirements) and which new kinds are warranted. The current count is approximately 28 kinds (lake-maintainer's 4 included). The portfolio plan's expected additions take the count to ~45-55. The freeze pause may fire mid-portfolio.

**Why:** there is no cardinality at which the substrate breaks, but there is a cardinality at which contributors cannot internalize the kind set. 50 is the current empirical threshold; review the threshold itself at the freeze pause.

**How to apply:** the review surfaces (a) candidate retirements, (b) candidate consolidations, (c) hard requirements for additions. Resume only after a written "what changes / what doesn't" decision.

---

## 3. Decision: PEVR-for-observation

**Question raised:** maintenance signals (`source_drift_detected`, etc.) write the full 4-entry PEVR cycle even though `verify_fn` always passes and `resolve_fn` always keeps. The pattern multiplies entry counts ~4× for observation-only emissions. Should observation-only emissions get a shorter "P-only" entry path?

**Decision: keep PEVR for all writes. No exceptions.**

**Rationale:**
1. **Governance value compounds.** The full cycle's `verify` step is the audit anchor that proves "this signal landed and was acknowledged." The `resolve` step is what makes the signal terminal vs. provisional. Both have audit value even when their content is fixed.
2. **Exception precedent is dangerous.** Once "observation-only" exists as a pattern, every new feature can claim it. Within ~3 waves, the PEVR rule erodes into "PEVR when convenient." That undermines the substrate's central commitment.
3. **Cost is bounded.** Maintenance signals are <10% of total entry volume on a moderately active workspace (chat traffic dominates). The 4× multiplier on a 10% slice is operationally invisible.
4. **The ceremony is the rule.** Architectural commitments hold by being uniformly applied, not by being applied where they're strictly necessary.

**Documentation note:** the empty-cycle pattern (`verify_fn = lambda _: {"checks": [...], "passed": True}`, `resolve_fn = lambda _: {"outcome": "keep", "rationale": "..."}`) is **canonical** for observation-emitting Reactivities. Lake-maintainer's `_emit_signal` helper is the reference implementation. Future worms reuse the same shape.

---

## 4. Adding a new entry kind — process

Before a wave that introduces a new kind, the plan author must:

1. **Verify against Rule 1.** Search the existing registry for adjacent kinds; document why an existing kind cannot be extended (Rule 2 application).
2. **Document the kind in the plan.** Name, payload shape, emitter (which Reactivity / write path), consumer projections, lifecycle (what fires it, when).
3. **Add to the contract-test layer.** Round-trip serialization, replay-handles-unknown, projection-builder-folds-it. These tests live with the package owning the emit.
4. **Update the kind dispatcher.** Both the projection builder's fold table and any registry-based router get the new kind.
5. **Cross-check Rule 5.** If the addition would push the registry past 50, **block the wave** and trigger the freeze-pause review.

This is non-negotiable plan-write-time work. Pre-execution verification (the lake-maintainer ritual) checks that the implementation matches the plan's claims about kind shape.

---

## 5. Deprecating a kind — process

When a kind is no longer emitted by current code:

1. **Mark `@deprecated`** in the entry-type registry, with date and replacement (if any).
2. **Write the forwarder.** If a replacement kind exists, the forwarder maps `old_payload → new_payload` at projection-build time. If no replacement exists (the concept is retired entirely), the forwarder returns "drop" and the projection builder skips.
3. **Update the contract tests.** The deprecated kind's tests prove the forwarder works on historical entries; they don't prove emit (since current code no longer emits).
4. **Document in the registry doc.** Why retired, when, replacement (or "concept retired").

The kind itself remains in the dispatcher table. Forever.

---

## 6. PEVR cycle authoring rules

Reaffirming for clarity, given the doctrine governs all writes:

- **`propose`** — payload shape: `{target_kind, ref_id, reason, proposed_by}`. `target_kind` IS the entry kind being proposed; `ref_id` is the resource the entry concerns; `reason` is intent-conveying prose; `proposed_by` is the actor (Person UUID, or `"<worm-name>"` for agent emissions).
- **`execute_fn`** — returns `{tool, args, result_ref}`. `tool` is the kind name (matches `target_kind`). `args` is the payload. `result_ref` is the kind's identifier (e.g. `source_id`, `kpi_node_id`).
- **`verify_fn`** — returns `{checks: [{name, ok}], passed: bool}`. For observation-only emissions, a single check `{name: "<kind>_recorded", ok: true}` and `passed: true` is canonical.
- **`resolve_fn`** — returns `{outcome: "keep" | "discard", rationale: str}`. For observation-only, `keep` with an intent-conveying rationale.

The `_emit_signal` helper in `packages/lake-maintainer/src/wormbase_lake_maintainer/reactivities.py` is the reference. New worms either import it or re-implement the same shape.

---

## 7. Telemetry the substrate must expose

The doctrine implies the following telemetry surfaces (most exist; verify all are wired before freeze-pause):

- `ledger_entries_total{kind}` — entry count per kind, per tenant
- `ledger_entries_skipped_unknown` — graceful-no-op counter (Rule 4)
- `entry_kind_registry_size` — distinct kind count (drives Rule 5)
- `pevr_cycle_duration_p99{kind}` — write-primitive latency
- `projection_build_lag{projection}` — staleness of materialized views

These are observability obligations, not optional. New waves that add kinds also add telemetry for them.

---

## 8. What this doctrine does not govern

For clarity, the following are out of scope:

- Connector / ChannelAdapter Protocol evolution (governed by their respective package contract tests)
- Reactivity Protocol evolution (governed by W5a's contract surface in `packages/reactivities`)
- HTTP / MCP API surface evolution (governed by the OpenAPI schema and MCP tool catalogs)
- Database substrate migrations beyond projection tables (covered by alembic-style migration tooling)

These layers have their own evolution disciplines. This doctrine is exclusively about ledger entry kinds and the projections that fold them.

---

**Authority:** this doctrine is binding for all worm extraction waves and for any feature work that adds or modifies entry kinds. Update it (additively, per Rule 2) when a freeze-pause review or post-mortem yields new constraints.

---

## Addendum 1 — Calibration finding (Wave F, 2026-05-03)

The doctrine at §2.5 ("Rule 5 — Freeze pause at 50 distinct kinds") and the projected progression table both stated the registry was "approximately 28 kinds" at doctrine-write time. **That figure was an undercount.**

### Verified registry size

A `grep 'kind: ClassVar\[str\] = "' packages/ledger/src/wormbase_ledger/entries.py | wc -l` at the close of the worm-decomposition portfolio (Wave F, post-Wave-E) returns **74 concrete kinds**.

Wave-by-wave reconstruction:

| Stage | Doctrine projection | Verified count |
|---|---|---|
| Pre-doctrine (lake-maintainer landed) | "~28" | **71** |
| After Wave A (identity v1) | 28 | 71 (no new kinds) |
| After Wave B (chat-worm) | 32 | 75 (Wave B added 4 `chat_reply_*` family) |
| After Wave C (research + process) | 32 | 75 (no new kinds) |
| After Wave D (governance consolidation) | 34 | 75 (no new kinds; `setup_step_advanced` etc. were already in registry) |
| After Wave E (hub redefinition) | — | 75 (no new kinds) |
| After Wave F (this addendum) | — | **74** (one observed delta vs the +4 chat_reply count — likely a deprecation-as-removal accounting drift; see issue note below) |

The lake-maintainer's `source_drift_detected`, `source_staleness_signaled`, `source_classification_refreshed`, `source_lineage_break_detected` kinds appear as `target_kind` strings in PEVR `propose` payloads but are **not registered as concrete Pydantic entry classes** in `entries.py`. They flow as kinds-within-kinds (riding inside generic `propose`/`execute`/`verify`/`resolve` envelopes), which is consistent with the PEVR-for-observation pattern in §3 of this doctrine but inconsistent with the per-kind class registration pattern most other entries follow. **Issue: this asymmetry should be reviewed at the freeze-pause review (see below).**

### Implications for Rule 5

Rule 5 set a freeze pause at 50 kinds. The threshold was already breached when the doctrine was written — by 21 kinds, not by zero. Three options going forward:

**Option A — Raise the threshold to ~100** and continue the current pattern. Justification: the contributors-cannot-internalize argument is empirical, and a 75-kind registry is currently being maintained without observable confusion (Waves A-E all conformed to Rule 1-4 without difficulty). Setting 100 gives a 25-kind buffer for B.5 (+2), Phase 2 lake-maintainer (+4-6), and ad-hoc additions before the next review.

**Option B — Execute a formal freeze-pause review now.** Justification: Rule 5's mechanism is meant to fire periodically; treating the breach as already-fired triggers the "what changes / what doesn't" decision the rule was designed to force. Likely outcomes: candidate consolidations (e.g., the four `data_product_*` kinds could collapse to one `data_product_event` with a `phase` field; the four `notebook_*` similarly), candidate retirements (heuristic_experiment is unused post Wave C₁ deletion; survives in registry per Rule 1 but should be marked `@deprecated`), and reaffirmation of the additive-only PEVR pattern.

**Option C — Both.** Raise the threshold to ~100 *and* schedule a freeze-pause review at a calendar checkpoint (e.g., end of Q2 2026). This is the recommended path. It preserves Rule 5's discipline while acknowledging the threshold was set on a wrong baseline.

### Recommendation

Adopt **Option C**:
1. Raise the Rule 5 threshold to **100 distinct concrete kinds** (`grep 'kind: ClassVar\[str\] = "'` in `entries.py`, excluding the abstract base) until the formal review.
2. Schedule a freeze-pause review at the start of the next major wave that would otherwise add kinds (Wave B.5 at minimum, since it adds +2). The review owns:
   - Candidate consolidations across the `data_product_*` (4), `notebook_*` (4), `setup_*` (3), `reactivity_*` (4), `chat_reply_*` (4), `experiment_*` (3), `resource_conversation_*` (3) families
   - Candidate retirements: `heuristic_experiment` (post-Wave-C₁ unused per `docs/superpowers/notes/2026-05-03-worm-decomposition-orchestration.md` §VIII), any other unused-in-current-code kinds discovered during the audit
   - Lake-maintainer kind asymmetry: do `source_drift_detected` and family graduate to concrete classes, or do we accept and document the "kind-within-kind" pattern as canonical for observation-only signals? (This question is genuinely open.)
3. Update §2.5's "current count" prose from "approximately 28" to "74 (verified 2026-05-03)" so future doctrine readers don't inherit the wrong baseline.

### Status

This addendum supersedes the projected progression table in §2.5 (which understated by ~40 kinds) and the sentence "the freeze pause may fire mid-portfolio" (it had already fired pre-portfolio). Rules 1-4 remain unchanged; only Rule 5's numerics are revised.

The addendum itself is additive per Rule 2 (no doctrine fields renamed or removed). Future addenda follow the same pattern: append, don't rewrite.

**Authority:** this addendum is binding alongside the original doctrine. The freeze-pause review (Option C step 2) is required before Wave B.5 dispatches.

---

## Addendum 2 — Freeze-pause review (2026-05-04)

This addendum executes the freeze-pause review mandated by Addendum 1 (Option C, step 2). Wave B.5 (`PositionInferenceReactivity` and `ResourceOwnershipReactivity`, +2 entry kinds) is gated on the outcomes recorded here.

Verification baseline: `grep 'kind: ClassVar\[str\] = "' packages/ledger/src/wormbase_ledger/entries.py | wc -l` returns **74 concrete kinds** at HEAD `a804dfa` (2026-05-04). This matches the count in Addendum 1.

### A. Threshold raise — Rule 5

The Rule 5 threshold of "50 distinct kinds" was set on a wrong baseline (the doctrine's "approximately 28 kinds" prose understated the registry by ~40 kinds). Empirically, Waves A-E composed and shipped against a 71-75-kind registry without contributors reporting kind-set confusion or replay incidents.

**Decision:** raise Rule 5 to **100 distinct concrete kinds**. The §2.5 prose ("current count is approximately 28 kinds") is superseded by "current count is 74 (verified 2026-05-03 and re-verified 2026-05-04)." After Wave B.5 (+2 kinds: `emit_position_proposed`, `emit_resource_role_proposed`), the registry will read **76**, leaving a **24-kind buffer** for Phase 2 lake-maintainer (+4-6) and ad-hoc additions before the next freeze-pause review.

**Next review trigger:** when the registry reaches **90 concrete kinds** (10-kind buffer to the new threshold), re-execute the freeze-pause review with this addendum as the template. Or at the start of Q3 2026 — whichever comes first.

### B. Consolidation candidates surveyed (no action this wave)

The seven kind-families flagged in Addendum 1 were reviewed against Rule 1 (every kind is forever) and Rule 2 (additive-only). All consolidation paths require forwarders that translate the existing concrete kinds into a hypothetical consolidated kind at projection-build time. **No consolidation is taken in this review.** Each family is documented below for future reference.

| Family | Concrete kinds | Shape | Decision | Rationale |
|---|---|---|---|---|
| `data_product_*` | `emit_data_product_published`, `emit_data_product_consumed`, `emit_data_product_proposed`, `emit_data_product_demoted` (4) | Same payload skeleton; differ only in lifecycle phase | **Keep as-is** | Rule 2 consolidation requires a forwarder + a `phase` field on the consolidated kind. Net entry count is identical. No projection simplification because the projection already folds all four through a kind-dispatch table. |
| `notebook_*` | `emit_notebook_proposed`, `emit_notebook_published`, `emit_notebook_demoted`, `emit_notebook_consumed` (4) | Mirrors `data_product_*` | **Keep as-is** | Same analysis as data_product. The mirror is intentional — notebooks are data products. |
| `setup_*` | `emit_setup_step_advanced`, `emit_setup_step_completed`, `emit_setup_step_skipped` (3) | Domain-specific phases | **Keep as-is** | The three kinds carry distinct downstream consumers (setup-progress projection branches on kind, not on a phase field). Consolidation regresses readability. |
| `chat_reply_*` | `emit_chat_reply_proposed`, `emit_chat_reply_executed`, `emit_chat_reply_verified`, `emit_chat_reply_resolved` (4) | Full PEVR cycle for chat presence | **Keep as-is** | These are the canonical PEVR-cycle expression for chat-presence. Consolidating to one kind with a `phase` field collapses PEVR's audit shape and breaks Rule 1's "ceremony is the rule" commitment in §3. |
| `experiment_*` | `emit_experiment_proposed`, `emit_experiment_executed`, `emit_experiment_resolved` (3) | PEVR-without-verify | **Keep as-is** | Mirrors `chat_reply_*`. Research-loop's canonical autoresearch cycle. |
| `resource_conversation_*` | `emit_resource_conversation_added`, `emit_resource_conversation_removed`, `emit_resource_conversation_relinked` (3) | Lifecycle of conversation-resource binding | **Keep as-is** | Distinct downstream behaviour per kind. Removed and relinked have separate audit semantics; collapsing them confuses "resource left" vs "resource moved." |
| `reactivity_*` | `emit_reactivity_proposed`, `emit_reactivity_executed`, `emit_reactivity_verified`, `emit_reactivity_resolved` (4) | PEVR cycle for Reactivity-emitted writes | **Keep as-is** | Same analysis as `chat_reply_*`. Substrate-level PEVR shape. |

**Consolidation policy going forward:** consolidation across kinds is only undertaken when (a) one of the existing kinds has zero historical-ledger occurrences across all tenants (mechanically verifiable) AND (b) the consolidated kind enables a meaningful projection simplification. Both conditions are rare. The default answer to "should we consolidate?" is **no** — Rule 1's permanence makes consolidation a net-additive operation, not a net-reductive one.

### C. Retirement — `heuristic_experiment`

The `heuristic_experiment` kind was emitted by `wormbase_core.heuristic_loop.HeuristicLoop`, which was deleted in Wave C₁ of the research-worm extraction (per `docs/superpowers/notes/2026-05-03-worm-decomposition-orchestration.md` §VIII row "Heuristic_loop deleted entirely (-312 LOC)"). Zero production callers remain.

**Status:** the entry class at `packages/ledger/src/wormbase_ledger/entries.py:391` already carries `DEPRECATED: ClassVar[bool] = True`. The payload schema is preserved per Rule 1; historical ledgers replay cleanly.

**Decision:** mark the kind formally retired in the entry-type registry side artifact (`docs/superpowers/specs/entry-type-registry.md`, created in this wave per F.2). Forwarder is not required — the concept retired entirely (autoresearch now flows through `wormbase_research_loop`'s `experiment_*` PEVR cycle), so historical entries fall through Rule 4's graceful-skip on replay-time encounter. No replacement mapping exists.

**Future-emit guard:** new code MUST NOT emit `heuristic_experiment`. The `DEPRECATED` marker is the source-of-truth signal; no test currently fails on emission attempts because the emit path is deleted. If a future contributor re-introduces an emitter, the contract-test layer (`packages/ledger/tests/test_deprecated_kinds_not_emitted.py`, TODO if it does not exist) must catch it. **Action item for Block G or later:** confirm a contract test exists or add one; tracked in the registry side artifact.

### D. Lake-maintainer kind asymmetry — accept as canonical

The four lake-maintainer signals (`source_drift_detected`, `source_staleness_signaled`, `source_classification_refreshed`, `source_lineage_break_detected`) flow as `target_kind` strings inside generic `propose`/`execute`/`verify`/`resolve` envelopes rather than as concrete Pydantic entry classes. Addendum 1 flagged this as a "kind-within-kind" asymmetry vs. the per-class registration most other entries follow.

**Decision: accept and document the kind-within-kind pattern as canonical for observation-only signals.**

**Rationale:**
1. **§3 already implies this pattern.** The PEVR-for-observation rule canonicalizes the empty-cycle shape (`verify_fn` returns `passed: true`, `resolve_fn` returns `outcome: keep`) for observation-emitting Reactivities. The kind-within-kind expression is the natural payload-level corollary: the signal name is data, not a Pydantic class.
2. **It keeps the registry small.** Promoting the four signals to concrete classes would push the registry to 78 immediately and create sprawl pressure on every future observation-only signal (lake-maintainer's Phase 2 will add 4-6 more). The kind-within-kind path scales without adding registry weight.
3. **Replay is unaffected.** Historical entries already flow as generic `propose`/`execute`/`verify`/`resolve` envelopes; changing them to concrete classes would be a Rule-1 violation. Accept-and-document is the only path consistent with Rule 1.
4. **Audit value is preserved.** The full PEVR cycle still writes; the `target_kind` string in the `propose` payload is queryable for the same audit purposes a concrete class would serve.

**Documentation:** §3 is updated implicitly by this addendum to note that "observation-emitting Reactivities MAY express their signal name as a `target_kind` string inside generic PEVR envelopes rather than as a concrete entry class. This is canonical for kind-within-kind observation-only emissions; lake-maintainer's `_emit_signal` helper is the reference implementation." Future addenda may upgrade this to inline §3 text.

**Telemetry consequence:** the `ledger_entries_total{kind}` series counts only concrete kinds. Kind-within-kind signals are observable via a derived series `ledger_observation_signals_total{target_kind}` which is materialized by the projection that folds the observation-PEVR family. (Telemetry obligation per §7; verify before next freeze-pause review.)

### E. Wave B.5 sign-off

Wave B.5 ships two new entry kinds — `emit_position_proposed` and `emit_resource_role_proposed` — to support `PositionInferenceReactivity` and `ResourceOwnershipReactivity` per Block G of `docs/superpowers/plans/2026-05-04-deferred-backlog.md` (lines 506-521).

**Verification against Rule 1 (every kind is forever):**
- `emit_position_proposed` — no adjacent kind covers position inference. The closest existing kind is `emit_person_proposed` (proposes a Person row); positions are an orthogonal facet (position assignment ≠ person creation). Distinct kind warranted.
- `emit_resource_role_proposed` — no adjacent kind covers resource-role proposals. `emit_resource_role_assigned` is the confirm-step kind; the propose-step is the new kind. Distinct kind warranted.

**Post-Wave-B.5 registry:** 74 + 2 = **76 concrete kinds**. Well under the new 100 threshold.

**Decision: Wave B.5 (+2 kinds) is approved.** Block G of the deferred-backlog plan may dispatch.

### F. Action items emerging from this review

1. **Create `docs/superpowers/specs/entry-type-registry.md`** with the `heuristic_experiment` retirement note. (Block F.2 of the deferred-backlog plan; lands in the same wave as this addendum.)
2. **Add a contract test or audit step** that pins "no current code emits `heuristic_experiment`" — owned by Block G or a follow-on cleanup wave.
3. **Verify `ledger_observation_signals_total{target_kind}` telemetry exists** for the kind-within-kind family — owned by the next freeze-pause review (or sooner if observability work touches the lake-maintainer projection).

### Status

This addendum supersedes Addendum 1's Recommendation section (which proposed Option C without executing it). Rules 1-4 remain unchanged; Rule 5's threshold is raised to 100 per §A. Sections B-D record the consolidation, retirement, and asymmetry decisions. Section E approves Wave B.5. Section F lists carry-overs.

The addendum itself is additive per Rule 2 (no doctrine fields renamed or removed).

**Authority:** this addendum is binding alongside Addendum 1 and the original doctrine. Wave B.5 (Block G of the deferred-backlog plan) is unblocked.

---

## Addendum 3 — conversation_sync added (2026-05-05)

KIND_REGISTRY: 82 → 83. Concrete kind: `conversation_sync`.
Quadrant: `passive_deterministic`.
Rationale: per-session lineage entry for bulk historical-message imports
(WhatsApp reconnect, initial connect, channel join). Per-message
chat_received entries from a sync reference the parent via
history_sync_id. Provenance fields (delivery_mode, platform_ts,
history_sync_id) added to ChatReceivedPayload — additive, defaults
preserve back-compat.

Reviewed against freeze-pause threshold (100, per Addendum 2):
well under (83/100). No retired kinds. No structural breakage.
Approved.

Cross-ref: `docs/superpowers/plans/2026-05-05-whatsapp-and-conversation-provenance.md`,
commits 0969537 (substrate), 6d81bc1 (WhatsApp adapter using the kind).

---

## Addendum 3 — Freeze-pause review (2026-05-11, Semantic-Layer Wave 2 gate)

This addendum executes the freeze-pause review triggered by the spec at `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` §9 Risk #10. Wave 2 of the semantic-layer build (`wormbase-agent-gateway` package + the §4.5 compounding query layer) is gated on the outcomes recorded here.

Verification baseline: `grep 'kind: ClassVar\[str\] = "' packages/ledger/src/wormbase_ledger/entries.py | wc -l` returns **88 concrete kinds** at HEAD `9022476` (2026-05-11, post Wave 1 catalog-mirror).

Trail: Addendum 1 raised the threshold to 100 with a buffer-of-10 review trigger. Addendum 2 (Wave B.5 review) re-affirmed the threshold and surveyed consolidation candidates without taking action. Addendum 3 (this) fires per Addendum 1's "next review trigger when registry reaches 90" rule — Wave 2 brings the registry through 88 → 96 (with 8 new kinds), and Wave 3 has further additions in scope, so the gate fires before the breach rather than after.

### A. Threshold raise — Rule 5

Empirical evidence so far: the registry crossed 50 (original threshold) without observable contributor confusion, crossed 75 (post-portfolio) without observable confusion, and is currently at 88 with all worm packages composed and shipped against it cleanly (Wave 1 just landed `wormbase-catalog-mirror` adding 5 kinds — `external_catalog_*`, `external_lineage_imported`, `external_policy_imported`, `external_metric_imported` — with zero replay incidents and zero kind-set confusion).

Wave 2 will add 8 kinds (88 → 96):
- agent-gateway core: `agent_registered`, `agent_grant`, `agent_query`, `credential` (4)
- §4.5 compounding query layer: `query_outcome_recorded`, `query_correction_suggested`, `semantic_gap_proposed`, `query_template_promoted` (4)

Wave 3 (dashboard + lake-maintainer dual-mode + ASML demo wiring) will not introduce new entry kinds per the spec §10 task list — dashboard surfaces are read-side only.

Forward calibration: Wave 2 lands 96 kinds; Wave 1.1 OAuth path test work is read-side; Wave 1.1 OSI import/export work may add ~2 kinds (`osi_manifest_imported`, `osi_manifest_exported`); planned semantic-layer future work (M&A integrations, more catalog sources) does not anticipate large kind-additions because they reuse the `external_*` family.

**Decision:** raise Rule 5 to **120 distinct concrete kinds** with **per-family caps** to give the doctrine shape rather than just a number:

| Family | Cap | Current count | Headroom |
|---|---|---|---|
| chat | 12 | 11 (chat_received, chat_reply_*, mentions_*, conversation_sync, …) | 1 |
| identity | 10 | 7 (person_*, identity_*, install_*, role_*) | 3 |
| process | 10 | 8 (process_map_proposed/published, decision_recorded, …) | 2 |
| research / autoresearch | 14 | 12 (propose/execute/verify/resolve cycles + experiment_*) | 2 |
| governance | 6 | 4 (gate_fired, policy_proposed, classification_*, domain_role_*) | 2 |
| lake / catalog-mirror | 10 | 5 (Wave 1 just added 5; lake-maintainer signals fold into agent_query elsewhere) | 5 |
| agent-gateway | 10 | 0 (Wave 2 adds 4) | 10 → 6 after Wave 2 |
| compounding-loop | 6 | 0 (Wave 2 adds 4) | 6 → 2 after Wave 2 |
| infra / data-products / notebooks / setup / heuristic / topics / misc | aggregate ~42 | aggregate ~41 | aggregate ~1 |

The per-family caps replace the single-number threshold with a doctrine: each named-actor worm gets ≤10 kinds without triggering a review; cross-family additions over 120 total still require a review. The aggregate row catches the long tail of cross-cutting infra kinds and is intentionally tight — net-new infra kinds should be rare.

**Next review trigger:** when the registry reaches **110 concrete kinds** (10-kind buffer to the new threshold), re-execute the freeze-pause review with this addendum as the template.

### B. Wave 2 kinds — review

Per `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` §6.1 (post §4.5 amendment), the 8 Wave 2 kinds are:

| # | Kind | Status-field consolidation? | PEVR single-kind? | Decision |
|---|---|---|---|---|
| 1 | `agent_registered` | — | — | KEEP |
| 2 | `agent_grant` | YES (assign / revoke) | — | KEEP |
| 3 | `agent_query` | — | YES (4 phases under one kind) | KEEP |
| 4 | `credential` | YES (issue / revoke) | — | KEEP |
| 5 | `query_outcome_recorded` | — | — | KEEP |
| 6 | `query_correction_suggested` | — | — | KEEP |
| 7 | `semantic_gap_proposed` | — | — | KEEP |
| 8 | `query_template_promoted` | — | — | KEEP |

### Consolidations considered and rejected (per spec §6.2 + this review)

1. **Could `query_outcome_recorded` fold into `agent_query.resolve` phase?** REJECTED. Different temporality: outcome lands AFTER user feedback (minutes-to-days later, often via a callback from the calling agent), while `agent_query.resolve` is synchronous at MCP-call return time. Folding them collapses two distinct ledger events into one and breaks the temporal causation chain that downstream projections + dashboards need.
2. **Could `query_template_promoted` be a status of `external_metric_imported`?** REJECTED. Distinct provenance: WormBase-derived (from accumulated agent outcomes via the W5a `OutcomeToTemplatePromotion` Reactivity) vs upstream-imported (from dbt manifest / Snowflake / etc.). Provenance is a primary projection facet for `/lake/metrics-proposed` and audit replay.
3. **Could `agent_query` be split into `agent_query_proposed`, `agent_query_executed`, `agent_query_verified`, `agent_query_resolved` (4 separate kinds)?** REJECTED. Splits the PEVR single-kind contract that lake-maintainer (Wave 1), chat-presence, process-extractor, and research-loop all use canonically. PEVR phases are a property of how the entry is *written* (via `Ledger.write(propose=, execute_fn=, verify_fn=, resolve_fn=)`), not a kind axis. Splitting would force every existing PEVR consumer to either fold across 4 kinds or accept inconsistency. **Single-kind PEVR is the canonical pattern.**
4. **Could `semantic_gap_proposed` + `query_correction_suggested` fold into `agent_query` with a sub-type field?** REJECTED. Observed at different junctures: `query_correction_suggested` chains via `caused_by` inside a single agent_query lifecycle (multi-retry self-correction loop); `semantic_gap_proposed` fires when NO matching metric exists for an NL question (no enclosing agent_query lifecycle). Dashboard surfaces them differently (`/lake/query-improvement` retry chain vs `/lake/metrics-proposed` admin queue). Folding regresses both UX and audit clarity.

### C. Status-field consolidations already applied (no further action)

Per spec §6.1, two consolidations were already designed into Wave 2:

- `agent_grant` uses a status field to cover both assign and revoke (saves 1 kind vs separate `agent_grant_revoked`)
- `credential` uses a status field to cover both issue and revoke (saves 1 kind vs separate `credential_revoked`)

These match the schema-evolution doctrine §3 status-field-over-separate-kind pattern.

### D. Implications

- **Wave 2 dispatch unblocked.** All 8 kinds approved as-is; no consolidations applied during this review.
- **`agent_grant` and `credential` status-field shape** must be enforced by the Wave 2 implementer: the Pydantic Payload classes for these two kinds declare `status: Literal["active", "revoked"]` (or equivalent enum). The Wave 2 plan must call this out explicitly as a non-negotiable in Task descriptions.
- **`agent_query` single-kind PEVR** must be enforced by the Wave 2 implementer: writes go through `Ledger.write(propose=, execute_fn=, verify_fn=, resolve_fn=)`, not via separate `emit_agent_query_*` helpers per phase.
- **Per-family caps now binding.** Any future PR that adds an entry kind must show, in the PR description, which family the kind belongs to and the post-add count against the cap. PRs that exceed a family cap trigger an inline review (this addendum's template).
- **Next review trigger at 110 kinds.** Wave 2 lands at 96; Wave 3 lands at 96 (read-side only). Wave 1.1 OSI work would bring us toward 98. Plenty of headroom for routine work; ad-hoc additions in unrelated waves consume the headroom faster than planned features.

### E. Authority

This addendum is binding alongside the original doctrine and Addenda 1 + 2. The threshold raise to **120** and the per-family caps in §A above are the operative numbers going forward.

Cross-ref:
- `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` §6 (entry kinds) + §9 Risk #10 (threshold trigger)
- `docs/superpowers/plans/2026-05-11-semantic-layer-wave-1-catalog-mirror.md` (Wave 1, +5 kinds)
- `docs/superpowers/notes/2026-05-11-semantic-layer-wave-1-shipped.md` (Wave 1 close-out)
- Wave 2 plan (to be written, post this addendum)

---

## Addendum 4 — Freeze-pause review (2026-06-04, L4 close-out trigger)

This addendum fires per Addendum 3's "next review trigger when registry reaches 110" rule. L4 (schema-evolution-impact) shipped 2026-06-03 at KIND_REGISTRY=117 — 3 kinds headroom under the 120 ceiling Addendum 3 set. The review verifies the doctrine still holds and decides whether to retire kinds, consolidate, or raise the ceiling.

Verification baseline: `KIND_REGISTRY = 117` at HEAD `7b5ebf2` (2026-06-04). Migrations `[1..23]`. 11 maintenance arcs cumulative since 2026-05-21.

### A. Audit summary

Full kind-by-kind audit at `docs/superpowers/notes/2026-06-04-schema-evolution-doctrine-review.md` (513 lines). Headline counts:

- **CORE (substrate-load-bearing):** 4 (`propose`, `execute`, `verify`, `resolve`)
- **ACTIVE (wired):** ~110 kinds with producers + consumers, or consumer-ready with planned-emit
- **CONSOLIDATABLE:** 7 families surveyed; **none recommended** (each costs more than it saves per Rule 1)
- **RETIRABLE:** 3 net-new + 1 already-deprecated = 4 total
- **DEMO/LEGACY:** 1 (`heuristic_experiment`, already in Addendum 2 §C)

### B. Why path (a) "retire enough to shrink the registry" is structurally impossible

The Python `KIND_REGISTRY` is populated via `EntryPayload.__init_subclass__` at module import time. Every concrete `EntryPayload` subclass declared in `packages/ledger/src/wormbase_ledger/entries.py` registers automatically. To shrink `len(KIND_REGISTRY)` you must DELETE the class — which violates Rule 1 (kinds-forever).

Marking classes DEPRECATED in docstrings is documentation hygiene only — it warns future contributors away from wiring the kind, but the registry count stays the same.

**Therefore Rule 1 + the registration mechanism jointly preclude path (a).** Any future ceiling discussion must either consolidate (which Addendum 2 §A-B already ruled out family-by-family) or raise the ceiling.

### C. The 3 net-new DEPRECATED kinds (documentation only)

Per the audit, the following kinds have **HIGH confidence** of no producer + no consumer in current code. Marked DEPRECATED in `packages/ledger/src/wormbase_ledger/entries.py` docstrings so future contributors don't wire them. Registry count unaffected.

| Kind | Location | Verdict |
|---|---|---|
| `ingest_profiled` | `entries.py:252` | Superseded by `source_profiled` (Wave 1 catalog mirror flow). |
| `position_metric_added` | `entries.py:929` | Intent-doc only; never wired; if revived, use a fresh kind matching the lake-side triple pattern. |
| `position_question_pattern` | `entries.py:939` | Intent-doc only; never wired. |

(Plus `heuristic_experiment` already marked deprecated in Addendum 2 §C.)

### D. Decision: raise the ceiling to 150

The L-axis lake-side compounding loops (L3 + L7 + L4 shipped; L5 + L6 + L8 planned) each add 3 ledger kinds. At 117 today, after L5+L6+L8 we'd be at 126. Plus L3/L7/L4-Phase-2 work adds 0-1 kinds each. Realistic 12-month projection: 135-145.

**Raising the ceiling to 150 buys ~33 kinds of runway** = ~11 more L-axis loops or equivalent additive growth.

This is sized for the institutional-AI growth surface this codebase targets, not for routine bloat — the lake-side compounding template is a deliberate growth axis, not entropy to fight.

**Per-family caps from Addendum 3 §A are preserved.** Each new family gets ≤10 kinds without triggering a review; cross-family additions over 150 total still require review.

### E. Per-family cap updates for the L-axis family

Addendum 3 §A defined per-family caps for then-existing named-actor worms. The L-axis lake-side family is the new growth pattern; add it explicitly to the table:

| Family | Cap | Current | Notes |
|---|---|---|---|
| lake-side L-axis (lineage/quality/schema-impact/...) | 30 | 9 (3 per axis × 3 axes shipped) | 3 kinds per axis; 7 more axes possible before cap |

The 30-cap for the L-axis family allows L3+L7+L4+L5+L6+L8+two-more = 10 axes × 3 kinds = 30, matching the doctrine's intent.

### F. Next review trigger at 140

Per Addendum 1's "buffer-of-10" pattern, next review fires when registry reaches **140** (10 kinds before the new 150 ceiling). Expected timing: after 2-3 more lake-side loops ship.

### G. Authority

This addendum is binding alongside the original doctrine + Addenda 1-3. The threshold raise to **150** + the L-axis family cap of **30** + the 3 DEPRECATED-marked kinds are the operative changes.

Cross-ref:
- `docs/superpowers/notes/2026-06-04-schema-evolution-doctrine-review.md` (full audit)
- `docs/superpowers/notes/2026-06-03-l4-shipped.md` (L4 close-out — triggered this review)
- L5/L6/L8 specs (to be written when picked) — each must verify L-axis-family cap headroom in plan-doc
