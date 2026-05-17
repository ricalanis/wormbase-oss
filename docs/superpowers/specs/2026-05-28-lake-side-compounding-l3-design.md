# Lake-Side Compounding — L3 Lineage Discovery + Connector Marketplace Shell

**Status:** DESIGN — user-approved 2026-05-28 ("L3 with Approach C, scope to first wave only")
**Predecessor:** 2026-05-27 polish-pass close-out flagged the lake-side direction as the next architectural arc
**Authority:** binding for the first wave (L3 + marketplace shell); L1–L8 roadmap deliberately out of scope per user's "scope to first wave only"

---

## 1. Motivation

WormBase has 5 query-side compounding axes (templates, data-products, bad-patterns, gap-escalations, recommendations). All operate downstream of the data — they learn from how agents query the lake.

The **lake side** has equivalent compounding potential **upstream** of agent queries. Every new source connection, every catalog drift, every observed dependency teaches the substrate about the customer's data ecosystem. The OpenClaw analog: as channel integration became commodity through a unified protocol + plugin architecture, **data integration should become commodity through unified Connector Protocol + plugin marketplace + compounding learning across every connected source.**

L3 (lineage-discovery) is the first lake-side compounding loop. It builds a confidence-weighted lineage graph from observable signals (column names, sample-value overlap, dbt manifest references) and compounds operator confirmations into a learned inference model.

---

## 2. Scope (first wave only)

**In scope:**
- L3 Compounding factory + 3 inference strategies + Optional-Effect Injection composition
- 3 new ledger entry kinds + 1 projection
- 1 dashboard surface: `/lake/lineage`
- Minimal Connector marketplace shell: `/lake/connectors` (catalog view of existing Connector registry)
- Opt-in via `WORMBASE_LINEAGE_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred to future waves):**
- L1, L2, L4, L5, L6, L7, L8 loops (the other 7 product loops from the polish-pass close-out's lake-side response)
- ML-based inference strategies (Phase 2 of L3 if signal supports it)
- Cross-tenant lineage federation
- Auto-confirmation policies (every proposal stays admin-confirmed; no auto-accept)

---

## 3. Architecture

### 3.1 The compounding loop

```
                       ┌──────────────────────────────────────────┐
                       │  Triggers:                               │
                       │  - source_connected (Connector lifecycle)│
                       │  - external_catalog_imported (Wave 1)    │
                       └──────────────────┬───────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │  LineageInferenceService (3 strategies)  │
                       │  - NamingHeuristicStrategy (substring + edit-distance) │
                       │  - SampleOverlapStrategy (Jaccard on sampled rows)     │
                       │  - DbtManifestStrategy (explicit refs from manifest)   │
                       │  Composed via Optional-Effect Injection: each is None-able│
                       └──────────────────┬───────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │  Compounding axis: make_lineage_discovery_reactivity │
                       │  - source_predicate: above triggers      │
                       │  - quality_filter: source is active + has sample data │
                       │  - gather_fn: pull recent inference candidates per (src_tbl, tgt_tbl) │
                       │  - cluster_fn: group by canonical edge identity │
                       │  - threshold: any cluster with ≥1 candidate │
                       │  - promotion_action: emit lineage_edge_proposed │
                       │  - idempotency: skip if edge already proposed/confirmed/rejected within window │
                       └──────────────────┬───────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │  Ledger entries: lineage_edge_proposed   │
                       │  Projection: projection_lineage_edges    │
                       │  Dashboard: /lake/lineage graph view     │
                       └──────────────────┬───────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │  Admin actions:                          │
                       │  - Confirm → emit lineage_edge_confirmed │
                       │  - Reject → emit lineage_edge_rejected   │
                       │  Both feed the inference model's signal pool │
                       └──────────────────────────────────────────┘
```

### 3.2 The LineageInferenceService Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class LineageInferenceService(Protocol):
    """Infers candidate lineage edges between source tables.
    
    Composable via Optional-Effect Injection: each concrete strategy is
    independently None-able. The composite resolves which strategies fire
    per invocation; missing strategies fall back to None outputs (no edges
    proposed from that source).
    """
    name: str  # "naming_heuristic", "sample_overlap", "dbt_manifest", etc.

    async def infer_edges(
        self,
        *,
        source_table: CatalogTable,
        candidate_targets: list[CatalogTable],
        sample_size: int = 1000,
    ) -> list[InferredEdge]: ...
```

