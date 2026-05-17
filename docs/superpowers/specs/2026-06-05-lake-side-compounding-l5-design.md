# Lake-Side Compounding — L5 Sample-Data Fingerprinting

**Status:** DESIGN — user-approved 2026-06-05 ("L5 fingerprinting next" after doctrine-review + LakeLoopAxis close-out)
**Predecessor:** 2026-06-04 doctrine review + LakeLoopComposite shipped (`0674576`); 2026-06-03 L4 shipped (`d80b076`)
**Authority:** binding for L5 first wave

---

## 1. What's distinctive about L5

L5 is the **4th lake-side compounding axis** and the **first one built on top of the LakeLoopComposite[T] abstraction from day one**. This validates whether the abstraction actually saves work for new consumers (vs. retrofitting existing ones).

L5 focuses on **column-level inference** (vs. L3's table-level edges and L4's column-level *impact*). When a table is profiled, L5 computes a fingerprint per column and proposes a semantic type (`email`, `iso_date`, `pii_ssn`, etc.) even when the column name is uninformative.

---

## 2. Wave scope (first wave only)

**In scope:**
- L5 Compounding factory built on `LakeLoopComposite[ProposedSemanticType]` + 3 strategies + Optional-Effect Injection case 12
- 3 new ledger kinds + 1 projection (KIND_REGISTRY 117 → 120; L-axis family 9 → 12 of 30)
- Dashboard surface: `/lake/semantic-types`
- Opt-in via `WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred):**
- L5 Phase 2: feeding L7 + L6 (e.g. inferred `email` auto-proposes `not_null` + `unique` checks via L7; inferred `pii_ssn` auto-proposes `regulated` classification via L6)
- L5 Phase 2: cross-tenant fingerprint compounding (privacy-sensitive; needs governance review)
- Custom-tenant-specific semantic types (Phase 3; needs ontology editor)

---

## 3. Architecture

### 3.1 Compounding loop

```
external_catalog_imported (new snapshot)
            │
            ▼
gather_fn enumerates columns from triggering snapshot
            │
            ▼
LakeLoopComposite[ProposedSemanticType]                   ← case 12 of Optional-Effect Injection
            ├── ColumnNameFingerprintStrategy   [productive — regex over column names]
            ├── ValuePatternFingerprintStrategy [configured · empty-upstream — needs sample values]
            └── DistributionFingerprintStrategy [configured · empty-upstream — needs column stats]
            │
            ▼
semantic_type_proposed (ledger)
            │
            ▼
projection_semantic_types (state: proposed)
            │
            ▼
/lake/semantic-types (admin Confirm / Reject)
            │
            ├──→ semantic_type_confirmed (state: confirmed)
            └──→ semantic_type_rejected   (state: rejected)
```

### 3.2 SemanticType enum (Literal in payload)

```python
SemanticType = Literal[
    # Identity
    "email", "phone_e164", "phone_us",
    # Temporal
    "iso_date", "iso_datetime", "unix_timestamp",
    # Identifiers
    "uuid_v4", "uuid_v7", "business_id",
    # Geo/locale
    "country_iso", "language_iso", "currency_iso",
    # PII (sensitive)
    "pii_name", "pii_address", "pii_ssn", "pii_credit_card",
    # Metric
    "metric_count", "metric_amount", "metric_rate",
    # Catch-all
    "other",
]
```

19 values. Strict Literal in the payload prevents semantic drift; new types require explicit doctrine review.

### 3.3 Three strategy impls

**`ColumnNameFingerprintStrategy`:**
- Productive today on bare column names from `CatalogReader`
- Regex patterns: `r"(?i)^(email|e_mail|email_address)$"` → email at 0.85; `r"(?i).*_email$"` → email at 0.80; `r"(?i)^(uuid|guid|id)$"` → uuid_v4 at 0.65; `r"(?i).*_(ssn|social_security)$"` → pii_ssn at 0.90; etc.
- 30-40 patterns total covering the 19 semantic types
- Stop-list for too-ambiguous names (e.g. `name`, `type`, `value` alone → no proposal)
- Confidence tiers: exact match (0.85+); substring/suffix (0.65-0.80); ambiguous (no proposal)

**`ValuePatternFingerprintStrategy`:**
- Requires sampled column values via the `SamplerProtocol` from L7 (reuse)
- Regex over a window of N=20 sample values; if M/N match a known pattern, propose
- RFC5322 email regex → email at 0.95 (when 18+/20 match); ISO 8601 dates → iso_date at 0.95; UUID v4 → uuid_v4 at 0.95; US ZIP → pii_address at 0.70; etc.
- **Configured · empty-upstream today** — Wave 1 mirror doesn't expose sampler hook yet (same gap L7 SampleOverlap surfaced; NoopSampler is the production stub)

**`DistributionFingerprintStrategy`:**
- Requires column-level statistical snapshots (cardinality, null %, distinct count, mean/p50/p99 for numerics, length distribution for strings)
- Heuristics: low cardinality (< 10) → enum-like; very high cardinality + all-distinct → uuid-like; range [0, 1] + float → metric_rate; positive integers + skewed distribution → metric_count
- **Configured · empty-upstream today** — Wave 1 mirror doesn't emit column-level stats (same gap L4 type_coercion + L7 historical_stats surface)
- Honest stub via `NoopHistoricalStatsReader` from L7 (reuse)

### 3.4 New ledger entry kinds (KIND_REGISTRY 117 → 120)

```python
class SemanticTypeProposedPayload(EntryPayload):
    kind: ClassVar[str] = "semantic_type_proposed"
    type_id: str  # deterministic hash of (table_id, column, semantic_type)
    table_id: str
    column: str
    semantic_type: SemanticType  # Literal (19 values)
    confidence: float
    strategy: str  # "column_name" | "value_pattern" | "distribution"
    reasoning: str
    evidence: dict  # strategy-specific (e.g. {match_count: 18, sample_n: 20, regex: "..."})


class SemanticTypeConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "semantic_type_confirmed"
    type_id: str
    confirmed_by_person_id: str
    notes: str | None = None


class SemanticTypeRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "semantic_type_rejected"
    type_id: str
    rejected_by_person_id: str
    reason: Literal["false_positive", "low_value", "wrong_type", "out_of_scope", "other"]
    notes: str | None = None
```

KIND_REGISTRY 117 → **120**. L-axis family 9 → **12 of 30**.

Per Addendum 4: 30 headroom under new 150 ceiling. Well-sized.

### 3.5 Projection `projection_semantic_types`

Migration **v024**. Schema mirrors L3/L7/L4 projections:
- Composite PK `(company_id, type_id)`
- CHECK on state enum
- Indexes: state / table_id / semantic_type

### 3.6 Compounding factory built on LakeLoopComposite from day one

In `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/semantic_type/composite.py`:

```python
def make_composite_semantic_type_service(
    *,
    column_name: ColumnNameFingerprintStrategy | None = None,
    value_pattern: ValuePatternFingerprintStrategy | None = None,
    distribution: DistributionFingerprintStrategy | None = None,
) -> LakeLoopComposite[ProposedSemanticType]:
    return LakeLoopComposite[ProposedSemanticType](
        case_name="fingerprint_inference",
        strategies={
            "column_name": column_name,
            "value_pattern": value_pattern,
            "distribution": distribution,
        },
        propose_method="propose",
        merge_key=lambda p: p.type_id,
    )
```

**~15 LOC instead of ~250 LOC composite.** This is the LakeLoopComposite[T] validation: L5 is born sharing the abstraction.

### 3.7 Env knobs (5 new, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_FINGERPRINT_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED` | false | Gates value-pattern strategy (needs sampler — empty-upstream today) |
| `WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED` | false | Gates distribution strategy (needs stats — empty-upstream today) |
| `WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS` | 86400 | Per-type dedup window |
| `WORMBASE_FINGERPRINT_MIN_CONFIDENCE` | 0.6 | Below → silent skip |

---

## 4. Dashboard surface

### `/lake/semantic-types`

Mirror L3/L7/L4 layout. Strategy status banner with honest labels:
- `column_name` — `productive` (regex over bare names)
- `value_pattern` — `configured · empty-upstream` (until Wave 1 sampler hook)
- `distribution` — `configured · empty-upstream` (until column stats)

Per-row: table.column + proposed semantic_type (badge) + confidence + strategy badge + Confirm/Reject

5-value reject reason enum: false_positive / low_value / wrong_type / out_of_scope / other (L5-specific — note "wrong_type" replaces L4's "already_handled")

---

## 5. Optional-Effect Injection compliance (case 12)

`LakeLoopComposite[ProposedSemanticType]` — backed by the shared abstraction shipped at `a4a62c2`. Telemetry counters: `fingerprint_inference_*` per Rule 9.

Doctrine cases now:
- 1: replay_mode (bool)
- 2: LazyWebhookSecretResolver
- 3: EmbeddingService
- 4: QueryOutcomeProjectionReader
- 5: TenantRouter
- 6: SseStreamTransport (with capability probe)
- 7: LedgerQuotaTracker
- 8: TenantEngineRegistry
- 9: LakeLoopComposite[InferredEdge] (L3)
- 10: LakeLoopComposite[ProposedQualityCheck] (L7)
- 11: LakeLoopComposite[ProposedImpact] (L4)
- 12: **LakeLoopComposite[ProposedSemanticType] (L5)**

---

## 6. Sub-wave decomposition

Same 4-sub-wave shape as L3/L7/L4:
- **A**: Ledger foundation (3 kinds + v024 projection + fold)
- **B**: Inference service + 3 strategies + factory (using `LakeLoopComposite[T]` from day one)
- **C**: Worm-core wiring (env knobs + reuse L7's `LedgerDbtTestReader` not needed; reuse L7's `NoopHistoricalStatsReader` for distribution; reuse `LedgerCatalogReader` from L3)
- **D**: Dashboard `/lake/semantic-types`

Estimated wall-clock: ~3-4 hours (template fully proven; LakeLoopComposite saves Sub-wave B work).

---

## 7. Cross-axis Phase 2 candidates (deferred)

When L5 proves out, the natural Phase 2 chains:

- **L5 → L7**: confirmed `semantic_type=email` proposes `not_null` + `unique` quality checks
- **L5 → L6**: confirmed `semantic_type=pii_*` proposes `regulated` classification
- **L5 → L4**: schema impact for a confirmed-semantic-type column is higher-severity (e.g. dropping an `email` column has known downstream consequences)

These are 3 cross-axis chains following the L4 → L3 template. Each adds 0 kinds (consumes existing) and demonstrates the lake-side architecture's compounding-across-axes property.

---

## 8. Implementation plan reference

See `docs/superpowers/plans/2026-06-05-l5-fingerprinting-impl.md`.

---

## 9. Status: DESIGN APPROVED

User confirmed via "L5 fingerprinting next". Implementation begins with Sub-wave A.
