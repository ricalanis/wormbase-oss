# Lake-Side Compounding — L2 Catalog-Drift Triage

**Status:** DESIGN — user-approved 2026-06-09 (hackathon autonomous run; L2 is the 8th and FINAL lake-side axis in this wave generation)
**Predecessor:** 2026-06-08 L1 shipped (`6412b62`); 2026-06-07 L8 shipped (`f791a5d`); 2026-06-06 L6 shipped (`d6944f3`)
**Authority:** binding for L2 first wave; closes the lake-side axis family at 24 of 30

---

## 1. What L2 ships

L2 detects when an **already-connected source's catalog has drifted** from a previous baseline and surfaces the drift to admins for acknowledgement-or-rejection. Five drift cases:

- A new table appears in the catalog
- A table disappears
- A new column appears in an existing table
- A column disappears
- A column's type changes

L2 is the **detection / triage layer**. L4 (schema-evolution-impact) is the **reaction layer** that reads L3 lineage to determine which downstream artifacts break. L2 surfaces the drift event itself; L4 surfaces the consequences. Today there is no peer-axis chain between them — L4 already runs from raw `external_catalog_imported` snapshots; L2's `catalog_drift_proposed` is a **meta** observation about that stream, designed to live alongside (not in front of) L4. A future Phase-2 wave may chain L4 ↦ L2-confirmed-drift for severity elevation, foreshadowed in §10.

L2 is the **8th lake-side axis** and the **5th axis built on `LakeLoopComposite[T]` from day one** (after L5, L6, L8, L1). Composite target ≤14 LOC, continuing the zero-friction streak.

### Naming collision check (passed)

Two existing catalog-event kinds occupy `external_catalog_*` namespace:

| Existing kind | Role |
|---|---|
| `external_catalog_imported` | Catalog-mirror Wave 1: full snapshot ingest from upstream (dbt / Snowflake / Cube / Malloy). Carries `snapshot_hash`, `table_count`, `edge_count`, `metric_count`, `import_mode`. **No per-column data today.** |
| `external_catalog_drift_detected` | Catalog-mirror Wave 1 W5a Reactivity: emitted when periodic re-discover sees `snapshot_hash` change. Carries `old_hash`, `new_hash`, `added_table_ids`, `removed_table_ids`, `changed_table_ids` (tuples; emitters MAY ship empty). **This is the raw structural-change event.** |

L2 does **NOT** duplicate either. L2 introduces a **separate `catalog_drift_*` namespace** (no `external_` prefix) carrying inference-bearing fields (`strategy`, `confidence`, `reasoning`, `evidence`) — analogous to how L1's `source_candidate_*` namespace is the triage prequel to the lifecycle `source_proposed/confirmed/connected/profiled` namespace.

| L2 kind | Role |
|---|---|
| `catalog_drift_proposed` | A strategy detects drift between current `external_catalog_imported` snapshot and previous baseline; carries `drift_kind`, source/table/column refs, strategy, confidence, reasoning |
| `catalog_drift_acknowledged` | Admin signs off; the drift is known/expected (e.g. planned schema migration) |
| `catalog_drift_rejected` | Admin rejects (false positive / inconsequential / out of scope) |

The `catalog_drift_*` namespace is unused elsewhere in `packages/ledger/src/wormbase_ledger/entries.py` (verified by grep). No collision with `external_catalog_imported` / `external_catalog_drift_detected`. No payload-schema changes on the established catalog-mirror kinds.

### Why "proposed/acknowledged/rejected" and not "proposed/confirmed/rejected"

L3/L4/L5/L6/L7/L8 use `*_confirmed` for affirmative state. L1 uses `*_promoted` because the affirmative state triggers a downstream pipeline write. **L2 uses `*_acknowledged`** because the affirmative state is a no-op record — admin acknowledges the drift is known/expected, but nothing else happens automatically. There's no peer-axis being elevated, no downstream pipeline being kicked off. The drift was already observed by the catalog-mirror's W5a Reactivity (`external_catalog_drift_detected`); L2's job is to record the human-in-the-loop disposition.