```python
@dataclass(frozen=True)
class InferredEdge:
    src_table_id: str        # "<source_id>.<schema>.<table>"
    src_column: str | None   # None = whole-table edge
    tgt_table_id: str
    tgt_column: str | None
    confidence: float        # 0.0-1.0
    strategy: str            # which strategy emitted this
    reasoning: str           # human-readable, e.g. "column names share 'customer_id' prefix"
    evidence: dict           # structured: e.g. {sample_overlap_ratio: 0.87, sampled_n: 1000}
```

### 3.3 Three strategy impls

#### `NamingHeuristicStrategy`

- Canonicalizes column names (lowercase, strip underscores)
- Edge proposed when src + tgt columns share canonical name AND name is "interesting" (not in stop-list: id / created_at / updated_at / name unless qualifying suffix exists)
- Optional: edit-distance ≤ 2 with shared prefix ≥ 3 chars (`customer_id` ↔ `cust_id`)
- Confidence: 0.6 (name only) to 0.85 (exact + non-stop-list)
- Zero data sampled — fastest strategy

#### `SampleOverlapStrategy`

- Reads N sampled rows from both tables
- Computes Jaccard similarity over each (src_column, tgt_column) pair
- Edge proposed when ratio ≥ 0.5 AND sample is value-rich (non-null cardinality > 10)
- Confidence: 0.55 (Jaccard 0.5) to 0.95 (Jaccard 0.95+)
- Skipped for tables larger than configurable threshold (default 10M rows) to avoid sampling cost
- Most expensive strategy; gated by env knob `WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED=true` (default OFF)

#### `DbtManifestStrategy`

- Reads dbt manifest entries already mirrored by Wave 1's `wormbase-catalog-mirror`
- Edge proposed for every explicit `ref()` / `source()` reference in the manifest
- Confidence: 0.99 (explicit dbt ref is near-ground-truth)
- Fastest + highest-confidence; gated by presence of dbt manifest in catalog

### 3.4 New ledger entry kinds (KIND_REGISTRY 106 → 109)

```python
class LineageEdgeProposedPayload(EntryPayload):
    """Emitted by the L3 Compounding axis when one or more strategies infer an edge."""
    kind: ClassVar[str] = "lineage_edge_proposed"
    edge_id: str  # deterministic hash of (src_table_id, src_column, tgt_table_id, tgt_column)
    src_table_id: str
    src_column: str | None
    tgt_table_id: str
    tgt_column: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict  # JSON-serialized

class LineageEdgeConfirmedPayload(EntryPayload):
    """Operator approves a proposed edge. Becomes part of the confirmed lineage graph."""
    kind: ClassVar[str] = "lineage_edge_confirmed"
    edge_id: str  # matches lineage_edge_proposed
    confirmed_by_person_id: str
    notes: str | None = None

class LineageEdgeRejectedPayload(EntryPayload):
    """Operator rejects a proposed edge. Negative signal for future inference."""
    kind: ClassVar[str] = "lineage_edge_rejected"
    edge_id: str  # matches lineage_edge_proposed
    rejected_by_person_id: str
    reason: Literal["false_positive", "wrong_direction", "low_confidence", "out_of_scope", "other"]
    notes: str | None = None
```

KIND_REGISTRY 106 → **109** (+3 additive per schema-evolution doctrine Rule 2). 11-kind headroom under 120 ceiling.

### 3.5 New projection: `projection_lineage_edges`

```sql
CREATE TABLE projection_lineage_edges (
    company_id UUID NOT NULL,
    edge_id VARCHAR NOT NULL,
    src_table_id VARCHAR NOT NULL,
    src_column VARCHAR,
    tgt_table_id VARCHAR NOT NULL,
    tgt_column VARCHAR,
    confidence FLOAT NOT NULL,
    strategy VARCHAR NOT NULL,
    reasoning TEXT NOT NULL,
    evidence JSON NOT NULL,
    state VARCHAR NOT NULL,  -- "proposed" | "confirmed" | "rejected"
    state_changed_at TIMESTAMP NOT NULL,
    state_changed_by VARCHAR,  -- person_id when state != proposed
    PRIMARY KEY (company_id, edge_id)
);

CREATE INDEX ix_projection_lineage_edges_state ON projection_lineage_edges (company_id, state);
CREATE INDEX ix_projection_lineage_edges_src ON projection_lineage_edges (company_id, src_table_id);
CREATE INDEX ix_projection_lineage_edges_tgt ON projection_lineage_edges (company_id, tgt_table_id);
```

