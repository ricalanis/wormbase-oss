# Lake-Side Compounding — L7 Quality-Checks Discovery

**Status:** DESIGN — user-approved 2026-05-30 ("L7 quality-checks next" following L3 first-wave ship)
**Predecessor:** 2026-05-29 L3 shipped (`4f54217`); 2026-05-28 lake-side direction
**Authority:** binding for L7 first wave; cross-tenant template federation deliberately out of scope (deferred to L7 Phase 2)

---

## 1. Motivation

L3 shipped the first lake-side compounding axis (lineage discovery). L7 is the next: **quality-check proposals**. When a new source/table arrives, the worm proposes candidate quality checks (null/uniqueness/freshness/row-count/type-stability/enum) based on schema patterns + naming heuristics + dbt tests + observed statistics. Admins confirm or reject. Confirmed checks become the audit-visible quality baseline.

Cross-tenant template promotion ("a useful check on tenant A → proposed for tenant B's similar tables") is the **L7 Phase 2** capability. It depends on cross-tenant federation infrastructure that isn't built today (engine-per-tenant Phases 3+4 not yet shipped). First wave is **within-tenant proposals only**, with the architecture ready to grow into cross-tenant when the federation work lands.

---

## 2. Scope (first wave only)

**In scope:**
- L7 Compounding factory + 3 inference strategies + Optional-Effect Injection composition (case 10)
- 3 new ledger entry kinds + 1 projection (KIND_REGISTRY 109 → 112)
- Dashboard surface: `/lake/quality`
- Opt-in via `WORMBASE_QUALITY_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred):**
- **Template promotion across tables** (within-tenant): observed once N tables share a check kind → propose it on table N+1. **L7 Phase 2.**
- **Template promotion across tenants**: needs engine-per-tenant Phases 3+4 federation. **L7 Phase 3.**
- **Active check execution**: this wave proposes/confirms checks but doesn't run them. Execution + alerting is a separate axis (could be its own L7b or absorbed into a future observability wave).
- **L1, L2, L4, L5, L6, L8 loops** — same deferred-to-future-wave posture as L3 close-out.

---

## 3. Architecture

### 3.1 The compounding loop (mirrors L3 structurally)

```
source_connected / external_catalog_imported
            │
            ▼
make_quality_discovery_reactivity  ← Compounding axis (7th opt-in)
            │
            ▼
CompositeQualityProposalService    ← Optional-Effect Injection case 10
            ├── SchemaPatternStrategy    [productive on Wave 1 catalog metadata]
            ├── DbtTestsStrategy         [productive on Wave 1 dbt manifest]
            └── HistoricalStatsStrategy  [stubbed today — needs sampler]
            │
            ▼
quality_check_proposed (ledger)
            │
            ▼
projection_quality_checks (state: proposed)
            │
            ▼
/lake/quality (admin Confirm / Reject)
            │
            ├──→ quality_check_confirmed (state: confirmed)
            └──→ quality_check_rejected   (state: rejected)
```

### 3.2 QualityCheckKind enum

A check is one of N kinds with kind-specific config:

```python
QualityCheckKind = Literal[
    "not_null",           # column should not have NULL values
    "unique",             # column values should be unique
    "freshness",          # max age of latest row in a timestamp column
    "row_count_range",    # row count should be in [min, max] range
    "enum_membership",    # column values should be in a known set
    "type_stability",     # column type should not change between snapshots
    "value_range",        # numeric column values should be in [min, max]
]
```

Each kind has a `config` field on the proposal payload (dict, kind-specific shape).

### 3.3 The QualityCheckProposalService Protocol

```python
@dataclass(frozen=True)
class ProposedQualityCheck:
    """A candidate quality check from an inference strategy."""
    check_id: str  # deterministic hash of (table_id, kind, column, normalized_config)
    table_id: str  # "<source_id>.<schema>.<table>"
    column: str | None  # None = whole-table check (e.g. row_count_range)
    kind: QualityCheckKind
    config: dict[str, Any]  # kind-specific (e.g. {"freshness_max_age_hours": 24})
    confidence: float  # 0.0-1.0
    strategy: str  # "schema_pattern" | "dbt_tests" | "historical_stats"
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class QualityCheckProposalService(Protocol):
    name: str
    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
    ) -> list[ProposedQualityCheck]: ...