This is a third naming pattern (after `confirmed` and `promoted`) — sui generis to L2's read-only-disposition semantics. Document in close-out for future axes that share the pattern.

---

## 2. Scope (first wave only)

**In scope:**
- L2 Compounding factory built on `LakeLoopComposite[ProposedCatalogDrift]` + 3 strategies + Optional-Effect Injection case 16
- 3 new ledger kinds + `drift_kind` 5-value enum + `reject_reason` 5-value enum + 1 projection (KIND_REGISTRY 129 → 132; L-axis family 21 → 24 of 30)
- Dashboard surface: `/lake/catalog-drift`
- One new lightweight Reader Protocol: `CatalogSnapshotReader` (reads `external_catalog_imported` entries to reconstruct per-source baseline + current snapshot)
- Concrete `LedgerCatalogSnapshotReader` impl in worm-core
- Opt-in via `WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred to Phase 2):**
- **Per-column catalog ingest** — `external_catalog_imported` payload today does NOT carry per-column lists (only summary counts: `table_count`, `edge_count`, `metric_count`). Column-set and column-type strategies are **honest empty-upstream** until catalog-mirror Wave 2 lands a `catalog_table_imported` per-table payload with columns + types. Wave 1 ships these strategies in `configured · empty-upstream` posture.
- **L4 cross-axis chain** — a future wave can let L4 read L2's `catalog_drift_proposed` to elevate impact severity for admin-acknowledged drifts (versus auto-detected ones). Foreshadowed in §10; **not** wired in Wave 1. Cross-axis chain count stays at 3.
- **Auto-acknowledge policies** — high-confidence drifts from known-safe sources (e.g. an admin-flagged "migration in progress" tag) could auto-acknowledge. Wave 1 routes everything through admin.
- **Drift-grouping** — many simultaneous drifts (e.g. a major migration touching 50 columns) are surfaced as 50 individual rows in Wave 1. Phase 2 could group by `(source_id, migration_window)` for batched acknowledgement.
- **Severity scoring** — Wave 1 confidence is `[0.85, 0.95]` flat per strategy; severity is implicit in `drift_kind` (table_removed ≈ high; column_added ≈ low). Phase 2 could attach explicit severity.
- **Anti-noise window** — L2 omits a `PROPOSE_WINDOW_SECONDS` knob (consistent with L1's simplification); the `drift_id` deterministic hash collides on re-emission, so re-proposing the same drift is idempotent via projection PK.

---

## 3. Architecture

### 3.1 Compounding loop

```
external_catalog_imported (snapshot N)         external_catalog_imported (snapshot N+1)
            │                                              │
            └──────────────────┬───────────────────────────┘
                               ▼
              CatalogSnapshotReader reconstructs:
                 - baseline = most-recent-before-N+1 per source
                 - current  = N+1
                               │
                               ▼
       LakeLoopComposite[ProposedCatalogDrift]        ← Optional-Effect Injection case 16
              ├── TableSetDriftStrategy        [productive day-1 · catalog metadata IS available]
              ├── ColumnSetDriftStrategy       [configured · empty-upstream — needs per-column ingest]
              └── ColumnTypeDriftStrategy      [configured · empty-upstream — needs per-column ingest]
                               │
                               ▼
catalog_drift_proposed (ledger; carries drift_kind, source/table/column refs,
                        strategy, confidence, reasoning, evidence)
                               │
                               ▼
projection_catalog_drifts (state: proposed)
                               │
                               ▼
/lake/catalog-drift (admin Acknowledge / Reject)
                               │
                               ├──→ catalog_drift_acknowledged (state: acknowledged)
                               └──→ catalog_drift_rejected (state: rejected)