Fold semantics:
- `lineage_edge_proposed` → INSERT (or UPDATE if edge_id exists; keeps the latest proposal's evidence)
- `lineage_edge_confirmed` → UPDATE state = "confirmed"
- `lineage_edge_rejected` → UPDATE state = "rejected"

State transitions:
- proposed → confirmed (admin approval)
- proposed → rejected (admin rejection)
- confirmed → rejected (admin revokes; rare; emits new lineage_edge_rejected)
- rejected → confirmed (admin re-approves; rare; emits new lineage_edge_confirmed; the SECOND proposed entry's evidence supersedes)

Per the forward-only doctrine: every state change is a new entry. No mutation of prior entries.

### 3.6 Compounding factory

```python
def make_lineage_discovery_reactivity(
    *,
    inference_service: LineageInferenceService | None = None,
    days_lookback: int = 7,
    propose_window_seconds: int = 86400,  # don't re-propose same edge within 24h
) -> Compounding:
    """L3 lineage-discovery axis.
    
    Optional-Effect Injection (doctrine case 9):
    - inference_service=None → no edges proposed (reactivity is a no-op pass-through)
    - inference_service=composite → strategies fire per their own None-ability
    """
    ...
```

When `inference_service` is None: the reactivity registers but every fire is a no-op. This preserves byte-identical-default behavior.

When configured: every `source_connected` or `external_catalog_imported` event triggers an inference pass over the source's tables, with results fed to the cluster_fn → promotion_action chain.

### 3.7 Composite service via Optional-Effect Injection

```python
class CompositeLineageInferenceService:
    """Composes multiple strategies; each is independently None-able."""
    def __init__(
        self,
        *,
        naming: NamingHeuristicStrategy | None = None,
        sample_overlap: SampleOverlapStrategy | None = None,
        dbt_manifest: DbtManifestStrategy | None = None,
    ) -> None: ...
    
    async def infer_edges(self, **kwargs) -> list[InferredEdge]:
        """Runs all configured strategies; merges + deduplicates results."""
        ...
```

Per the doctrine, each strategy follows Rule 9 (telemetry distinguishes paths): the composite logs `lineage_inference_strategy_count[strategy_name]` per invocation, surfacing via `metrics()`.

### 3.8 Wire at boot

In `apps/worm-core/src/wormbase_core/agent_gateway_construction.py`:

```python
def build_lineage_inference_service_from_env() -> CompositeLineageInferenceService | None:
    """Builds the composite from env knobs. Returns None when L3 is disabled."""
    if os.getenv("WORMBASE_LINEAGE_DISCOVERY_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return None
    
    return CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),  # always-on when L3 enabled
        sample_overlap=SampleOverlapStrategy() if _is_sample_overlap_enabled() else None,
        dbt_manifest=DbtManifestStrategy(),  # always-on when L3 enabled
    )
```

The factory is consumed by `make_agent_gateway_reactivities()` when assembling the reactivities list.

---

## 4. Dashboard surfaces

### 4.1 `/lake/lineage` — proposed + confirmed edges graph view

Layout:
```
Lineage Audit                                              [Filter: All | Proposed | Confirmed | Rejected]
─────────────────────────────────────────────────────────────────────────────────────────────────────

Pending Proposals (N total)
┌─────────────────────────┬─────────────────────────┬────────┬───────────────────┬──────────────┐
│ Source                  │ Target                  │ Conf.  │ Strategy          │ Actions      │
├─────────────────────────┼─────────────────────────┼────────┼───────────────────┼──────────────┤
│ snowflake.raw.users     │ snowflake.dbt.dim_users │ 0.99   │ dbt_manifest      │ Confirm | Reject │
│ snowflake.raw.orders    │ snowflake.dbt.fact_orders│ 0.95  │ naming_heuristic  │ Confirm | Reject │
│ snowflake.raw.events    │ snowflake.dbt.fact_events│ 0.62  │ sample_overlap    │ Confirm | Reject │
└─────────────────────────┴─────────────────────────┴────────┴───────────────────┴──────────────┘

Confirmed Edges (M total) [Inspect] [Export as JSON]
[graph view: nodes = tables, edges = confirmed lineage; admin can click an edge to revoke]

Rejected Edges (K total — last 30 days)
[collapsed by default; expand to inspect — useful for tuning strategies]
```

Empty states honest. Admin role-gated for Confirm/Reject actions.

### 4.2 `/lake/connectors` — marketplace shell

Layout:
```
Connector Catalog                                          [Add Source...]
─────────────────────────────────────────────────────────────────────────

PRODUCTION
- Slack channel adapter        [Connected ✓]
- WhatsApp channel adapter     [Connected ✓ (preview)]
- Postgres                     [Disconnected]
- Snowflake                    [Connected ✓]
- dbt manifest mirror          [Connected ✓]
- CSV local                    [Always-available]
- S3 CSV                       [Disconnected]
- Stripe                       [Disconnected]
- Salesforce                   [Disconnected]
- HubSpot                      [Disconnected]
- BigQuery                     [Disconnected]
- Google Sheets                [Disconnected]
- HTTP CSV                     [Disconnected]

PREVIEW
- WhatsApp send wire           [Capability: send]

COMING SOON
- Discord
- Microsoft Teams
```

Reads from the existing Connector registry. Each row has:
- Connector kind
- Status (`production` / `preview` / `coming_soon` — per CLAUDE.md §3 conventions)
- Capability set (discover / profile / sample / watch / send / etc.)
- Connection status per tenant (Connected / Disconnected / Awaiting Auth)
- Action button when applicable (Add Source / Reauth / Disconnect)

The "Add Source..." button triggers the existing source-build flows (`drop_and_profile`, `credential_in_dm`, `mentioned_in_conversation`, `dashboard_form`, `kpi_gap_triggered`). For this first-wave shell, only `dashboard_form` is wired from the page UI. The other 4 flows are already wired elsewhere; the catalog page documents them.

### 4.3 Optional: `/trace/lineage_edge/<edge_id>` PEVR-style view

Following the existing `/trace/agent_query/[id]` pattern: per-edge audit chain. Defer to next wave if scope feels tight.

---

## 5. Env knobs

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_LINEAGE_DISCOVERY_ENABLED` | false | Enables L3 reactivity composition |
| `WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED` | false | Enables the expensive SampleOverlapStrategy (requires L3 enabled) |
| `WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS` | 86400 | Per-edge dedup window (don't re-propose within 24h) |
| `WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX` | 2 | Max edit-distance for naming heuristic |
| `WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD` | 0.5 | Min Jaccard ratio for sample strategy |

All default-OFF. Byte-identical pre-L3 behavior preserved.

---

## 6. Optional-Effect Injection compliance

The composite service is doctrine case **9** (the 8 prior cases are documented in Addendum 1 of the doctrine spec). Per Rule 9, telemetry counters surface via `metrics()`:
- `lineage_inference_invocations`: total invocations
- `lineage_inference_strategy_invocations.{strategy_name}`: per-strategy invocations
- `lineage_inference_edges_proposed`: total edges proposed
- `lineage_inference_no_op`: when service was None or all strategies were None

Per Rule 7, all strategies follow the `Optional[T]` shape on the composite's constructor.

---

## 7. Tests

| Layer | Coverage |
|---|---|
| Ledger payload roundtrip | 3 new tests per kind (full / minimal / invalid-enum) |
| Strategy unit tests | 10-15 per strategy (naming match / non-match / edge cases / stop-list) |
| Composite service | 5-7 tests (None-ability per strategy / merge dedup / telemetry counters) |
| Compounding factory integration | 5-7 tests (fires on source_connected / no-op when service=None / idempotency / quality_filter) |
| Projection fold | 4-5 tests (proposed → confirmed; proposed → rejected; idempotent re-fold) |
| Dashboard accessor | 4-6 tests (raw-ledger scan; tenant isolation; state filter) |
| Dashboard page | 4-6 tests (admin gate; empty state; row actions; flash banners) |
| End-to-end | 1-2 tests (source_connected → propose → confirm → projection visible) |

Aggregate ~40-55 new tests.

---

## 8. Implementation plan reference

See `docs/superpowers/plans/2026-05-29-l3-lineage-discovery-impl.md` for task breakdown.

---

## 9. Open questions (resolved in design)

- **Should auto-confirmation happen above a confidence threshold?** No — every edge confirmed by admin. Auto-confirm policy is a future wave (would need its own audit story).
- **Should rejected edges be excluded from future inference?** Yes — the cluster_fn filters out edges whose latest state is "rejected" within the propose window. Re-proposing requires the operator to manually reset.
- **What about edges where source is not yet in catalog?** L3 only fires on `source_connected` + `external_catalog_imported` — the catalog is always present when L3 runs.
- **What about edges across tenants?** Out of scope. L3 is per-tenant; cross-tenant federation is a future wave (would be a multi-tenant routing question on top of engine-per-tenant).

---

## 10. Status: DESIGN APPROVED

User confirmed scope via "L3 with Approach C, scope to first wave only". Implementation plan follows.
