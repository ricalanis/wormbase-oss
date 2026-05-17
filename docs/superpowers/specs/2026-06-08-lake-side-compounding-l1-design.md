# Lake-Side Compounding — L1 Source-Candidate Triage

**Status:** DESIGN — user-approved 2026-06-08 (hackathon autonomous run; L1 picked per close-out sequence)
**Predecessor:** 2026-06-07 L8 shipped (`f791a5d`); 2026-06-06 L6 shipped (`d6944f3`); 2026-06-05 L5 shipped (`d17c391`)
**Authority:** binding for L1 first wave

---

## 1. What L1 ships

L1 formalizes the **source-candidate proposal / promotion pipeline** as a compounding loop. The existing 5 source-acquisition trigger flows (drop-and-profile, credential-in-dm, mentioned-in-conversation, dashboard-form, kpi-gap-triggered — see `Projects/wormbase/CLAUDE.md` §"Agentic source-building") emit raw candidate sources into a triage queue; L1's strategies score and propose, admins promote-or-reject, and only **promoted** candidates enter the existing `source_proposed → source_confirmed → source_connected → source_profiled` pipeline.

L1 is the **7th lake-side axis** in lake-side architecture. **4th axis built on `LakeLoopComposite[T]` from day one** (after L5, L6, L8 — zero-friction streak continues). L1 introduces **zero new cross-axis Protocol chains** in the L4→L3 / L6→L5 / L8→L5 sense — its readers consume existing first-class platform projections (`projection_sources`, `projection_kpi_nodes`, `projection_silver_conversations`) rather than peer lake-axis projections. Cross-axis chain count stays at 3.

### Naming collision check (passed)

The existing `source_*` ledger kinds (`source_proposed`, `source_confirmed`, `source_connected`, `source_profiled`) are the **post-promotion** lifecycle of an already-decided source. L1 is the **prequel triage layer**. Naming chosen for L1:

| L1 kind | Role |
|---|---|
| `source_candidate_proposed` | A strategy (or one of the 5 trigger flows) surfaces a candidate; carries kind, identifier, reasoning, confidence |
| `source_candidate_promoted` | Admin signs off; triggers a downstream `source_proposed` (the existing pipeline takes over) |
| `source_candidate_rejected` | Admin rejects; candidate dead-ends with audit |

The `source_candidate_*` namespace is unused elsewhere in `packages/ledger/src/wormbase_ledger/entries.py` (verified). No collision with the established source-pipeline kinds; L1 prequels them without modification.

---

## 2. Scope (first wave only)

**In scope:**
- L1 Compounding factory built on `LakeLoopComposite[ProposedSourceCandidate]` + 3 strategies + Optional-Effect Injection case 15
- 3 new ledger kinds + 1 projection (KIND_REGISTRY 126 → 129; L-axis family 18 → 21 of 30)
- Dashboard surface: `/lake/source-candidates`
- Lightweight readers for cross-projection signal (`ConnectedSourceReader`, `KpiNodeReader`, `SilverConversationReader`) — **NOT** new cross-axis-Protocol chains in the L4/L6/L8 sense (they read existing platform projections, not peer L-axis projections)
- Opt-in via `WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true`
- Tests + operator runbook

**Out of scope (deferred):**
- L1 Phase 2: **auto-promote** policies (e.g. a CSV dropped by `tenancy.admin` at confidence ≥ 0.95 auto-promotes — bypasses admin review). Today everything routes through admin confirm.
- L1 Phase 2: **wire candidate-promoted to source_proposed automatically** (today the promote action writes `source_candidate_promoted` AND triggers the existing source-builder flow synchronously; Phase 2 would decouple via a Reactivity)
- Connector-specific configuration validation at promote-time (today connectors validate during their own `source_proposed → source_confirmed` step)
- **Cross-tenant** candidate federation (a candidate proposed in tenant A is not visible to tenant B)
- **Anti-duplicate** with already-`source_connected` sources beyond the bare-identifier match in `ComplementarityStrategy` (Phase 2: fuzzy match including credentials hash)

