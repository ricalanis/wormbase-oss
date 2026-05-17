# Lake-Side Compounding — L8 Cross-Source Entity Stitching

**Status:** DESIGN — user-approved 2026-06-07 (hackathon autonomous run; L8 picked per close-out sequence)
**Predecessor:** 2026-06-06 L6 shipped (`d6944f3`); 2026-06-05 L5 shipped (`d17c391`)
**Authority:** binding for L8 first wave

---

## 1. What L8 ships

When multiple sources connect, L8 proposes that columns in different sources refer to the **same business entity** (e.g. `crm.contacts.email` and `app.users.email_address` both identify the same Person). This is the "entity stitching" axis.

L8 is the **6th lake-side axis** and the **3rd cross-axis chain** in lake-side architecture (reads L5's confirmed semantic types to anchor matches). 3rd axis built on `LakeLoopComposite[T]` from day one.

---

## 2. Scope (first wave only)

**In scope:**
- L8 Compounding factory built on `LakeLoopComposite[ProposedEntityStitch]` + 3 strategies + Optional-Effect Injection case 14
- 3 new ledger kinds + 1 projection (KIND 123→126; L-axis family 15→18 of 30)
- Dashboard surface: `/lake/entity-stitches`
- Cross-axis read: reuse L6's `ConfirmedSemanticTypeReader` (same Protocol; second consumer)
- Opt-in via `WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true`

**Out of scope:**
- Active entity resolution (i.e. SQL JOINs across sources via stitches) — Phase 2 query-layer extension
- Entity hierarchies (e.g. Person → email → phone is one hierarchy, not 3 stitches) — Phase 3
- Federated cross-tenant entity matching — Phase 4 (privacy review needed)

---

## 3. Architecture

```
external_catalog_imported (any source)
    │
    ▼
gather_fn enumerates candidate column pairs (filter: different source_ids)
    │
    ▼
LakeLoopComposite[ProposedEntityStitch]     ← case 14
    ├── NameMatchEntityStrategy        [productive — fuzzy name + L5 semantic type anchor]
    ├── SampleOverlapEntityStrategy    [configured · empty-upstream — needs Sampler]
    └── SchemaShapeEntityStrategy      [productive — column-count + type pattern matching]
    │
    ▼
entity_stitch_proposed (ledger)
    │
    ▼
projection_entity_stitches (state: proposed)
    │
    ▼
/lake/entity-stitches (admin Confirm/Reject + L5 cross-axis trace nav)
```

---

## 4. Ledger kinds (KIND 123→126)

```python
class EntityStitchConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "entity_stitch_confirmed"
    stitch_id: str
    confirmed_by_person_id: str
    notes: str | None = None


class EntityStitchProposedPayload(EntryPayload):
    kind: ClassVar[str] = "entity_stitch_proposed"
    stitch_id: str  # deterministic hash of (src_a, src_b, table_a, table_b, col_a, col_b)
    src_source_id_a: str
    src_table_a: str
    src_column_a: str
    src_source_id_b: str
    src_table_b: str
    src_column_b: str
    upstream_semantic_type_id: str | None = None  # links to L5 when NameMatch used semantic type anchor
    entity_kind: Literal[
        "person", "organization", "transaction", "product",
        "event", "location", "session", "other",
    ]
    confidence: float
    strategy: str  # "name_match" | "sample_overlap" | "schema_shape"
    reasoning: str
    evidence: dict


class EntityStitchRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "entity_stitch_rejected"
    stitch_id: str
    rejected_by_person_id: str
    reason: Literal["false_positive", "low_value", "wrong_pairing", "out_of_scope", "other"]
    notes: str | None = None
```

`wrong_pairing` is L8-specific (replaces L6's `wrong_level`, L5's `wrong_type`, L4's `already_handled`, L7's `wrong_threshold`).

Migration **v026** = `projection_entity_stitches`: composite PK + indexes on (state / src_source_id_a / src_source_id_b / entity_kind).

---

## 5. Three strategies

**`NameMatchEntityStrategy`** (cross-axis to L5):
- Reads L5 confirmed semantic types for both columns via reused `ConfirmedSemanticTypeReader`
- When both columns share confirmed semantic type (e.g. both `email`) → propose stitch at 0.90
- Plus fuzzy name match (Levenshtein normalized) → 0.65-0.80 confidence
- entity_kind inferred from semantic type: `email`/`pii_name` → person; `business_id` → varies; default → other
- Productive today when L5 confirmed types exist

**`SampleOverlapEntityStrategy`**:
- Reuses L7's SamplerProtocol; NoopSampler returns no values → `configured · empty-upstream`
- When sampler is real: Jaccard overlap of sampled values; high overlap (≥0.5) → propose stitch at 0.85
- Wave 1 mirror sampler hook activation prerequisite

**`SchemaShapeEntityStrategy`**:
- Column-count similarity + type-shape similarity + naming convention similarity
- For two tables: if columns are mostly same names + same types → tables represent same entity
- Confidence 0.50-0.75
- Productive on bare catalog metadata; no L5 dep

---

## 6. Env knobs (5; default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED` | false | Gates NameMatch's L5 anchor (otherwise pure fuzzy) |
| `WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED` | false | Gates SampleOverlap (empty-upstream stub) |
| `WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS` | 86400 | Per-stitch dedup window |
| `WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE` | 0.6 | Below → silent skip |

---

## 7. Dashboard `/lake/entity-stitches`

Same shape as L3/L7/L4/L5/L6. Strategy banner with 4-state name_match (L5-dependent if anchor enabled), productive schema_shape, empty-upstream sample_overlap.

Per-row: src_a.col_a ↔ src_b.col_b + entity_kind chip (8 colors) + strategy badge + cross-axis link to L5 when `upstream_semantic_type_id` set.

---

## 8. Optional-Effect Injection case 14

`LakeLoopComposite[ProposedEntityStitch]` — 6th lake case (after L3/L7/L4/L5/L6). 3rd from-day-one consumer of the abstraction.

---

## 9. Sub-wave decomposition

Standard 4-wave (A ledger / B inference + composite / C worm-core wiring / D dashboard).

---

## 10. Status: DESIGN APPROVED — proceed to implementation
