# Entry-Type Registry — retirement and deprecation notes

**Status:** Authoritative
**Created:** 2026-05-04
**Governed by:** [`docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`](2026-05-03-schema-evolution-doctrine.md) (Rule 3 — deprecation is retired-not-deleted; Rule 4 — replay is graceful for unknown kinds).

This file is the side artifact the doctrine §3 placeholder ("TODO: create as a side artifact when the first kind is retired") becomes when a kind is formally retired. It records every kind that has been retired or deprecated, the date, the replacement (if any), the forwarder strategy, and any contract-test obligations. The file grows monotonically — entries are appended, never removed or rewritten.

The concrete Pydantic class for a retired kind **stays in `packages/ledger/src/wormbase_ledger/entries.py` forever** per Rule 1. This file is documentation of why and when, not a deletion log.

---

## Format

Each entry:

- **Kind name** (matches the `kind: ClassVar[str]` value in `entries.py`)
- **Retired date** (ISO 8601, the date emit was deleted from production code)
- **Reason** (1-3 sentences)
- **Replacement kind** — name of the canonical replacement, or "concept retired (no replacement)"
- **Forwarder** — projection-build-time mapping `old_payload → new_payload`, or "none — Rule 4 graceful-skip"
- **Contract-test obligations** — what tests guard the retirement
- **Source link** — commit, plan, or doc that authorized the retirement

---

## Retired kinds

### `heuristic_experiment`

- **Retired:** 2026-05-04
- **Reason:** the original emitter `wormbase_core.heuristic_loop.HeuristicLoop` was deleted in Wave C₁ of the worm-decomposition portfolio (zero production callers at deletion time). The autoresearch concept has been re-expressed via `wormbase_research_loop`'s canonical `experiment_*` PEVR cycle (`emit_experiment_proposed`, `emit_experiment_executed`, `emit_experiment_resolved`).
- **Replacement kind:** concept retired (no replacement). `experiment_*` kinds carry the new-shape autoresearch flow but are not a 1:1 mapping of `heuristic_experiment` payloads — the cycle structure changed.
- **Forwarder:** none — Rule 4 graceful-skip applies. Historical ledger entries with `kind = "heuristic_experiment"` flow through the projection builder's unknown-kind dispatcher and are counted in `ledger_entries_skipped_unknown` telemetry.
- **Schema preservation:** the Pydantic class at `packages/ledger/src/wormbase_ledger/entries.py:391` (`HeuristicExperimentPayload`) carries `DEPRECATED: ClassVar[bool] = True` and remains importable so historical replays construct payloads cleanly. The class stays forever per Rule 1.
- **Contract-test obligations:**
  - **TODO** — add a test (e.g. `packages/ledger/tests/test_deprecated_kinds_not_emitted.py`) that scans the codebase for `kind == "heuristic_experiment"` literal emissions in non-test, non-deprecation-marker code paths. Currently no test pins this invariant; the source-of-truth signal is the `DEPRECATED` class attribute. Tracked as Action Item F.2 of Addendum 2.
  - Existing replay tests in `packages/ledger/tests/` continue to verify historical entries with this kind deserialize without error.
- **Source link:**
  - Wave C₁ deletion: `docs/superpowers/notes/2026-05-03-worm-decomposition-orchestration.md` §VIII row "Heuristic_loop deleted entirely (-312 LOC)"
  - Formal retirement decision: `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` Addendum 2 §C
  - Authorizing plan: `docs/superpowers/plans/2026-05-04-deferred-backlog.md` Block F

---

## Deprecated-but-not-retired kinds

(none yet)

A "deprecated-but-not-retired" kind is one whose emit point is being phased out, but where the new emit path is not yet the default. Use this section when the transition is multi-wave. When emit is fully removed, move the entry to "Retired kinds" above.

---

## Maintenance

- Append new entries; never edit or remove existing ones.
- When a new kind is retired, the wave that does the retirement updates this file in the same commit as the doctrine addendum (or as a Block-F-style follow-on if the addendum was authored separately).
- Cross-link the doctrine addendum that authorized the retirement.
- Cross-link the contract test (or TODO) that guards future re-emit attempts.