```

### 3.4 Three strategy impls

#### `SchemaPatternStrategy`

- Reads catalog column metadata (type, nullability, naming)
- Heuristics:
  - Column marked NOT NULL but observed-NULL in stats → not_null check at 0.85
  - Column named `id` or `*_id` with high cardinality → unique check at 0.80
  - Column named `created_at` / `updated_at` / timestamp type → freshness check (default 24h) at 0.70
  - Column with low cardinality (<10 distinct values) → enum_membership at 0.65
- Zero data sampled — fast strategy
- **Productive today** if catalog metadata is sufficient (Wave 1 emits type + nullability)

#### `DbtTestsStrategy`

- Reads dbt manifest entries already mirrored by Wave 1 (`external_lineage_imported` carries dbt model metadata)
- Maps dbt tests to QualityCheckKinds:
  - `not_null` → `not_null` check at 0.99
  - `unique` → `unique` check at 0.99
  - `accepted_values` → `enum_membership` at 0.99
  - `dbt_utils.row_count` → `row_count_range` at 0.95
  - `dbt_utils.test_freshness` → `freshness` at 0.95
- Highest-confidence strategy when manifest is present
- **Productive today** against Wave 1 dbt mirror

#### `HistoricalStatsStrategy`

- Reads sampled column statistics from prior `external_catalog_imported` entries
- Heuristics:
  - Stable mean + p95 row count → row_count_range proposal
  - Stable latest-timestamp drift → freshness threshold proposal
  - Stable distinct-value set → enum_membership proposal
- Requires N≥3 historical snapshots; uses statistical estimators
- **Stubbed today** — Wave 1 catalog mirror doesn't yet emit column-level stats. Same gating as L3's NamingHeuristic/SampleOverlap. Honest-stub posture with `configured · stubbed` badge.

### 3.5 New ledger entry kinds (KIND_REGISTRY 109 → 112)

```python
class QualityCheckProposedPayload(EntryPayload):
    kind: ClassVar[str] = "quality_check_proposed"
    check_id: str
    table_id: str
    column: str | None
    check_kind: QualityCheckKind  # field name "check_kind" to avoid collision with EntryPayload.kind
    config: dict[str, Any]
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]

class QualityCheckConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "quality_check_confirmed"
    check_id: str
    confirmed_by_person_id: str
    notes: str | None = None

class QualityCheckRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "quality_check_rejected"
    check_id: str
    rejected_by_person_id: str
    reason: Literal["false_positive", "low_value", "wrong_threshold", "out_of_scope", "other"]
    notes: str | None = None
```

Note: `check_kind` field disambiguates from `EntryPayload.kind` (the ledger entry kind). All 3 kinds additive per Rule 2.

### 3.6 Projection `projection_quality_checks`

```sql
CREATE TABLE projection_quality_checks (
    company_id UUID NOT NULL,
    check_id VARCHAR NOT NULL,
    table_id VARCHAR NOT NULL,
    column VARCHAR,
    check_kind VARCHAR NOT NULL,
    config JSON NOT NULL,
    confidence FLOAT NOT NULL,
    strategy VARCHAR NOT NULL,
    reasoning TEXT NOT NULL,
    evidence JSON NOT NULL,
    state VARCHAR NOT NULL,  -- "proposed" | "confirmed" | "rejected"
    state_changed_at TIMESTAMP NOT NULL,
    state_changed_by VARCHAR,
    PRIMARY KEY (company_id, check_id)
);

CREATE INDEX ix_projection_quality_checks_state ON projection_quality_checks (company_id, state);
CREATE INDEX ix_projection_quality_checks_table ON projection_quality_checks (company_id, table_id);
CREATE INDEX ix_projection_quality_checks_kind ON projection_quality_checks (company_id, check_kind);
```

Same fold semantics as L3's `projection_lineage_edges`: proposed → INSERT (or UPDATE evidence); confirmed/rejected → UPDATE state.

Migration: **v022**.

### 3.7 Compounding factory

```python
def make_quality_discovery_reactivity(
    *,
    proposal_service: QualityCheckProposalService | None = None,
    catalog_reader: CatalogReader | None = None,
    propose_window_seconds: int = 86400,
) -> Compounding:
    """L7 quality-checks axis.
    
    Optional-Effect Injection (doctrine case 10):
    - proposal_service=None → no-op
    - catalog_reader=None → cannot enumerate target tables → no-op
    """
```

Reactivity ID: `agent_gateway.quality_discovery`. Source predicate: `EntryKind("source_connected") | EntryKind("external_catalog_imported")` (same as L3).

### 3.8 Composite + telemetry

```python
class CompositeQualityProposalService:
    """Optional-Effect Injection case 10."""
    def __init__(
        self,
        *,
        schema_pattern: SchemaPatternStrategy | None = None,
        dbt_tests: DbtTestsStrategy | None = None,
        historical_stats: HistoricalStatsStrategy | None = None,
    ) -> None: ...
    
    def metrics(self) -> dict[str, int]:
        return {
            "quality_inference_invocations": ...,
            "quality_inference_strategy_invocations.schema_pattern": ...,
            "quality_inference_strategy_invocations.dbt_tests": ...,
            "quality_inference_strategy_invocations.historical_stats": ...,
            "quality_inference_checks_proposed": ...,
            "quality_inference_no_op": ...,
        }