```

### 3.2 `drift_kind` enum (5 values — matches the 5 detection cases)

```python
DRIFT_KIND = Literal[
    "table_added",
    "table_removed",
    "column_added",
    "column_removed",
    "column_type_changed",
]
```

Strict `Literal[...]` (unlike L1's free-form `proposed_kind`) — the 5 cases enumerate the observable catalog-metadata change classes; new cases require a doctrine review + Pydantic schema bump, which is appropriate gating for what is otherwise the inference primitive.

### 3.3 Three strategy impls

**`TableSetDriftStrategy`** (productive day-1):
- Diffs current vs baseline table list per `source_id` using `CatalogSnapshotReader.list_tables(source_id, snapshot_hash)`
- Emits `drift_kind=table_added` for entries in current ∖ baseline; emits `drift_kind=table_removed` for baseline ∖ current
- Confidence **0.90** (these are observable directly from catalog metadata; high signal)
- **Productive today** — `external_catalog_imported.added_table_ids` / `removed_table_ids` payload fields already carry per-table diffs; `CatalogSnapshotReader` reconstructs by folding the existing payload tuples. No per-column ingest needed.
- Requires `WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED=true`

**`ColumnSetDriftStrategy`** (configured · empty-upstream until per-column ingest):
- Diffs current vs baseline column list per `(source_id, table_id)` using `CatalogSnapshotReader.list_columns(source_id, table_id, snapshot_hash)`
- Emits `drift_kind=column_added` for columns in current ∖ baseline; emits `drift_kind=column_removed` for baseline ∖ current
- Confidence **0.90** when productive
- **CAVEAT**: today `external_catalog_imported` emits no per-column data (payload carries only `table_count`/`edge_count`/`metric_count` summaries). `CatalogSnapshotReader.list_columns` returns `()` for all tables today. Strategy is **honest stub** — `configured · empty-upstream` until catalog-mirror Wave 2 ships a `catalog_table_imported` per-table payload with `columns: tuple[ColumnSpec, ...]`. Per the L8 Sub-wave C handoff (concern #1) and L4 handoff (same concern), the catalog-mirror per-column extension is foreshadowed but not in scope for L2.
- Until then, this strategy registers in the composite, produces zero proposals, and surfaces `configured · empty-upstream` on the dashboard banner — exactly like L1's `channel_mention` posture before silver-conversations populate.
- Requires `WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED=true`

**`ColumnTypeDriftStrategy`** (configured · empty-upstream until per-column ingest):
- Diffs current vs baseline column **types** per `(source_id, table_id, column)` using `CatalogSnapshotReader.list_columns`
- Emits `drift_kind=column_type_changed` for matching column names with different types (carries before/after types in `evidence`)
- Confidence **0.90** when productive
- Same per-column data dependency caveat as `ColumnSetDriftStrategy`; ships `configured · empty-upstream` posture today
- Requires `WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED=true`

### 3.4 `CatalogSnapshotReader` Protocol (lightweight; NOT a cross-axis chain)

```python
@runtime_checkable
class CatalogSnapshotReader(Protocol):
    """Reads external_catalog_imported entries to reconstruct
    per-source baseline + current snapshot. Reads platform substrate
    (catalog-mirror's projection), not a peer L-axis projection.
    """
    async def list_sources_with_snapshot_pair(
        self, *, company_id: UUID
    ) -> list[SnapshotPair]: ...
    # SnapshotPair = (source_id, baseline_snapshot_hash, current_snapshot_hash)

    async def list_tables(
        self, *, company_id: UUID, source_id: str, snapshot_hash: str
    ) -> tuple[str, ...]: ...

    async def list_columns(
        self, *, company_id: UUID, source_id: str, table_id: str, snapshot_hash: str
    ) -> tuple[ColumnSpec, ...]: ...
    # ColumnSpec = (column_name, column_type) namedtuple