---

## 3. Design choice: 3 new kinds vs reuse existing `source_proposed`

The existing `source_proposed` kind already exists with a well-established post-confirm lifecycle. L1 deliberately does **not** reuse it:

- `source_proposed` represents "this source is going to be connected" — already a commitment, just awaiting connector negotiation. The dashboard's `/sources` surface shows these as in-flight connections.
- `source_candidate_proposed` represents "this might become a source if an admin agrees" — a triage candidate, not a commitment.

Conflating them would pollute the source pipeline with low-confidence proposals that may never connect. Keeping them split:

- Preserves audit clarity (triage stage is separate from connection stage)
- Lets L1 carry inference fields (`strategy`, `confidence`, `reasoning`, `evidence`) without bloating the existing source-pipeline payloads
- Mirrors the L3/L7/L4/L5/L6/L8 template precisely (3-kind lifecycle: proposed → confirmed/promoted, proposed → rejected)
- Allows the 5 existing trigger flows to **dual-write**: write a `source_candidate_proposed` (for triage visibility) AND a `source_proposed` (for direct connection, when the trigger flow has high enough confidence). Wave-1 stays strict (trigger flows continue writing `source_proposed` only when the user explicitly confirmed via DM / dashboard; L1 strategies write `source_candidate_proposed`). Phase 2 unifies.

Per Addendum 4 §E: L-axis family currently 18 of 30 cap → after L1 = 21 of 30. 9 headroom remaining (room for L2 + 6 future axes).

---

## 4. Architecture

### 4.1 Compounding loop

```
external_catalog_imported          KPI tree changes      silver_conversations updated
        │                                  │                          │
        └──────────────────┬───────────────┴───────────────┬──────────┘
                           ▼                               ▼
                  gather_fn enumerates trigger snapshots; reads existing
                  projection_sources to filter out already-connected kinds
                           │
                           ▼
LakeLoopComposite[ProposedSourceCandidate]          ← Optional-Effect Injection case 15
        ├── KpiGapAcquisitionStrategy           [productive · KPI-dependent]
        ├── ChannelMentionAcquisitionStrategy   [configured · empty-upstream — needs silver_conversations NLP]
        └── ComplementaritySourceStrategy       [productive — reads projection_sources only]
                           │
                           ▼
source_candidate_proposed (ledger; carries strategy, confidence, evidence)
                           │
                           ▼
projection_source_candidates (state: proposed)
                           │
                           ▼
/lake/source-candidates (admin Promote / Reject; promote triggers downstream
                          source_proposed via existing source_builder)
                           │
                           ├──→ source_candidate_promoted (state: promoted; downstream source_proposed emitted)
                           └──→ source_candidate_rejected (state: rejected)
```

### 4.2 ProposedKind values (free-form, validated against Connector registry)

The `proposed_kind` field carries a **connector kind string** (e.g. `"csv_local"`, `"postgres"`, `"snowflake"`, `"stripe"`, `"hubspot"`, `"mcp:notion"`). Validation:

- At write time the kind is checked against the live `default_registry()` from `wormbase_connectors.registry`. Unknown kinds raise a payload validation error.
- The `Literal[...]` *type* is **not** used (would couple ledger schema evolution to connector add/remove cadence; connectors are additive only and may grow beyond the 10 day-one entries).
- Validation is a runtime guard, not a Pydantic Literal, mirroring how `proposed_identifier` is a free-form string. Per the schema-evolution doctrine (Addendum 4 §B): "Connector registry kinds are NOT KIND_REGISTRY entries; they are configuration."

### 4.3 Three strategy impls