```

### 3.9 Env knobs (5 new opt-ins, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_QUALITY_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED` | false | Gates the stubbed historical-stats strategy (no-op until column stats are mirrored) |
| `WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS` | 24 | Default freshness threshold for schema-pattern proposals |
| `WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS` | 86400 | Per-check dedup window |
| `WORMBASE_QUALITY_LOW_CARDINALITY_MAX` | 10 | Max distinct values for enum_membership proposals |

Codebase total opt-in env knobs/escapes: 23 (pre-L7) + 5 = **28**.

---

## 4. Dashboard surfaces

### 4.1 `/lake/quality` — proposed + confirmed checks

Layout:
```
Quality Checks Audit                                       [Filter: All | Proposed | Confirmed | Rejected]
─────────────────────────────────────────────────────────────────────────────────────────────────────

[Strategy Status Banner — 3 badges per L3 pattern]
✓ dbt_tests       — productive (reads Wave 1 dbt manifest mirror)
✓ schema_pattern  — productive (reads Wave 1 catalog column metadata)
⚠ historical_stats — configured · stubbed (needs column-stats mirroring)

Pending Proposals (N total)                                [Group by table | by kind | by strategy]
┌─────────────────────────┬─────────────┬────────┬──────────┬───────────────┬───────────────┐
│ Table                   │ Column      │ Kind   │ Conf.    │ Strategy      │ Actions       │
├─────────────────────────┼─────────────┼────────┼──────────┼───────────────┼───────────────┤
│ snowflake.dbt.dim_users │ user_id     │ unique │ 0.99     │ dbt_tests     │ Confirm | Rej │
│ snowflake.dbt.dim_users │ email       │ not_null│ 0.99    │ dbt_tests     │ Confirm | Rej │
│ snowflake.raw.events    │ created_at  │ freshness│ 0.70   │ schema_pattern│ Confirm | Rej │
│ snowflake.raw.events    │ event_type  │ enum    │ 0.65    │ schema_pattern│ Confirm | Rej │
└─────────────────────────┴─────────────┴────────┴──────────┴───────────────┴───────────────┘

Confirmed Checks (M total) [Inspect] [Export as JSON]
[Table view; click a check to see config + evidence]

Rejected Checks (K total — last 30 days)
[collapsed]
```

Admin Confirm/Reject actions. Reject modal has the 5-reason enum (false_positive / low_value / wrong_threshold / out_of_scope / other).

### 4.2 Re-trigger affordance + window warning

Same static footnote as L3: "Re-proposal is dedup'd via WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS (24h default)."

---

## 5. Optional-Effect Injection compliance (case 10)

`CompositeQualityProposalService` is doctrine case 10. Three independently None-able strategies. Telemetry counters surfaced via `metrics()` per Rule 9.

Cumulative cases now: 1 replay_mode / 2 LazyWebhookSecretResolver / 3 EmbeddingService / 4 QueryOutcomeProjectionReader / 5 TenantRouter / 6 SseStreamTransport / 7 LedgerQuotaTracker / 8 TenantEngineRegistry / 9 LineageInference / **10 QualityProposal**. Pattern unambiguously canonical.

---

## 6. Tests

| Layer | Coverage |
|---|---|
| Ledger payload roundtrip | 3 per kind × 3 = 9 |
| Strategy unit tests | 25-30 (schema/dbt/historical) |
| Composite service | 5-7 |
| Compounding factory integration | 5-7 |
| Projection fold | 6-8 |
| Worm-core wiring + endpoints | 12-15 |
| Dashboard accessor + components | 14-20 |
| End-to-end | 1-2 |

Aggregate ~80-100 new tests.

---

## 7. Deferred — L7 Phase 2

**Template promotion within tenant.** When ≥3 tables in the same tenant have the same `(check_kind, column_naming_pattern)` confirmed, propose the check on table N+1 automatically (with `strategy="template_promotion"` and reasoning that names the source-of-template tables).

This is a 2nd Compounding axis layered on confirmed-checks. It requires a `quality_check_template_emitted` ledger kind OR can be modeled as additional `strategy="template_promotion"` on `quality_check_proposed`. Cleaner: status field (Phase 2 design choice).

Cross-tenant federation is Phase 3 (engine-per-tenant dependent).

---

## 8. Status: DESIGN APPROVED

Implementation plan follows at `docs/superpowers/plans/2026-05-30-l7-quality-checks-impl.md`.