```

**Why this is NOT a cross-axis chain (per L1's doctrine clarification):**
- L1's spec §4.6 established that lightweight Readers reading **first-class platform projections** (sources, KPIs, silver conversations) are NOT cross-axis chains in the L4→L3 / L6→L5 / L8→L5 sense — the producer is substrate, not a compounding loop.
- L2's `CatalogSnapshotReader` reads `external_catalog_imported` — a catalog-mirror Wave 1 substrate event, NOT an L-axis projection. Per the L1 doctrine, this is a **platform-projection reader**, not a peer-axis chain.
- Cross-axis chain count stays at **3** (L4→L3, L6→L5, L8→L5). L2 adds **1 new platform Reader Protocol** (the 4th platform reader after L1's 3).

If/when a future axis reads L2's `projection_catalog_drifts` directly, that **would** be the first cross-axis chain into L2 — see §10's foreshadowed L4-↦-L2-confirmed-drift wave.

### 3.5 New ledger entry kinds (KIND_REGISTRY 129 → 132)

```python
class CatalogDriftProposedPayload(EntryPayload):
    kind: ClassVar[str] = "catalog_drift_proposed"
    drift_id: str  # deterministic hash of (source_id, table_id, column, drift_kind, strategy)
    source_id: str
    table_id: str            # non-empty
    column: str | None = None  # None for table_added/table_removed; set for column_*
    drift_kind: Literal[
        "table_added",
        "table_removed",
        "column_added",
        "column_removed",
        "column_type_changed",
    ]
    before: str | None = None  # prior value (column type for column_type_changed; None for set-membership cases)
    after: str | None = None   # new value (analogous)
    baseline_snapshot_hash: str
    current_snapshot_hash: str
    confidence: float          # [0.0, 1.0]
    strategy: str              # "table_set" | "column_set" | "column_type"
    reasoning: str
    evidence: dict             # strategy-specific: before_tables, after_tables, before_type, after_type, etc.


class CatalogDriftAcknowledgedPayload(EntryPayload):
    kind: ClassVar[str] = "catalog_drift_acknowledged"
    drift_id: str
    acknowledged_by_person_id: str
    notes: str | None = None


class CatalogDriftRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "catalog_drift_rejected"
    drift_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "inconsequential",
        "out_of_scope",
        "duplicate",
        "other",
    ]
    notes: str | None = None
```

`false_positive` is L2's primary reject reason (replaces L1's `duplicate`, L8's `wrong_pairing`, L6's `wrong_level`, L5's `wrong_type`, L4's `already_handled`, L7's `wrong_threshold`) — reflects that the most common reject reason for a drift proposal is "the diff is real but it's not a meaningful drift" (e.g. a renamed-then-rolled-back transient).

KIND_REGISTRY 129 → **132**. L-axis family 21 → **24 of 30** (6 headroom — L2 is the last planned axis; see §11).

### 3.6 Projection `projection_catalog_drifts`

Migration **v028**. Same shape as L3/L7/L4/L5/L6/L8/L1 projections:
- Composite PK `(company_id, drift_id)`
- CHECK on state enum (`proposed` / `acknowledged` / `rejected`)
- CHECK on `drift_kind` enum (5 values)
- Indexes: state / drift_kind / source_id / strategy
- Nullable `column` (NULL for table_added/table_removed), nullable `before`/`after` (NULL for set-membership cases)

Migrations sequence advances `[1..27] → [1..28]`. Forward-only; no schema breakage.

### 3.7 Compounding factory + composite via LakeLoopComposite from day one

```python
def make_composite_catalog_drift_service(
    *,
    table_set: TableSetDriftStrategy | None = None,
    column_set: ColumnSetDriftStrategy | None = None,
    column_type: ColumnTypeDriftStrategy | None = None,
) -> LakeLoopComposite[ProposedCatalogDrift]:
    return LakeLoopComposite[ProposedCatalogDrift](
        case_name="catalog_drift_inference",
        strategies={
            "table_set": table_set,
            "column_set": column_set,
            "column_type": column_type,
        },
        propose_method="propose",
        identity_key=lambda p: p.drift_id,
        proposals_counter_name="catalog_drifts_proposed",
    )
