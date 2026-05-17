# Lake-Side Compounding — L4 Schema-Evolution Impact

**Status:** DESIGN — user-approved 2026-06-02 ("L4 schema-evolution-impact next" after L7 close-out)
**Predecessor:** 2026-06-01 L7 shipped (`7b31750`); 2026-05-29 L3 shipped (`4f54217`)
**Authority:** binding for L4 first wave

---

## 1. What's novel about L4

L4 is the first lake-side compounding axis that **consumes another axis's output**. When a column changes in an upstream source, L4 reads L3's confirmed lineage edges to identify downstream tables/columns affected, and proposes impact entries for admin review.

This validates a key architectural property: **lake-side loops chain.** Future loops can consume any other loop's confirmed-state output without coupling to the producer's implementation.

---

## 2. Wave scope (first wave only)

**In scope:**
- L4 Compounding factory + 3 inference strategies + Optional-Effect Injection (case 11)
- 3 new ledger kinds + 1 projection (KIND_REGISTRY 114 → 117)
- Dashboard surface: `/lake/schema-impact`
- Opt-in via `WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred per "first wave only" precedent):**
- L4 Phase 2: auto-confirmation policies above confidence threshold
- Cross-tenant federation
- "Impact remediation" workflows (suggested migrations / SQL patches)
- LakeLoopAxis<T> DRY refactor (assessed after L4 ships; trigger: this is the 3rd lake-loop instance)

---

## 3. Architecture

### 3.1 The compounding loop (mirrors L3/L7 + cross-axis read)

```
external_catalog_imported (new snapshot for source X)
            │
            ▼
gather_fn computes delta vs prior snapshot for source X     ← inline column diff
            │
            ▼
For each changed column: read L3's projection_lineage_edges  ← cross-axis consumption
WHERE state = "confirmed" AND src_column = <changed_column>
            │
            ▼