**`KpiGapAcquisitionStrategy`** (reads existing KPI tree):
- Reads `projection_kpi_nodes` via new `KpiNodeReader` lightweight Protocol (NOT a cross-axis chain — KPI tree predates the lake-side axes)
- For each KPI without a backing data source (i.e. no `source_id` reference in its `formula` or upstream lineage): infer the *kind* of source likely needed
  - KPI named like `*_revenue` / `*_sales` / `*_arr` → propose `stripe` or `salesforce` at 0.70
  - KPI named like `*_signups` / `*_users` / `*_dau` → propose `postgres` (app DB) or `mcp:notion` at 0.60
  - KPI named like `*_pipeline` / `*_leads` → propose `hubspot` or `salesforce` at 0.65
  - Fallback to `csv_local` at 0.40 with reasoning "no domain inference; manual file drop suggested"
- `domain_id_hint` carried through from the KPI node's owning domain
- **Productive today** when KPI tree has unbacked nodes; **`configured · awaiting-kpi-tree-population`** when KPI tree is empty
- Requires `WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED=true`

**`ChannelMentionAcquisitionStrategy`** (reads silver_conversations):
- Reads `projection_silver_conversations` (or whichever conversation lake table exists) via `SilverConversationReader` lightweight Protocol
- Scans the last N days of confirmed conversation rows for **data-source mentions** — patterns like `"our snowflake warehouse"`, `"export from Stripe"`, `"the marketing google sheet"`, `"hubspot CRM"`
- Wave-1 uses a **honest regex pattern bank** (~30 patterns covering top connectors); future waves can swap in the existing channel-mention NLP if available
- For each match: propose the mentioned connector kind at 0.55 (low confidence; admin should triage)
- Carries `evidence.message_refs` (list of `chat_received` entry ids) so admin can review the originating message
- **`configured · awaiting-silver-conversations`** when silver lake is empty; **productive** once silver pipeline has signal
- Requires `WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED=true`

**`ComplementaritySourceStrategy`** (reads projection_sources):
- Reads `projection_sources` via `ConnectedSourceReader` lightweight Protocol — enumerates **already-connected** source kinds
- Heuristic: detect **portfolio gaps**:
  - All connected sources have `domain ∈ {sales, revenue}` → propose a marketing source (`hubspot` or `gsheets` at 0.50 with reasoning "no marketing source; sales-heavy portfolio")
  - All connected sources have `domain ∈ {finance, ops}` → propose a product/usage source (`postgres` or `mcp:notion` at 0.50)
  - No file source (no `csv_local` or `s3_csv`) in a tenant with ≥3 connected sources → propose `csv_local` at 0.45 with reasoning "ad-hoc file drops not configured"
