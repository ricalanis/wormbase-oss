# Lake-Side Compounding — L6 Column-Level Governance Classification

**Status:** DESIGN — user-approved 2026-06-06 ("L6 governance next" after L5 close-out)
**Predecessor:** 2026-06-05 L5 shipped (`d17c391`); 2026-06-04 LakeLoopComposite + doctrine review (`0674576`)
**Authority:** binding for L6 first wave

---

## 1. What's distinctive about L6

L6 is the **5th lake-side compounding axis** and the **second cross-axis chain** in the lake-side architecture (after L4→L3). L6 reads L5's confirmed semantic types and proposes column-level classification levels. This closes the L5→L6 chain the PII chip on `/lake/semantic-types` foreshadows.

L6 is also the **2nd axis built on `LakeLoopComposite[T]` from day one** — validates the abstraction further beyond L5's first-day use.

---

## 2. Wave scope (first wave only)

**In scope:**
- L6 Compounding factory built on `LakeLoopComposite[ProposedColumnClassification]` + 3 strategies + Optional-Effect Injection case 13
- 3 new ledger kinds + 1 projection (KIND_REGISTRY 120 → 123; L-axis family 12 → 15 of 30)
- Dashboard surface: `/lake/column-classification`
- Cross-axis read: new `ConfirmedSemanticTypeReader` Protocol mirroring L4's `LineageEdgeReader` shape
- Opt-in via `WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred):**
- L6 Phase 2: auto-confirmation policies (e.g. `pii_ssn` → auto-`regulated` above 0.95 confidence; needs governance review)
- Cross-tenant classification federation
- Custom-tenant-specific classification levels (today's 5-value enum is fixed)
- Domain-pack-driven classification REVOKES (L6 is additive; domain-pack classifications still apply as baseline)

---

## 3. Design choice: new kinds vs reuse existing

The existing `classification_proposed` kind (from the onboarding wave's domain pack picker) is:
- Domain/policy-driven (admin assigns classification defaults per domain)
- Coarse-grained (per-domain or per-resource-type, not per-column)
- No confidence / strategy / reasoning fields (admin-declarative, not agent-inferred)

L6 column-level classification is:
- Agent-inference-driven (proposes from L5 semantic types + naming + domain defaults)
- Fine-grained (per-table-column)
- Carries confidence + strategy + reasoning for SOC-2 audit

**Decision: 3 new `column_classification_*` kinds** following the established L3/L7/L4/L5 template. Cleaner separation; existing kinds untouched; lifecycle audit is per-axis.

Per Addendum 4 §E: L-axis family currently 12 of 30 cap → after L6 = 15 of 30. Well within bounds.

---

## 4. Architecture

### 4.1 Compounding loop

```
external_catalog_imported (or semantic_type_confirmed for cross-axis triggers)
            │
            ▼
gather_fn enumerates columns from triggering snapshot
            │
            ▼
For each column: read L5's projection_semantic_types          ← cross-axis read
WHERE state="confirmed" AND column matches
            │
            ▼
LakeLoopComposite[ProposedColumnClassification]               ← Optional-Effect Injection case 13
            ├── SemanticTypeClassificationStrategy [productive — needs L5 confirmed types]
            ├── NamingPatternClassificationStrategy [productive — regex over column names]
            └── DomainDefaultClassificationStrategy [productive — reads domain pack defaults from existing governance]
            │
            ▼
column_classification_proposed (ledger; carries upstream_semantic_type_id when applicable)
            │
            ▼
projection_column_classifications (state: proposed)
            │
            ▼
/lake/column-classification (admin Confirm / Reject + cross-axis trace nav to L5)
            │
            ├──→ column_classification_confirmed (state: confirmed)
            └──→ column_classification_rejected   (state: rejected)