```

Target ≤14 LOC body, continuing the L1-set streak (L1 = 11 LOC, the smallest yet). **Fifth from-day-one consumer** of `LakeLoopComposite[T]` (after L5, L6, L8, L1).

`drift_id` is a deterministic hash of `(source_id, table_id, column, drift_kind, strategy)`. Two strategies proposing the same `(source_id, table_id, column, drift_kind)` collide on **different** ids (kept-separate-by-strategy posture, per L6/L1's pattern). For L2 specifically: `ColumnSetDriftStrategy` proposing `column_added` and `ColumnTypeDriftStrategy` ALSO proposing for the same column won't happen in practice (the strategies cover disjoint drift_kinds), so the separation is mostly defensive.

### 3.8 Env knobs (5 new, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED` | false | Gates TableSetDriftStrategy (productive day-1) |
| `WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED` | false | Gates ColumnSetDriftStrategy (empty-upstream until per-column ingest) |
| `WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED` | false | Gates ColumnTypeDriftStrategy (empty-upstream until per-column ingest) |
| `WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE` | 0.7 | Below → silent skip. **L2's floor is 0.7 (higher than L1's 0.4 and lower than peer-axes' 0.6)** — drift is high-signal (catalog metadata is observable, not inferred), so the floor sits in the upper-half; but we leave headroom below the strategies' default 0.90 confidence so per-strategy lowering doesn't immediately silently-skip. |