- **Productive today** as soon as ≥1 source is connected (it's a static heuristic; no upstream signal dependency)
- Requires `WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED=true`

### 4.4 New ledger entry kinds (KIND_REGISTRY 126 → 129)

```python
class SourceCandidateProposedPayload(EntryPayload):
    kind: ClassVar[str] = "source_candidate_proposed"
    candidate_id: str  # deterministic hash of (proposed_kind, proposed_identifier, strategy)
    proposed_kind: str  # connector registry kind; runtime-validated against default_registry()
    proposed_identifier: str  # e.g. database name, file path hint, OAuth scope, vendor account hint
    domain_id_hint: str | None = None  # domain inference from upstream signal
    confidence: float
    strategy: str  # "kpi_gap" | "channel_mention" | "complementarity"
    reasoning: str
    evidence: dict  # strategy-specific: kpi_node_id, message_refs, portfolio_snapshot, etc.


class SourceCandidatePromotedPayload(EntryPayload):
    kind: ClassVar[str] = "source_candidate_promoted"
    candidate_id: str
    promoted_by_person_id: str
    downstream_source_proposed_id: str | None = None  # the source_proposed entry the promotion triggered
    notes: str | None = None


class SourceCandidateRejectedPayload(EntryPayload):
    kind: ClassVar[str] = "source_candidate_rejected"
    candidate_id: str
    rejected_by_person_id: str
    reason: Literal["duplicate", "low_value", "wrong_kind", "out_of_scope", "other"]
    notes: str | None = None
```

`duplicate` is L1-specific (replaces L8's `wrong_pairing`, L6's `wrong_level`, L5's `wrong_type`, L4's `already_handled`, L7's `wrong_threshold`) — reflects that the most common reject reason is "we already have this source / something equivalent."

KIND_REGISTRY 126 → **129**. L-axis family 18 → **21 of 30** (9 headroom for L2 + future axes).

### 4.5 Projection `projection_source_candidates`

Migration **v027**. Same shape as L3/L7/L4/L5/L6/L8 projections:
- Composite PK `(company_id, candidate_id)`
- CHECK on state enum (`proposed` / `promoted` / `rejected`)
- Indexes: state / proposed_kind / strategy
- Nullable `domain_id_hint` and `downstream_source_proposed_id`

Migrations sequence advances `[1..26] → [1..27]`. Forward-only; no schema breakage.

### 4.6 Lightweight Reader Protocols (NOT cross-axis chains)

L1 introduces **three lightweight Reader Protocols** that mirror the *shape* of the cross-axis Protocols (L4's `LineageEdgeReader`, L6's `ConfirmedSemanticTypeReader`) but **do not constitute** cross-axis chains in the doctrine sense:

```python
@runtime_checkable
class ConnectedSourceReader(Protocol):
    """Reads existing projection_sources for complementarity heuristics."""
    async def list_connected_sources(
        self, *, company_id: UUID
    ) -> list[ConnectedSourceRecord]: ...


@runtime_checkable
class KpiNodeReader(Protocol):
    """Reads existing projection_kpi_nodes for KPI-gap detection."""
    async def list_kpi_nodes_without_source(
        self, *, company_id: UUID
    ) -> list[KpiNodeRecord]: ...


@runtime_checkable
class SilverConversationReader(Protocol):
    """Reads silver_conversations for channel-mention regex scanning."""
    async def list_recent_conversations(
        self, *, company_id: UUID, since_seconds: int = 86400
    ) -> list[SilverConversationRecord]: ...
```

**Why this is NOT a cross-axis chain (doctrine clarification):**
- The L4→L3, L6→L5, L8→L5 chains read **peer lake-axis projections** (`projection_lineage_edges` etc.). Those producer axes own their own L-numbered Compounding loops.
- L1's readers consume **first-class platform projections** (sources, KPI tree, silver conversations) that predate the lake-side axes entirely. The producers aren't compounding loops; they're substrate.
- Doctrine implication: **cross-axis chain count stays at 3** (L4→L3, L6→L5, L8→L5). L1's readers are "platform readers," a separate category. The runbook documents the distinction so future axes don't inflate the chain count by reading e.g. `projection_persons`.

If/when L2 reads L1's `projection_source_candidates` directly, that **would** be a true cross-axis chain (4th) — defer that classification until L2's design.

### 4.7 Compounding factory + composite via LakeLoopComposite from day one

```python
def make_composite_source_candidate_service(
    *,
    kpi_gap: KpiGapAcquisitionStrategy | None = None,
    channel_mention: ChannelMentionAcquisitionStrategy | None = None,
    complementarity: ComplementaritySourceStrategy | None = None,
) -> LakeLoopComposite[ProposedSourceCandidate]:
    return LakeLoopComposite[ProposedSourceCandidate](
        case_name="source_candidate_inference",
        strategies={
            "kpi_gap": kpi_gap,
            "channel_mention": channel_mention,
            "complementarity": complementarity,
        },
        propose_method="propose",
        identity_key=lambda p: p.candidate_id,
        proposals_counter_name="source_candidates_proposed",
    )
```

~14 LOC by design. **Fourth from-day-one consumer** of `LakeLoopComposite[T]` (after L5, L6, L8). Zero-friction streak continuation expected.

Identity key is `candidate_id` — deterministic hash of `(proposed_kind, proposed_identifier, strategy)`. Strategies that propose the same `(kind, identifier)` with different strategies collide on different ids (kept-separate-by-strategy posture, per L6's pattern; admin sees each strategy's evidence independently). Future Phase-2 merge-on-(kind, identifier) is open.

### 4.8 Env knobs (5 new, default-OFF)

| Knob | Default | Effect |
|---|---|---|
| `WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED` | false | Master switch |
| `WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED` | false | Gates KpiGapAcquisitionStrategy (requires KPI tree population) |
| `WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED` | false | Gates ChannelMentionAcquisitionStrategy (requires silver_conversations) |
| `WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED` | false | Gates ComplementaritySourceStrategy (productive once ≥1 source connected) |
| `WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE` | 0.4 | Below → silent skip; L1 floor is lower than other axes (0.6) because candidate-triage is the right place for low-confidence noise |

Note: L1 omits a `PROPOSE_WINDOW_SECONDS` knob — candidate dedup is handled by `candidate_id` collision on the projection PK (re-proposing the same (kind, identifier, strategy) is idempotent). This diverges from L3/L7/L4/L5/L6/L8 which all carry a window knob; documented in the runbook as L1-specific simplification (triage-stage entries are cheap; collision-based idempotence is sufficient).

Codebase env-knob total: 62 → **67**.

---

## 5. Dashboard surface

### `/lake/source-candidates`

Mirror L3/L7/L4/L5/L6/L8 layout:

**Strategy status banner** (3 rows; reuse `CapabilityBadges`):
- `kpi_gap` — 4 honest postures keyed off KPI tree size:
  - L1 off → `disabled`
  - L1 on, KPI knob off → `configured · disabled-by-knob`
  - L1 on, KPI knob on, 0 nodes → `configured · awaiting-kpi-tree-population`
  - L1 on, KPI knob on, ≥1 unbacked node → `productive · KPI-dependent`
- `channel_mention` — 4 honest postures keyed off silver_conversations:
  - L1 off → `disabled`
  - L1 on, channel-mention knob off → `configured · disabled-by-knob`
  - L1 on, knob on, 0 silver rows → `configured · empty-upstream`
  - L1 on, knob on, ≥1 silver row → `productive · silver-dependent`
- `complementarity` — `configured · disabled-by-knob` if knob off, otherwise `productive · portfolio-dependent` (always-on once enabled; uses bare projection_sources)

**Pending Candidates** (the actionable section):
- Group-by: proposed_kind / strategy / domain_id_hint
- Per-row: kind badge + identifier + strategy badge + confidence + reasoning excerpt + Promote/Reject buttons
- **Promote action**: writes `source_candidate_promoted` AND triggers the existing source-builder flow synchronously (emits a downstream `source_proposed` and links the two via `downstream_source_proposed_id`)
- **Connector badge color**: reuse the 10-connector color palette from `/sources/new` (csv_local / postgres / snowflake / bigquery / s3_csv / stripe / salesforce / hubspot / gsheets / mcp:* — `mcp:*` shares one muted color)

**Promoted Candidates** — audit panel; click row to navigate to the resulting `/sources/<source_id>` page when `downstream_source_proposed_id` is set (this **is** a navigable cross-axis link, but it points downstream into the source pipeline, not upstream into a peer L-axis; pattern is sui generis for L1).

**Rejected Candidates** — last 30 days, collapsed

**High-density advisory** at >200 rows (concern carried from L8)

**Empty-state honest** when projection returns 0 rows (no FIXTURE fallback; per CLAUDE.md §9)

**Admin nav 28 → 29 tabs**

### Cross-axis link (downstream, not peer-axis)

When `downstream_source_proposed_id` is set on a `promoted` row, render "view connected source →" linking to the source-builder's `/sources/<id>` (or `/sources` filtered by id). This is NOT a peer-L-axis cross-axis link in the L4→L3 / L6→L5 / L8→L5 sense; it's L1 → source pipeline. Doc this distinction in the spec footer + dashboard tooltip.

---

## 6. Optional-Effect Injection compliance (case 15)

`LakeLoopComposite[ProposedSourceCandidate]` — backed by the shared abstraction. Telemetry: `source_candidate_inference_*` per Rule 9.

Doctrine cases now:
- 9: LakeLoopComposite[InferredEdge] (L3)
- 10: LakeLoopComposite[ProposedQualityCheck] (L7)
- 11: LakeLoopComposite[ProposedImpact] (L4)
- 12: LakeLoopComposite[ProposedSemanticType] (L5)
- 13: LakeLoopComposite[ProposedColumnClassification] (L6)
- 14: LakeLoopComposite[ProposedEntityStitch] (L8)
- 15: **LakeLoopComposite[ProposedSourceCandidate] (L1)** — 7th lake-side case, 4th from-day-one consumer

---

## 7. Sub-wave decomposition

Same 4-sub-wave shape as L3/L7/L4/L5/L6/L8:

- **A — Ledger**: 3 kinds (`source_candidate_proposed/promoted/rejected`) + 5-value reject reason with L1-specific `duplicate` + v027 projection_source_candidates + fold (~50-55 tests)
- **B — Inference**: new `source_candidate/` subpackage in `wormbase-agent-gateway`, 3 strategies + 3 lightweight Reader Protocols + composite via `LakeLoopComposite[T]` (~40-45 tests)
- **C — Worm-core wiring**: 3 concrete reader impls (`LedgerConnectedSourceReader`, `LedgerKpiNodeReader`, `LedgerSilverConversationReader`) + 2 admin endpoints (`source_candidates_promote/reject`) + 5 env knobs + L1 appended after L8 in `cli.py` (~25-30 tests)
- **D — Dashboard**: `/lake/source-candidates` + strategy banner + admin tabs 28→29 + downstream link to `/sources/<id>` + promote action wired through source-builder (~50-55 tests)

Aggregate target: ~110-140 new tests (mid-range expected).

Estimated wall-clock: ~3-4 hours sequential, or ~1.5 hours with 4 parallel subagents per the 11.5 worktree pattern.

---

## 8. Phase 2 candidates (deferred per spec §2)

When L1 has signal:
- **Auto-promote policies**: candidates from `tenancy.admin`-initiated DM drops + confidence ≥ 0.95 + matching previously-promoted pattern → auto-promote without admin click (writes a `source_candidate_promoted` with `promoted_by_person_id` = the auto-promote actor)
- **Reactivity-driven downstream wire**: today the dashboard's promote action synchronously emits the downstream `source_proposed`; Phase 2 decouples via a `SourceCandidatePromoted → SourceProposed` Reactivity (mirrors the agent-gateway's `OutcomeToTemplatePromotion`)
- **Fuzzy-duplicate detection**: L1's reject reason `duplicate` is admin-driven today; Phase 2 adds a fuzzy match at propose-time against existing `projection_sources` (credentials hash, identifier similarity)
- **Per-domain candidate caps**: if a domain has 5+ pending candidates, suppress new proposals until admin triages (avoids notification fatigue)
- **L2 → L1 cross-axis chain**: if L2 (next axis; lake-side axis #8) reads L1's `projection_source_candidates` directly, it becomes the **4th cross-axis chain** and the first to chain *into* L1

---

## 9. Implementation plan reference

See `docs/superpowers/plans/2026-06-08-l1-source-candidates-impl.md`.

---

## 10. Status: DESIGN APPROVED

User confirmed via hackathon autonomous-run framing ("L1 source-onboarding compounding loop — design spec + implementation plan"). Implementation begins with Sub-wave A.