```

### 4.2 ClassificationLevel enum (Literal in payload)

5-value enum matching existing governance levels (per CLAUDE.md §"Ledger-native governance"):

```python
ClassificationLevel = Literal["public", "internal", "confidential", "pii", "regulated"]
```

These are the canonical 5 levels. No L6-specific additions.

### 4.3 Three strategy impls

**`SemanticTypeClassificationStrategy`** (the cross-axis chain):
- Reads L5's confirmed semantic types via new `ConfirmedSemanticTypeReader` Protocol
- Maps semantic types to classifications:
  - `pii_*` (pii_name / pii_address / pii_ssn / pii_credit_card) → `pii` at 0.95 OR `regulated` if also matches regulated indicators (e.g. credit card → regulated for PCI compliance)
  - `phone_*` / `email` → `pii` at 0.90 (PII even though sometimes-public)
  - `metric_*` → `internal` at 0.70 (default internal unless overridden by domain)
  - `uuid_*`, `business_id` → `internal` at 0.60
  - `country_iso` / `language_iso` / `currency_iso` → `public` at 0.85
- **Productive today** when L5 has confirmed types

**`NamingPatternClassificationStrategy`** (independent of L5):
- Regex over column names directly
- Patterns:
  - `*_secret`, `*_password`, `*_api_key` → `confidential` at 0.95
  - `*_ssn`, `*_tax_id` → `regulated` at 0.95 (catches them even before L5 confirmation)
  - `*_internal_*` → `internal` at 0.80
  - `*_public_*` → `public` at 0.85
- **Productive today** on bare column names from catalog
- Independent of L5 — fires even without L5 enabled

**`DomainDefaultClassificationStrategy`**:
- Reads domain pack's `classification_defaults` (e.g. fintech pack defaults financial-data columns to `regulated`)
- For each column, check if any domain pack rule matches → propose that classification at 0.60 (low confidence; admin should override with specific signals)
- **Productive today** when a domain pack is selected (post-onboarding)

### 4.4 New ledger entry kinds (KIND_REGISTRY 120 → 123)

```python
class ColumnClassificationProposedPayload(EntryPayload):
    kind: ClassVar[str] = "column_classification_proposed"
    classification_id: str  # deterministic hash of (table_id, column, classification_level, strategy)
    table_id: str
    column: str
    classification_level: ClassificationLevel  # 5-value Literal
    upstream_semantic_type_id: str | None  # links back to L5 when strategy="semantic_type"
    confidence: float
    strategy: str  # "semantic_type" | "naming_pattern" | "domain_default"
    reasoning: str
    evidence: dict


class ColumnClassificationConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "column_classification_confirmed"
    classification_id: str
    confirmed_by_person_id: str
    notes: str | None = None


class ColumnClassificationRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "column_classification_rejected"
    classification_id: str
    rejected_by_person_id: str
    reason: Literal["false_positive", "low_value", "wrong_level", "out_of_scope", "other"]
    notes: str | None = None
```

`wrong_level` is L6-specific (replaces L5's `wrong_type`, L4's `already_handled`, L7's `wrong_threshold`).

KIND_REGISTRY 120 → **123**. L-axis family 12 → **15 of 30**.

### 4.5 Projection `projection_column_classifications`

Migration **v025**. Same shape as L3/L7/L4/L5 projections:
- Composite PK `(company_id, classification_id)`
- CHECK on state enum
- Indexes: state / table_id / classification_level

### 4.6 Cross-axis read Protocol

```python
@runtime_checkable
class ConfirmedSemanticTypeReader(Protocol):
    """Cross-axis read: exposes L5's confirmed semantic types to L6.
    
    Second cross-axis Protocol (after L4's LineageEdgeReader). Same shape:
    minimum coupling, async, returns minimal record. Future cross-axis chains
    follow this template.
    """
    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ConfirmedSemanticTypeRecord]: ...
```

`ConfirmedSemanticTypeRecord` carries: `type_id`, `semantic_type`, `confidence`, `strategy` (so L6 can filter on L5 strategy if needed).

### 4.7 Compounding factory + composite via LakeLoopComposite from day one

```python
def make_composite_column_classification_service(
    *,
    semantic_type: SemanticTypeClassificationStrategy | None = None,
    naming_pattern: NamingPatternClassificationStrategy | None = None,
    domain_default: DomainDefaultClassificationStrategy | None = None,
) -> LakeLoopComposite[ProposedColumnClassification]:
    return LakeLoopComposite[ProposedColumnClassification](
        case_name="column_classification_inference",
        strategies={
            "semantic_type": semantic_type,
            "naming_pattern": naming_pattern,
            "domain_default": domain_default,
        },
        propose_method="propose",
        identity_key="classification_id",
        proposals_counter_name="classifications_proposed",
    )