Note: L2 omits `PROPOSE_WINDOW_SECONDS` (consistent with L1's simplification). Re-proposing the same drift collides on `drift_id` projection PK; idempotent.

Codebase env-knob total: 67 → **72**.

---

## 4. Dashboard surface

### `/lake/catalog-drift`

Mirror L3/L7/L4/L5/L6/L8/L1 layout:

**Strategy status banner** (3 rows; reuse `CapabilityBadges`):
- `table_set` — 3 honest postures:
  - L2 off → `disabled`
  - L2 on, knob off → `configured · disabled-by-knob`
  - L2 on, knob on → `productive · catalog-metadata-dependent` (always-on once enabled; works against existing `added_table_ids` / `removed_table_ids` payload fields)
- `column_set` — 4 honest postures:
  - L2 off → `disabled`
  - L2 on, knob off → `configured · disabled-by-knob`
  - L2 on, knob on, no per-column data on any snapshot → `configured · empty-upstream · awaiting-catalog-mirror-wave-2`
  - L2 on, knob on, at least one snapshot with per-column data → `productive · per-column-dependent`
- `column_type` — same 4-posture matrix as `column_set` (same upstream dependency)

**Pending Drifts** (the actionable section):
- Group-by: drift_kind / source.table / strategy
- Per-row: `drift_kind` chip (5 colors) + `source_id.table_id[.column]` identifier + strategy badge + confidence + before→after delta (when present) + Acknowledge/Reject buttons
- **Acknowledge action**: writes `catalog_drift_acknowledged` (no downstream pipeline trigger; no cross-axis effect)
- **Reject action**: writes `catalog_drift_rejected` with 5-value reason dropdown including L2-specific `false_positive`

**Drift-kind chip palette (5 colors)**:
- `table_added` — green
- `table_removed` — red
- `column_added` — green-muted
- `column_removed` — red-muted
- `column_type_changed` — amber

Color semantics: green = additive (low concern), red = removal (high concern), amber = type change (consequential). Reuse the `KindChip` component shape from L8 / L6.

**Acknowledged Drifts** — audit panel; collapsed by default; clickable to expand evidence

**Rejected Drifts** — last 30 days, collapsed

**High-density advisory at >200 rows** (concern carried from L8/L1)

**Empty-state honest** when projection returns 0 rows (no FIXTURE fallback; per CLAUDE.md §9)

**Admin nav 29 → 30 tabs**

### Cross-axis link (NONE in Wave 1)

L2's Wave 1 has **zero cross-axis links** to peer L-axes — no upstream Lineage → L2, no downstream L2 → SchemaImpact. Foreshadowed §10 covers Phase 2's potential L4 ↦ L2-confirmed-drift severity-elevation chain, but it ships with no UI affordance today.

---

## 5. Optional-Effect Injection compliance (case 16)

`LakeLoopComposite[ProposedCatalogDrift]` — backed by the shared abstraction. Telemetry: `catalog_drift_inference_*` per Rule 9.

Doctrine cases now:
- 9: LakeLoopComposite[InferredEdge] (L3)
- 10: LakeLoopComposite[ProposedQualityCheck] (L7)
- 11: LakeLoopComposite[ProposedImpact] (L4)
- 12: LakeLoopComposite[ProposedSemanticType] (L5)
- 13: LakeLoopComposite[ProposedColumnClassification] (L6)
- 14: LakeLoopComposite[ProposedEntityStitch] (L8)
- 15: LakeLoopComposite[ProposedSourceCandidate] (L1)
- 16: **LakeLoopComposite[ProposedCatalogDrift] (L2)** — 8th lake-side case, 5th from-day-one consumer

---

## 6. Sub-wave decomposition

Same 4-sub-wave shape as L3/L7/L4/L5/L6/L8/L1:

- **A — Ledger**: 3 kinds (`catalog_drift_proposed/acknowledged/rejected`) + `drift_kind` 5-value enum + 5-value reject_reason enum with L2-specific `false_positive` + v028 `projection_catalog_drifts` + fold + subscription-eligibility registration (~50-55 tests)
- **B — Inference**: new `catalog_drift/` subpackage in `wormbase-agent-gateway`, 3 strategies + `CatalogSnapshotReader` Protocol + `ColumnSpec` + `SnapshotPair` record dataclasses + composite via `LakeLoopComposite[T]` (~35-40 tests)
- **C — Worm-core wiring**: `LedgerCatalogSnapshotReader` impl (folds `external_catalog_imported` + the `added_table_ids`/`removed_table_ids` payload tuples; per-column hooks return `()` honestly today) + 2 admin endpoints (`POST /api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}` and `_reject/{drift_id}`) + 5 env knobs + L2 appended after L1 in `cli.py` (~20-25 tests)
- **D — Dashboard**: `/lake/catalog-drift` + 5-color drift_kind chips + 3-strategy banner with 4-state matrices + admin tabs 29 → 30 (~25-30 tests)

Aggregate target: ~110-140 new tests (mid-range expected).

Estimated wall-clock: ~3-4 hours sequential, or ~1.5 hours with 4 parallel worktrees per `Projects/wormbase/CLAUDE.md` §11.5.

---

## 7. L2 vs `external_catalog_drift_detected` — why both exist

The catalog-mirror's W5a Reactivity emits `external_catalog_drift_detected` as a **raw, deterministic, structural-change record**: snapshot N's hash differs from N+1's hash; here are the added/removed/changed table-ids. This is **substrate**, analogous to how `chat_received` is substrate.

L2 is the **inference-and-disposition layer** over that substrate. Where the W5a Reactivity says "drift happened," L2 says "drift happened, here's the strategy that surfaced it, here's the confidence, here's the per-cell delta, and here's whether the admin acknowledged or rejected it." The shapes differ:

| Field | `external_catalog_drift_detected` | `catalog_drift_proposed` |
|---|---|---|
| Granularity | per-snapshot (one entry per drift event) | per-cell (one entry per added/removed/changed table-or-column) |
| Inference fields | none | strategy + confidence + reasoning + evidence |
| Disposition | none | acknowledged / rejected ledger entries |
| Audit trail | implicit (just the hashes) | explicit (5-state lifecycle: proposed → acknowledged or rejected) |
| Producer | catalog-mirror W5a Reactivity (deterministic) | L2 strategies (over `LakeLoopComposite[T]`) |
| Consumer | future Phase-2 chains | dashboard `/lake/catalog-drift` + admin |

This is the same architectural pattern as L1's `source_candidate_*` vs `source_proposed`: substrate kind + triage prequel/companion kind. The shapes don't overlap; both can coexist forever.

L4 currently consumes neither directly — it folds from `schema_impact_proposed` only, with upstream change classes encoded in `schema_impact_proposed.change_kind`. Phase 2 wiring could chain L4 ↦ L2-acknowledged-drift for severity elevation; see §10.

---

## 8. Phase 2 candidates (deferred per §2)

When L2 has signal:

- **Per-column catalog ingest (catalog-mirror Wave 2)** — adds `catalog_table_imported` per-table payload with `columns: tuple[ColumnSpec, ...]` and `column_types: dict[str, str]`. Unblocks `ColumnSetDriftStrategy` and `ColumnTypeDriftStrategy` to leave empty-upstream posture. This is **THE** prerequisite for L2's full productive state.
- **L4 ↦ L2 cross-axis chain** — `SchemaImpactDiscovery` reads `projection_catalog_drifts` filtered to `state=acknowledged` to elevate impact severity. Acknowledged drift = real upstream change confirmed by an operator; impact severity should jump versus auto-detected drift. This becomes the **4th cross-axis chain**.
- **Auto-acknowledge policies** — drifts from sources tagged `migration_in_progress` (or with a high-confidence operator-provided drift hint) auto-acknowledge. Wave 1 routes everything through admin.
- **Drift-grouping by migration window** — group `(source_id, time_window)` for batched acknowledgement; UX improvement for large migrations touching many columns.
- **Explicit severity scoring** — replace the implicit severity-by-drift-kind heuristic with an explicit `severity ∈ {low, medium, high, critical}` field on `catalog_drift_proposed`. Today inferred client-side from `drift_kind`.
- **Anti-noise window knob** — re-add a `WORMBASE_CATALOG_DRIFT_PROPOSE_WINDOW_SECONDS` if `drift_id` collision turns out to be insufficient (e.g. for transient renamed-then-rolled-back drifts).
- **Severity-tiered notification** — `critical` (e.g. `table_removed` on a domain.owner-claimed source) could post to channel; `low` (e.g. `column_added`) stays dashboard-only.

---

## 9. Implementation plan reference

See `docs/superpowers/plans/2026-06-09-l2-catalog-drift-impl.md`.

---

## 10. L4 ↦ L2 foreshadowed chain (Phase 2 only — NOT in Wave 1 scope)

When `SchemaImpactDiscovery` (L4) reads from `LineageEdgeReader` today, it doesn't have visibility into whether an upstream change was admin-acknowledged or auto-detected. A future wave would:

1. Add a new lightweight `AcknowledgedDriftReader` Protocol in L4's `protocol.py`
2. Impl it in worm-core as `LedgerAcknowledgedDriftReader` folding `catalog_drift_acknowledged` filtered by `state=acknowledged`
3. Inject into `SchemaImpactDiscovery` strategies; if an upstream change matches an acknowledged drift, elevate the impact's confidence floor by +0.05 (operator-confirmed = higher-signal)
4. Render an "operator-confirmed upstream" badge on the `/lake/schema-impact` row when the impact's evidence carries an `acknowledged_drift_id` reference

This would be the **4th cross-axis chain** (L4 → L2-acknowledged-drift). Explicitly **OUT OF SCOPE for L2 Wave 1**; chain count stays at 3.

---

## 11. L-axis family ceiling — L2 IS THE LAST PLANNED AXIS

Per the schema-evolution doctrine Addendum 4 §E:
- L-axis family cap = **30 of KIND_REGISTRY 150 total**
- Pre-L2: 21 of 30 (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 + L8=3 + L1=3)
- Post-L2: **24 of 30 (6 headroom)**

**L2 is the 8th and FINAL planned lake-side axis in this wave generation.** The originally enumerated 8 axes (L1, L2, L3, L4, L5, L6, L7, L8) are now all shipped or in-progress. Future axes (L9, L0, L10+, etc.) **require a doctrine review per Addendum 4 §E before design can begin**:

- 6 headroom in the L-axis family cap
- 18 headroom in the overall KIND_REGISTRY cap (150)
- Mandatory criteria per Addendum 4 §E for adding new L-axes: (a) genuine compounding loop (not a one-off Reactivity); (b) clear `propose → confirm → reject` 3-state lifecycle OR documented justification for an alternate state machine (per L1's `promoted` and L2's `acknowledged` precedents); (c) tested-in-isolation strategy implementations; (d) at least one strategy productive day-1

The post-L2 close-out should include a **L-axis family review** section: are the 7 (and now 8) loops the right decomposition? Are there opportunities for axis consolidation? Is there a missing axis that warranted earlier prioritization? This review feeds the doctrine before any L9 design.

---

## 12. Status: DESIGN APPROVED

User confirmed via hackathon autonomous-run framing ("L2 catalog-drift compounding loop — design spec + implementation plan"). Implementation begins with Sub-wave A.