CompositeSchemaImpactService                                 ← Optional-Effect Injection case 11
            ├── LineageEdgeImpactStrategy    [productive — reads L3's confirmed edges]
            ├── DbtTestImpactStrategy        [configured · empty-upstream — Wave 1 dbt tests gap]
            └── TypeCoercionImpactStrategy   [productive — reasoning over column types]
            │
            ▼
schema_impact_proposed (ledger)
            │
            ▼
projection_schema_impacts (state: proposed)
            │
            ▼
/lake/schema-impact (admin Confirm / Reject)
            │
            ├──→ schema_impact_confirmed (state: confirmed)
            └──→ schema_impact_rejected   (state: rejected)
```

### 3.2 Triggering on `external_catalog_imported` with inline delta

Source predicate: `EntryKind("external_catalog_imported")`.

Gather_fn semantics:
1. Read the triggering entry's `source_id` and `tables` snapshot
2. Read the *prior* `external_catalog_imported` for the same source (if any)
3. Compute column-level delta: `column_added` / `column_dropped` / `column_type_changed`
4. For each changed column: cross-query L3's `projection_lineage_edges` for confirmed edges where `src_column = changed_column`

**No new entry kinds for the trigger.** L4 reuses existing `external_catalog_imported` from Wave 1.

### 3.3 Three strategy impls

**`LineageEdgeImpactStrategy`:**
- For each `(changed_column, downstream_table.column)` pair from L3's confirmed edges
- Proposes `schema_impact_proposed` with:
  - kind: `column_dropped` → `tgt_column_orphaned` at 0.90 (high confidence — drop is unambiguous)
  - kind: `column_type_changed` → `tgt_column_type_mismatch` at 0.85 (downstream may need coercion)
  - kind: `column_added` → `tgt_column_unaware` at 0.50 (lower confidence — addition rarely breaks anything)
- Confidence scales by source edge's strategy: dbt_manifest edges (0.99) → 0.99 × impact factor; naming_heuristic edges (0.85) → 0.85 × impact factor
- **Productive today** when L3 is enabled and has confirmed edges

**`DbtTestImpactStrategy`:**
- Read existing dbt tests on the changed column (via `LedgerDbtTestReader` from L7)
- Propose `dbt_test_breakage` impact at confidence per test type
- **Configured · empty-upstream today** — Wave 1 mirror doesn't emit dbt tests yet (same gap L7 surfaced)

**`TypeCoercionImpactStrategy`:**
- For `column_type_changed` events, reason over the type transition (varchar→int / int→varchar / nullable→not_null / etc.)
- Propose `type_coercion_required` at 0.70 with the suggested coercion
- **Productive today** — works on bare column type metadata

### 3.4 New ledger entry kinds (KIND_REGISTRY 114 → 117)

```python
class SchemaImpactProposedPayload(EntryPayload):
    kind: ClassVar[str] = "schema_impact_proposed"
    impact_id: str  # deterministic hash of (source_id, src_table, src_column, change_kind, tgt_table_id, tgt_column)
    source_id: str
    src_table: str
    src_column: str
    change_kind: Literal["column_added", "column_dropped", "column_type_changed"]
    impact_kind: Literal[
        "tgt_column_orphaned",      # column dropped, downstream references it
        "tgt_column_type_mismatch", # type changed, downstream may need coercion
        "tgt_column_unaware",       # column added, downstream may want to consume
        "dbt_test_breakage",        # existing dbt test will fail
        "type_coercion_required",   # downstream computation needs coercion
    ]
    tgt_table_id: str
    tgt_column: str
    upstream_lineage_edge_id: str | None  # links back to L3 edge that produced this impact (NULL for non-edge-driven strategies)
    confidence: float
    strategy: str  # "lineage_edge" | "dbt_test" | "type_coercion"
    reasoning: str
    evidence: dict


class SchemaImpactConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "schema_impact_confirmed"
    impact_id: str
    confirmed_by_person_id: str
    notes: str | None = None


class SchemaImpactRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "schema_impact_rejected"
    impact_id: str
    rejected_by_person_id: str
    reason: Literal["false_positive", "already_handled", "low_value", "out_of_scope", "other"]
    notes: str | None = None
```

KIND_REGISTRY 114 → **117**. **Headroom: 3 kinds before the Wave F Addendum 1 ceiling at 120.** This is the load-bearing concern for L4 — see §9.

### 3.5 Projection `projection_schema_impacts`

Same shape as `projection_lineage_edges` + `projection_quality_checks`. Migration **v023**.

Schema:
- Composite PK `(company_id, impact_id)`
- CHECK on state enum
- 4 indexes: state / source_id / tgt_table_id / change_kind

### 3.6 Compounding factory

```python
def make_schema_impact_discovery_reactivity(
    *,
    impact_service: SchemaImpactService | None = None,
    catalog_reader: CatalogReader | None = None,
    lineage_edge_reader: LineageEdgeReader | None = None,  # NEW: cross-axis read from L3
    propose_window_seconds: int = 86400,
) -> Compounding:
    """L4 schema-evolution-impact axis.
    
    Optional-Effect Injection (doctrine case 11):
    - impact_service=None → no-op
    - catalog_reader=None → no-op
    - lineage_edge_reader=None → LineageEdgeImpactStrategy gracefully no-ops (still
      runs TypeCoercionImpactStrategy which doesn't need L3)
    """
```

The third `lineage_edge_reader` injection is the **cross-axis read** that's new. It exposes L3's projection.

### 3.7 Env knobs (5 new opt-ins, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED` | false | Gates DbtTestImpactStrategy (stubbed until Wave 1 emits) |
| `WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS` | 86400 | Per-impact dedup window |
| `WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE` | 0.5 | Minimum confidence for proposals (below → silently skip) |
| `WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE` | false | Whether to include naming-heuristic lineage edges (lower confidence than dbt edges); default off — only dbt-confirmed edges feed L4 by default |

Total opt-in env knobs: 37 (post-L7) + 5 = **42**.

---

## 4. Dashboard surface

### `/lake/schema-impact`

Mirror L3/L7 layout:

**Strategy status banner** (3 rows; reuses `CapabilityBadges`):
- `lineage_edge` — `productive · L3-dependent` when L3 enabled + has confirmed edges
- `dbt_test` — `configured · empty-upstream` (Wave 1 gap)
- `type_coercion` — `productive` (works on bare type metadata)

**Pending Proposals** (the actionable section):
- Group-by: source / impact_kind / target_table / strategy
- Per-row: change description + downstream table + impact_kind + confidence + Confirm/Reject

**Confirmed Impacts** — audit panel; click to see the upstream lineage edge

**Rejected Impacts** — last 30 days; collapsed

**Cross-axis link surfacing:** every row links back to the L3 lineage edge that produced the impact (when applicable). Admin can click through to `/lake/lineage` to inspect the source.

---

## 5. Optional-Effect Injection compliance (case 11)

`CompositeSchemaImpactService` is the 11th case. Three independently None-able strategies. Telemetry via `metrics()`.

Doctrine cases summary:
- 1: replay_mode (bool)
- 2: LazyWebhookSecretResolver
- 3: EmbeddingService
- 4: QueryOutcomeProjectionReader
- 5: TenantRouter
- 6: SseStreamTransport (with capability probe)
- 7: LedgerQuotaTracker
- 8: TenantEngineRegistry
- 9: CompositeLineageInferenceService (L3)
- 10: CompositeQualityProposalService (L7)
- 11: **CompositeSchemaImpactService (L4)**

---

## 6. Sub-wave decomposition

Same shape as L3/L7:

- **Sub-wave A**: Ledger foundation (3 kinds + v023 projection + fold)
- **Sub-wave B**: Inference service + 3 strategies + Compounding factory + LineageEdgeReader Protocol
- **Sub-wave C**: Worm-core wiring (env knobs + LedgerLineageEdgeReader impl + 2 admin endpoints + projection fold runner — likely no-op like L7 C)
- **Sub-wave D**: Dashboard `/lake/schema-impact`

Estimated wall-clock: ~3-4 hours (template proven; L4 adds the cross-axis read complexity which is bounded).

---

## 7. KIND_REGISTRY ceiling concern

At KIND_REGISTRY 117 post-L4, we have **3 kinds remaining** before the Wave F Addendum 1 ceiling at 120. The next 1-2 lake-side loops (L5/L6/L8) would consume that headroom and trigger the doctrine's freeze-pause review.

**This is fine** — the ceiling exists precisely to force a review when the registry gets large. After L4 ships, the next maintenance arc should include:
1. A schema-evolution doctrine review (any kinds retire-able? any kinds consolidate-able into status fields?)
2. Either raise the ceiling (with rationale) OR shrink the registry before adding more kinds

**This is not a blocker for L4.** Document it in the close-out as the next arc's first deliverable.

---

## 8. Implementation plan reference

See `docs/superpowers/plans/2026-06-02-l4-schema-impact-impl.md` for sub-wave decomposition.

---

## 9. Status: DESIGN APPROVED

User confirmed via "L4 schema-evolution-impact next". Implementation begins with Sub-wave A.