```

~15 LOC. Second-day-one use of the abstraction.

### 4.8 Env knobs (5 new, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED` | false | Gates semantic_type strategy (requires L5 confirmed types) |
| `WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED` | false | Gates domain_default strategy (requires onboarding domain pack selected) |
| `WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS` | 86400 | Per-classification dedup window |
| `WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE` | 0.6 | Below → silent skip |

`naming_pattern` strategy is always-on when master switch is on (no upstream dependency).

---

## 5. Dashboard surface

### `/lake/column-classification`

Mirror L3/L7/L4/L5 layout:

**Strategy status banner** (3 rows; reuse `CapabilityBadges`):
- `semantic_type` — 4 honest postures keyed off L5 confirmed-type count (mirroring L4's L3-dependent posture):
  - L6 off → `disabled`
  - L6 on, L5 off → `configured · L5-disabled`
  - L6 on, L5 on, 0 confirmed types → `configured · awaiting-L5-types`
  - L6 on, L5 on, ≥1 confirmed type → `productive · L5-dependent`
- `naming_pattern` — `productive` when L6 enabled (no upstream dependency)
- `domain_default` — `productive · domain-pack-dependent` when L6 enabled AND a domain pack is selected; `configured · awaiting-domain-pack` otherwise

**Pending Proposals** (the actionable section):
- Group-by: classification_level / table / strategy
- Per-row: table.column + proposed classification_level badge + confidence + strategy badge + Confirm/Reject
- **Cross-axis link**: when `upstream_semantic_type_id` set → renders "view L5 semantic type →" link to `/lake/semantic-types?type_id=<id>`. When NULL → no dead link. Same pattern as L4 → L3.

**Confirmed Classifications** — audit panel; click row for evidence

**Rejected Classifications** — last 30 days, collapsed

**L5-dependency banner** when L6 on + L5 enabled but no confirmed types

**Re-trigger window warning** as static footnote

---

## 6. Optional-Effect Injection compliance (case 13)

`LakeLoopComposite[ProposedColumnClassification]` — backed by the shared abstraction. Telemetry: `column_classification_inference_*` per Rule 9.

Doctrine cases now:
- 9: LakeLoopComposite[InferredEdge] (L3)
- 10: LakeLoopComposite[ProposedQualityCheck] (L7)
- 11: LakeLoopComposite[ProposedImpact] (L4)
- 12: LakeLoopComposite[ProposedSemanticType] (L5)
- 13: **LakeLoopComposite[ProposedColumnClassification] (L6)** — 5th lake-side case

---

## 7. Sub-wave decomposition

Same 4-sub-wave shape as L3/L7/L4/L5:
- **A**: Ledger foundation (3 kinds + v025 projection + fold)
- **B**: Inference service + 3 strategies + composite via `LakeLoopComposite[T]` + `ConfirmedSemanticTypeReader` Protocol
- **C**: Worm-core wiring + concrete `LedgerConfirmedSemanticTypeReader` (mirrors L4's `LedgerLineageEdgeReader`) + 2 admin endpoints
- **D**: Dashboard `/lake/column-classification`

Estimated wall-clock: ~3-4 hours.

---

## 8. Phase 2 candidates (deferred per spec §2)

When L6 has signal:
- **Auto-confirmation policy**: `pii_*` semantic type + naming_pattern agreement + confidence > 0.95 → auto-confirm to `pii` or `regulated`
- **Cross-axis Phase 3 chains**: L6 confirmed `regulated` → L4 elevates schema-change impact severity (touching a regulated column has higher review requirements)
- **Domain-pack governance refinement**: when L6's `domain_default` strategy contradicts the actual confirmations, propose a domain-pack tuning

---

## 9. Implementation plan reference

See `docs/superpowers/plans/2026-06-06-l6-column-classification-impl.md`.

---

## 10. Status: DESIGN APPROVED

User confirmed via "L6 governance next". Implementation begins with Sub-wave A.
