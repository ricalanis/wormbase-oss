# WormBase Delivery Log

> The project's release register — every meaningful ship from project start to current.
> Each entry captures what landed, why, what changed in numbers, and what carried forward.

## How to read this log

Entries are grouped into phases reflecting the project's natural arc — substrate first, then product surfaces, then a long compounding-axis program, then cross-axis polish. Within a phase, entries run chronologically. Each entry pins its commit SHA, links to its spec when one exists, and reports the test delta against the prior commit's suite. Numbers belong in the structured fields; prose describes intent. Phase introductions provide one-paragraph framings; the entries themselves are the primary record.

For internal architecture, see `ARCHITECTURE.md`. For day-to-day operator guidance, see `DEVELOPERS.md`. For the autonomous-maintenance playbook the late phases relied on, see `AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`.

---

## Phase 1 — Substrate (2026-05-04 → 2026-05-13)

The first month established the ledger substrate, the identity tracker, the catalog mirror, and the agent gateway control plane. By the end of this phase the codebase had the architectural pieces in place: an append-only ledger as the source of truth, a five-wire boot path, a multi-tool MCP server, and a six-beat ASML demo arc passing end-to-end.

### 2026-05-04 — Identity tracker greenfield reactivities

**Commit:** `bf5da68`
**Spec:** `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`
**Tests:** +5 (factory + 3 e2e + 2 projection)
**What shipped:** Two new identity-tracker reactivities (PositionInferenceReactivity, ResourceOwnershipReactivity) wired end-to-end through the canonical propose → execute → verify → resolve cycle, with the projection-roles table gaining a resource facet for downstream consumers.
**Why:** Closes the identity worm's first compounding loop — chat signal now produces durable Person and ResourceRole proposals without manual annotation.

### 2026-05-11 — Catalog-mirror Wave 1

**Commit:** `306dd29`
**Spec:** `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`
**Tests:** +101 (KIND_REGISTRY 83 → 88; suite 845 passed)
**What shipped:** New `wormbase-catalog-mirror` package with `CatalogSource` Protocol plus two reference implementations (dbt manifest, Snowflake native), five new ledger entry kinds for external catalog ingest, and the fifth boot wire (`wire_catalog_for_install`).
**Why:** Establishes the data plane — external catalogs now flow into the lake as ledger truth, providing the substrate every downstream lake-side strategy reads from.
**Carry-forwards:** SQL-vs-Python migration runner reconciliation; Snowflake OAuth path untested live; KIND_REGISTRY freeze-pause review required before Wave 2.

### 2026-05-12 — Agent gateway (semantic layer Wave 2)

**Commit:** `519bcb0`
**Spec:** `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md` §10 Wave 2
**Tests:** +254 (KIND_REGISTRY 88 → 96; suite 1099 passed)
**What shipped:** New `wormbase-agent-gateway` package introducing the institutional-AI control plane — `CredentialBroker`, `QuerySpec`, and `Router` extension Protocols; eight new ledger entry kinds across agent identity, grants, queries, and the §4.5 compounding query layer; FastMCP server with nine tools; the `OutcomeToTemplatePromotion` reactivity that autonomously promotes high-quality query clusters into durable templates.
**Why:** This is the institutional-AI moat made architectural. Agents register, are granted access, and execute queries — all through the ledger — while the compounding loop turns ad-hoc successful queries into reusable templates without human intervention.
**Carry-forwards:** MCP HTTP transport for hosted multi-tenant; `record_outcome` payload marker; LLM-based reflective rewrite for `suggest_correction`; embedding-based clustering for template promotion.

### 2026-05-12 — Dashboard + ASML demo arc (semantic layer Wave 3)

**Commit:** `b8e44a1`
**Spec:** `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md` §10 Wave 3
**Tests:** +1275 (KIND_REGISTRY unchanged at 96; suite 2374 passed)
**What shipped:** Six dashboard surfaces (`/lake/catalog`, `/people/agents`, `/trace/agent_query/[id]` with recursive-CTE PEVR chain rendering, `/lake/query-improvement`, `/lake/metrics-proposed`, `/lake/governance`); projection builders for twelve Wave 1+2 entry kinds; `source_mode` formalization in lake-maintainer; the six-beat ASML hermetic integration test (1.73s) exercising real ledger writes, projection builds, and governance gate enforcement.
**Why:** The substrate is now legible end-to-end as a product. The demo arc gives a publishable narrative the project's institutional-AI claims can be measured against.

### 2026-05-13 — Journey polish bundle (Wave 3.2)

**Commit:** `2a3bfa5`
**Tests:** +132 (KIND_REGISTRY unchanged at 96; MCP tools 9 → 17)
**What shipped:** Five customer-journey gaps closed: agent-registration form at `/people/agents/new`, eight new MCP tools doubling the surface (`decisions.*`, `processes.*`, `data_products.*`), WhatsApp production-graduation honesty banner, Tier 3 onboarding gains a dbt/Snowflake catalog-import branch, and `QueryOutcomeToDataProductReactivity` autonomously promoting high-quality outcomes into data products.
**Why:** The substrate was whole but the customer's path through it had visible holes. This bundle wires the surfaces so an external agent can read the worm's institutional knowledge graph end-to-end.

### 2026-05-13 — Production hardening (v1.1)

**Commit:** (this close-out)
**Tests:** +237 (suite 2743 passed)
**What shipped:** Four worm-core write endpoints take the stub server-actions live (`register_agent`, `import_dbt_catalog`, `import_snowflake_catalog`, `promote_semantic_gap`); `LedgerDecisionReader` and `LedgerProcessMapReader` back the `decisions.*` / `processes.*` MCP tools with raw-ledger queries; `DataProductConsumedPayload` gains an additive `consumed_by_agent_id` field; governance unification composes four inline + four stateful gates in the MCP path.
**Why:** v1.0 left dashboard server actions hitting honest-stub error paths and MCP tools backed by in-memory data. v1.1 closes those gaps at the back-end without expanding surface area or kind count.

### 2026-05-14 — Production wire-ups (v1.2)

**Commit:** `91cc7fb`
**Tests:** +11 (suite 3213 passed)
**What shipped:** `CredentialBroker` wired into gateway construction (env + vault knobs); stateful gate bundle lifted from chat-presence into `GatewayDeps`; `LedgerDataProductReader` replaces `_EmptyDataProductReader`; `Ledger.get_entry(id)` direct-lookup primitive replaces O(N) iteration; `ExternalMetricImportedPayload` canonicalizes promotion provenance as first-class additive fields.
**Why:** Closes the five v1.1 follow-ups in one wave — the production gateway construction site now lifts the broker and stateful gates, every MCP tool family has a real ledger-backed reader, and promotion provenance lives on the typed schema rather than `execute()` kwargs.

### 2026-05-14 — Production operationalization (v1.3)

**Commit:** `d0ede81`
**Spec:** `docs/superpowers/specs/2026-05-14-projection-materialization-doctrine.md`
**Tests:** +35 (suite 3248 passed)
**What shipped:** `LedgerAgentGrantReader` wires `AgentAccessGate.grant_lookup` to real granted scopes; MCP listener now binds at boot (stdio default; streamable-HTTP opt-in via env); broker default flips from `env` to `vault`; projection-materialization doctrine documented governing when and in what order raw-ledger readers promote to projection-backed.
**Why:** The four remaining deploy-readiness follow-ups: every MCP call now respects real granted scopes, the listener boots at install time, the secret broker matches production posture, and the projection-promotion question has a written doctrine instead of an implicit "we'll figure it out later."

---

## Phase 2 — Compounding primitive & agent-as-teammate (2026-05-15 → 2026-05-20)

With the substrate stable, attention turned to the compounding layer itself — first extracting the `Compounding` primitive so new axes shipped at low cost, then proving it across new axes, then giving agents an outbound event channel.

### 2026-05-15 — Compounding axes (v2.B Phase 2)

**Commit:** `a976b88`
**Tests:** +56 (KIND_REGISTRY 96 → 99)
**What shipped:** Three new compounding axes built on the Phase 1 `Compounding` primitive — `bad_pattern_proposed` (repeated failures cluster into known-bad patterns), `semantic_gap_escalated` (unresolved gaps escalate after 7d), `data_product_recommended` (consumed clusters surface recommendations). `Compounding.idempotency_filter` becomes a first-class parameter.
**Why:** The §4.5 compounding query layer now has five named axes. The Phase 1 extraction is validated by proving the primitive scales to N axes without reintroducing the duplication that motivated the refactor.

### 2026-05-16 — Periodic predicate (v2.B Phase 3)

**Commit:** `3193cb1`
**Tests:** +21 (KIND_REGISTRY 99 → 100)
**What shipped:** `clock_tick` ledger entry kind + `Periodic(every_seconds=N)` predicate + `ClockTickEmitter` daemon. Axis 4 (gap-escalation) swapped to time-driven cadence; fresh-install ledgers can now escalate pre-existing gaps as soon as the first tick lands.
**Why:** Tick events are ledger-resident, not in-memory, because the gap-escalation decision depends on `(tick_time, ledger_state_at_tick_time)` and both must be replayable. Generalizes cleanly to daily-digest, weekly-summary, monthly-trend reactivities.

### 2026-05-17 — Agent-as-teammate (v2.A)

**Commit:** `b90a17e`
**Spec:** `docs/superpowers/plans/2026-05-16-semantic-layer-v2.A-agent-as-teammate.md`
**Tests:** +57 (KIND_REGISTRY 100 → 103; MCP tools 17 → 21)
**What shipped:** Agents shift from read-only MCP consumers to event-subscribed teammates. Three new ledger kinds (`agent_subscription_created`, `agent_subscription_revoked`, `agent_event_delivered`); `EventFilter` matching engine with four axes; `SubscriptionDispatcher` reactivity with two transports (MCP stream, HMAC webhook with retry); four new MCP tools (`agent.subscriptions.*`); wire-replay determinism preserved via `ReactivityContext.replay_mode`.
**Why:** Compounding axes now have a delivery channel. The agent lifecycle (register → grant → query → subscribe → receive) is end-to-end ledger-resident, MCP-accessible, and dashboard-observable. The MCP-native institutional AI claim is now materially supported across 21 tools.

### 2026-05-18 — Polish bundle (v1.4)

**Commit:** `6aad010`
**Tests:** +20 (KIND_REGISTRY unchanged at 103)
**What shipped:** Channel-adapter writer-invariant allowlist replaces stale absolute-count assertion; `/people/agents/[id]` detail page (Identity / Access / Activity / Subscriptions / Audit sections); `LazyWebhookSecretResolver` resolves secrets at delivery time rather than boot; headless lint via `tsc --noEmit + lint:anti-patterns`; subscription-eligible kinds endpoint surfaces the dynamic list of 93 of 103 registered kinds from `KIND_REGISTRY`.
**Why:** Five of seven v2.A carry-forwards closed; two deferred with rationale (true SSE upgrade pending FastMCP capability; `agent_event_delivered` projection promotion pending volume signal). The agent-as-teammate surface is now production-ready end-to-end.

### 2026-05-19 — Embedding-based clustering (v2.B Phase 3b)

**Commit:** `0392162`
**Tests:** +42 (KIND_REGISTRY unchanged at 103)
**What shipped:** `EmbeddingService` Protocol + `OllamaCloudEmbeddingService` (nomic-embed-text, 768 dim) with per-instance LRU cache; v018 migration resizes projection embedding columns; hybrid cosine + substring `cluster_fn` for axes 1 + 3 (template-promotion, bad-pattern library); write-time embedding wire gated by `WORMBASE_EMBEDDING_ENABLED`.
**Why:** Compounding axes now cluster semantically, not lexically. An agent failing on one phrasing informs the institutional knowledge layer about all phrasings of the same intent. The Optional-Effect Injection pattern hits its third production case and becomes a doctrine candidate.

### 2026-05-20 — Projection-promoted gather (v2.B Phase 3c)

**Commit:** `a01dc73`
**Tests:** +17 (KIND_REGISTRY unchanged at 103)
**What shipped:** `QueryOutcomeProjectionReader` Protocol with Postgres (pgvector `<=>` TopK) and SQLite (Python cosine) impls; axes 1 + 3 read candidate outcomes from `projection_query_outcomes` instead of scanning the entire ledger; multi-tenant isolation at the SQL layer.
**Why:** As tenants compound learning over months, raw outcome counts grow into the tens of thousands. Phase 3c is the architectural unblock for production scale — indexed pgvector reads replace full-ledger scans, with byte-identical default-OFF behavior.

---

## Phase 3 — Overnight runs & doctrine consolidation (2026-05-21 → 2026-05-28)

A burst of overnight autonomous runs shipped seven multi-tenant and operational hardening paths, surfaced and closed the Optional-Effect Injection doctrine across eight production cases, established a perf baseline that surfaced a real operator footgun, and produced the durable maintenance playbook the rest of the project ran on.

### 2026-05-21 — Overnight run: 7 paths shipped

**Commit:** `becfe11`
**Spec:** `docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md`
**Tests:** +101 (KIND_REGISTRY unchanged at 103)
**What shipped:** Seven independent paths in one overnight execution — Optional-Effect Injection doctrine (716-line spec covering four observed cases); HNSW v019 index migration; agent revoke UI wire-up; embedding-backfill CLI (`wormbase-embedding-backfill`); multi-tenant MCP HTTP routing (`TenantRouter` + per-tenant rate limiter + quota tracker); SSE stream transport abstraction; full ESLint adoption.
**Why:** The first overnight autonomous run validated the subagent-driven dispatch pattern at scale. Every architectural addition stayed default-OFF byte-identical; the doctrine that emerged formalizes the pattern that made it possible.
**Carry-forwards:** Engine-per-tenant impl pending premium-tier ask; SSE flip pending FastMCP streaming-tool support; parallel-dispatch worktree discipline (`CLAUDE.md` §11.5) codified after a git-index race incident.

### 2026-05-22 — Final wave: 8 deferred paths

**Commit:** `9097c22`
**Spec:** `docs/superpowers/specs/2026-05-22-engine-per-tenant-routing-design.md`
**Tests:** +79 (KIND_REGISTRY 103 → 105)
**What shipped:** Worktree-per-parallel-dispatch playbook codified; embedding backfill `--all-tenants`; `no-explicit-any` warn → error (zero violations to fix — prior cleanup had already typed every surface); pgvector ≥0.6 boot pre-flight; FastMCP SSE feature-detection probe with three states; agent edit flow via new `agent_metadata_updated` kind; tenant-policy ledger emission via `tenant_quota_consumed`; engine-per-tenant routing design spec (impl gated on premium-tier ask).
**Why:** All eight paths the overnight run deferred shipped within four hours of authorization. Optional-Effect Injection doctrine reaches seven cases; the eighth (`TenantEngineRegistry`) ships as design-only — paradoxically, designing IS the requirement, but the impl is not.

### 2026-05-25 — Post-rest wave: trigger-gated paths

**Commit:** `65b7db6`
**Tests:** +119 (KIND_REGISTRY 105 → 106)
**What shipped:** Engine-per-tenant Phases 1+2 (Protocol extension + new `tenant_engine_registered` kind + parallel-replay validator); multi-region tenant routing; SSE streaming path test pin + disconnect-leak fix; agent-metadata revert UI; HNSW index tuning env knobs; tenant-quota dashboard surface at `/governance/tenant-quota`; EmbeddingService mxbai-embed-large fallback with v020 dim-flexible migration.
**Why:** External triggers had blocked these paths in prior waves; user override authorized the run. Optional-Effect Injection doctrine reaches its pre-designed eighth case. Two operator runbooks ship covering HNSW re-tuning and cross-model embedding migration.

### 2026-05-26 — Next pass: 3 of 6 carry-forwards

**Commit:** `9ff1811`
**Tests:** +34 (KIND_REGISTRY unchanged at 106)
**What shipped:** `resolve_engine_region` promoted to Protocol surface; embedding-backfill `--target-model` flag for cross-model migration; HNSW per-tenant data-model plumbing.
**Why:** Three more carry-forwards land cleanly; three honest external blockers remain (engine-per-tenant Phases 3+4 pending operator workflow, SSE flip pending FastMCP version, connection-pool-per-region pending deployment cloud shape). The `TenantEngineRegistry` Protocol grows from one resolver to three as per-tenant configurability surfaces clarify.

### 2026-05-27 — Polish pass: audit + benchmarks + helper

**Commit:** `c02cdf4`
**Tests:** +60 (KIND_REGISTRY unchanged at 106)
**What shipped:** 56-finding maintenance audit across 8 categories; performance baseline harness across 5 hot paths with 40 perf benchmarks (`@pytest.mark.perf` opt-in); `OptionalEffectGuard[T]` helper with built-in Rule 9 telemetry, adopted in two pilot cases.
**Why:** The audit + benchmarks turned "we think it's fine" into "we measured what's fine and what isn't." Critical finding: `WORMBASE_GATHER_VIA_PROJECTION` is 2000× slower on SQLite at N=5000 (an operator footgun), and cosine clustering dominates at N=1000 with 715ms vs 3.2ms substring fallback.

### 2026-05-28 — Top-3 carry-forwards

**Commit:** `de459db`
**Tests:** +42 (KIND_REGISTRY unchanged at 106)
**What shipped:** SQLite runtime guard (`GatherViaProjectionUnavailableError`) refuses Path B against non-Postgres engines; numpy-vectorized batch cosine clustering delivers 6.8× speedup mean, 7.7× p95, 222× worst-case at N=200; pyflakes unused-imports sweep cleared 261 of 297 findings across 150 files.
**Why:** Every benchmark-surfaced concern got an XS-or-S fix landing the same day. The footgun is closed with a conservative posture, the hot path is materially faster, and the codebase is 88% cleaner on lint findings.

---

## Phase 4 — Lake-side compounding program (2026-05-29 → 2026-06-09)

The eight-axis lake-side compounding program — the architectural payoff of the substrate. Each axis followed the same four-sub-wave template (ledger → inference → worm-core → dashboard) at roughly three hours wall-clock per axis. By the end of this phase the lake-side family was closed at eight axes with three cross-axis chains validated, the `LakeLoopComposite[T]` abstraction proven across five day-one consumers, and three distinct affirmative-state naming patterns (`confirmed` / `promoted` / `acknowledged`) codified into doctrine.

### 2026-05-29 — L3 lineage discovery (first lake-side axis)

**Commit:** (this close-out)
**Spec:** `docs/superpowers/specs/2026-05-28-lake-side-compounding-l3-design.md`
**Tests:** +122 (KIND_REGISTRY 106 → 109; Migrations [1..21])
**What shipped:** Three lineage edge kinds (`lineage_edge_proposed/confirmed/rejected`); `LineageInferenceService` with three strategies (`DbtManifestStrategy` productive today; `NamingHeuristicStrategy` + `SampleOverlapStrategy` honest-stubbed pending Wave 1 column-list mirroring); `/lake/lineage` admin page with Sugiyama-lite SVG graph view; `/lake/connectors` marketplace shell.
**Why:** The first lake-side compounding axis validates the template the next seven axes will follow. Optional-Effect Injection doctrine reaches its ninth case.

### 2026-05-31 — Institutional onboarding

**Commit:** `f0c6d99`
**Spec:** `docs/superpowers/specs/2026-05-30-institutional-onboarding-design.md`
**Tests:** +180 (KIND_REGISTRY 109 → 111)
**What shipped:** Unified `/onboard` route consolidating seven onboarding-touchable object kinds (chat / source / domain / person / policy / agent / subscription); `CapabilityBadges` shared component with nine-state status enum; universal `/status/[kind]/[id]` and `/logs/[kind]/[id]` deep-link surfaces; four domain packs (generic, saas, marketplace, fintech); `domain_pack_selected` and `person_invited` ledger kinds; Stripe OAuth reference implementation replacing the credential-paste redirect; per-connector status probes via the Connector Protocol's lifecycle; `confirm_concept` graduation writing real ledger entries.
**Why:** OpenClaw's onboarding pattern now has its institutional analog — capability badges as data, status-as-verb, per-adapter capability sets, onboarding-deferred channel adds. The four critical fixes a three-subagent research wave surfaced are all closed.

### 2026-06-01 — L7 quality checks

**Commit:** `0e259f4`
**Spec:** `docs/superpowers/specs/2026-05-30-lake-side-compounding-l7-design.md`
**Tests:** +150 (KIND_REGISTRY 111 → 114; Migrations [1..22])
**What shipped:** Three quality-check kinds with seven-value `check_kind` enum (`not_null` / `unique` / `freshness` / `row_count_range` / `enum_membership` / `type_stability` / `value_range`); `QualityCheckProposalService` with three strategies (`SchemaPatternStrategy` productive on column-aware heuristics; `DbtTestsStrategy` honest about Wave 1 catalog-mirror gap; `HistoricalStatsStrategy` gated stub); `/lake/quality` admin page.
**Why:** Second lake-side axis. Template generalization confirmed — L3 → L7 share substantial shape, validating the four-sub-wave dispatch pattern.

### 2026-06-03 — L4 schema-evolution-impact (first cross-axis chain)

**Commit:** `9caea71`
**Spec:** `docs/superpowers/specs/2026-06-02-lake-side-compounding-l4-design.md`
**Tests:** +166 (KIND_REGISTRY 114 → 117; Migrations [1..23])
**What shipped:** Three schema-impact kinds; `SchemaImpactService` with three strategies (`LineageEdgeImpactStrategy` + `DbtTestImpactStrategy` + `TypeCoercionImpactStrategy`); `LineageEdgeReader` Protocol — **the first cross-axis chain** in the WormBase architecture (L4 reads L3's confirmed lineage edges); `LedgerLineageEdgeReader` as the first cross-axis adapter; `/lake/schema-impact` with cross-axis trace navigation back to L3.
**Why:** Validates that lake-side loops can chain via `*Reader` Protocols. The canonical cross-axis read pattern is now established: producer axis owns the Protocol and adapter, consumer axis imports both and injects at boot, dashboard renders the cross-axis link when `upstream_*_id` is set.

### 2026-06-04 — Doctrine review + `LakeLoopComposite[T]` refactor

**Commit:** `a4a62c2`
**Spec:** `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` Addendum 4
**Tests:** +19 (KIND_REGISTRY unchanged at 117; ceiling raised 120 → 150)
**What shipped:** Schema-evolution doctrine Addendum 4 — KIND_REGISTRY ceiling raised to 150 with L-axis family cap of 30, four retire candidates marked DEPRECATED (documentation-only per Rule 1's forever-stable doctrine), next-review trigger at 140. `LakeLoopComposite[T]` generic extracted from L3 + L7 + L4 — ~170 LOC of duplicated business logic removed; future axes shrink from ~250 LOC composite to ~80 LOC wrapper.
**Why:** L4 hit the 3rd-consumer threshold for the OptionalEffectGuard precedent's DRY refactor trigger. The doctrine review establishes the L-axis family is the institutional-AI growth surface this codebase targets; the refactor makes each subsequent axis cheaper to ship.

### 2026-06-05 — L5 fingerprinting (first day-one composite consumer)

**Commit:** `df2f96d`
**Spec:** `docs/superpowers/specs/2026-06-05-lake-side-compounding-l5-design.md`
**Tests:** +175 (KIND_REGISTRY 117 → 120; Migrations [1..24])
**What shipped:** Three semantic-type kinds with nineteen-value enum (email / pii_ssn / iso_date / etc.); `ColumnNameFingerprintStrategy` (productive today via 30-40 regex patterns), `ValuePatternFingerprintStrategy` and `DistributionFingerprintStrategy` (honest-stubbed pending sampler activation); composite built on `LakeLoopComposite[T]` from day one at 16 LOC instead of 250; `/lake/semantic-types` admin page with PII chip foreshadowing the deferred L5 → L6 chain.
**Why:** First axis built on the DRY refactor from day one. Validates the abstraction concretely — zero friction reported, default merge worked out-of-the-box, future axes should follow this pattern.

### 2026-06-06 — L6 column classification (second cross-axis chain)

**Commit:** `0f64f7d`
**Spec:** `docs/superpowers/specs/2026-06-06-lake-side-compounding-l6-design.md`
**Tests:** +182 (KIND_REGISTRY 120 → 123; Migrations [1..25])
**What shipped:** Three column-classification kinds with five-value `ClassificationLevel` enum (`public` / `internal` / `confidential` / `pii` / `regulated`); three strategies including `SemanticTypeClassificationStrategy` reading L5's confirmed semantic types — the **second cross-axis chain** via the new `ConfirmedSemanticTypeReader` Protocol; `/lake/column-classification` with cross-axis nav to L5.
**Why:** Second cross-axis chain canonicalizes the pattern. `LakeLoopComposite[T]` from day one at 15 LOC. The PII-chip cue foreshadowed on L5 now has its consumer side wired.

### 2026-06-07 — L8 entity stitching (first cross-axis Protocol+Adapter reuse)

**Commit:** `ddd5d5b`
**Spec:** `docs/superpowers/specs/2026-06-07-lake-side-compounding-l8-design.md`
**Tests:** +166 (KIND_REGISTRY 123 → 126; Migrations [1..26])
**What shipped:** Three entity-stitch kinds with eight-value `EntityKind` enum; three strategies including `NameMatchEntityStrategy` reusing L6's `ConfirmedSemanticTypeReader` Protocol and `LedgerConfirmedSemanticTypeReader` adapter — **third cross-axis chain, first chain to reuse another axis's Protocol+Adapter without re-defining either**; `/lake/entity-stitches` with cross-source pairing.
**Why:** Validates the cross-axis pattern as canonical infrastructure rather than per-axis repetition. Zero new cross-axis files; the consumer axis simply imports and injects. `LakeLoopComposite[T]` at 14 LOC.

### 2026-06-08 — L1 source-candidate triage (Reader Protocol generalizes)

**Commit:** `6412b62`
**Spec:** `docs/superpowers/specs/2026-06-08-lake-side-compounding-l1-design.md`
**Tests:** +227 (KIND_REGISTRY 126 → 129; Migrations [1..27])
**What shipped:** Three source-candidate kinds; three strategies (`KpiGapAcquisitionStrategy` / `ChannelMentionAcquisitionStrategy` / `ComplementaritySourceStrategy`) with three new lightweight Reader Protocols reading platform projections (sources / KPIs / silver conversations); composite at 11 LOC (smallest yet); `promote_source_candidate` synchronously dual-writes a downstream `source_proposed` entry — the first axis introducing the **`promoted` affirmative-state pattern** distinct from `confirmed`.
**Why:** Generalizes the Reader Protocol pattern beyond peer-axis chains to platform projections. The architectural lesson: agents read state via Protocol-shaped Readers with Ledger\*Reader fold-replay impls, uniformly, regardless of whether the upstream is a peer axis or a platform projection.

### 2026-06-09 — L2 catalog-drift detection (lake-side wave 1 closed)

**Commit:** `341622a`
**Spec:** `docs/superpowers/specs/2026-06-09-lake-side-compounding-l2-design.md`
**Tests:** +232 (KIND_REGISTRY 129 → 132; Migrations [1..28])
**What shipped:** Three catalog-drift kinds with five-value `drift_kind` enum (`table_added` / `table_removed` / `column_added` / `column_removed` / `column_type_changed`); three strategies (`TableSetDriftStrategy` + `ColumnSetDriftStrategy` + `ColumnTypeDriftStrategy` — all infrastructure-complete, bottlenecked on catalog payload thinness); `CatalogSnapshotReader` Protocol reading platform substrate; `/lake/catalog-drift` with five-color drift chips and before-after delta rendering; the **`acknowledged` affirmative-state pattern** — read-only disposition with no downstream effect.
**Why:** Eighth and final lake-side axis in this generation. Codifies the three-pattern naming doctrine (`confirmed` / `promoted` / `acknowledged`) for future axes. L-axis family lands at 24 of 30 cap; L9+ requires doctrine review.

### 2026-06-09 — Lake-side wave 1 generation closed (polish bundle)

**Commit:** `e67b89e`
**Tests:** +33 + 135 contract-test cases fixed
**What shipped:** Contract-test `_samples()` backfill across L3-L8 + L1 + L2 entry kinds (135 cases now passing); `min_confidence` knob enforcement across L6/L8/L1/L2 composites via `OptionalEffectGuard` integration; six-axis Stripe OAuth carry-forward resolved (test was stale; route's `/not-configured` redirect is the production-correct behavior); `FAMILY_PREFIXES` entry for `catalog_drift_*`.
**Why:** Closes four named carry-forwards from the program aggregate. The eight-axis lake-side compounding architecture is production-ready — every axis ships default-OFF, each strategy is per-knob-gated, banners are honest about upstream-richness gaps, and the orchestration substrate is uniform across the entire family.

---

## Phase 5 — Cross-axis chains & navigation symmetry (2026-06-10)

A single intense day shipped six cross-axis chains plus the navigation polish that makes the architecture visible as UX. Every chain followed the canonical recipe at ~50-90 minutes each; the polish bundles made every cross-axis relationship visible from both ends, with single-click drill-in across all eight axes.

### 2026-06-10 — Sampler activation

**Commit:** `d30fab6`
**Tests:** +42 (KIND_REGISTRY unchanged at 132)
**What shipped:** `SourceHandleProvider` Protocol + `LedgerSourceHandleProvider` folding `source_proposed → source_confirmed → source_connected`; `ConnectorSampler` bridging `SamplerProtocol` to `Connector.sample()` per-kind; three site swaps in agent-gateway construction. End-to-end roundtrip verified: csv_local source → ledger PEVR → handle provider → real connector → sampled column values surfaced back to strategies.
**Why:** Activates the three honest-stubbed sample-based strategies (L3 `SampleOverlapStrategy`, L5 `ValuePatternFingerprintStrategy`, L8 `SampleOverlapEntityStrategy`) behind a master env knob. Production hot-path unblock for value-based inference.

### 2026-06-10 — L5 → L7 cross-axis chain

**Commit:** `213c97b`
**Tests:** +28 (KIND_REGISTRY unchanged at 132)
**What shipped:** L7's fourth strategy `SemanticTypeQualityCheckStrategy` reads L5 confirmed semantic types via the canonical `ConfirmedSemanticTypeReader` Protocol — third reuse of L6's Protocol and adapter. Maps `email`/`uuid`/`business_id` → `not_null + unique`; `phone`/`url`/`pii_name` → `not_null`; `currency` → `not_null + range`.
**Why:** Fourth cross-axis chain. The 10-step recipe is now canonical at four instances; cost per chain stabilized at ~50 min wall-clock and ~28 tests with zero substrate changes.

### 2026-06-10 — L6 → L4 cross-axis chain

**Commit:** `c4134bc`
**Tests:** +38 (KIND_REGISTRY unchanged at 132)
**What shipped:** L4's fourth strategy `GovernanceClassificationImpactStrategy` reads L6 confirmed classifications and elevates impact severity (`regulated` → critical, `pii` → high, `confidential` → high). First producer-side Protocol from L6 (`ConfirmedClassificationReader`); new `LedgerConfirmedClassificationReader` adapter. Governance severity lives in `evidence.governance_severity` per the doctrine pattern.
**Why:** Fifth cross-axis chain. Recipe addendum codified: prefer enriching the `evidence` field over extending the payload schema to preserve the zero-KIND_REGISTRY constraint.

### 2026-06-10 — L5 → L4 cross-axis chain (composite-merge dedup emergent)

**Commit:** `9cf8387`
**Tests:** +30 (KIND_REGISTRY unchanged at 132)
**What shipped:** L4's fifth strategy `SemanticTypeImpactStrategy` reads L5 confirmed semantic types — fourth reuse of `LedgerConfirmedSemanticTypeReader`. When governance (L6 → L4) and semantic-type (L5 → L4) elevations fire on the same column, the composite merges them onto a single L4 row carrying both evidence keys, both cross-axis links, both severity chips.
**Why:** Sixth cross-axis chain. The three originally-foreshadowed peer-axis chains all shipped. Composite-merge dedup is the row-level analog of the evidence-dict pattern — both prefer enrichment over duplication, both preserve schema stability.

### 2026-06-10 — L4 ↔ L2 bidirectional chain

**Commit:** `14064d5`
**Tests:** +55 (KIND_REGISTRY unchanged at 132)
**What shipped:** L4's sixth strategy `AcknowledgedDriftImpactStrategy` reads L2 acknowledged drifts via new `AcknowledgedDriftReader` Protocol + `LedgerAcknowledgedDriftReader` adapter. L2 dashboard rows surface "↪ N downstream impacts" badges grouped by source/table/column. Composite-merge dedup verified at three-strategy depth.
**Why:** Seventh cross-axis chain and the first bidirectional one. The reverse-arc dashboard enrichment requires zero ledger / Protocol / adapter changes — cost of the reverse arc is near-zero when the forward arc is already shipped. This becomes recipe addendum #3 for future chains.

### 2026-06-10 — Reverse-arc polish bundle

**Commit:** `7311ecf`
**Tests:** +49 (KIND_REGISTRY unchanged at 132)
**What shipped:** Six reverse-arc dashboard enhancements applied to all prior single-direction cross-axis chains; L5 page absorbs four reverse-arc badges (L6 classifications, L8 entity stitches, L7 quality checks, L4 impact proposals) via the new `DownstreamCountsCluster` component; L3 + L6 pages each gain one impact-count badge.
**Why:** Every cross-axis relationship in the lake-side family is now visible from both ends. The L5 page tells the full lake-side fan-out story at a glance — that's the architectural narrative made visible as UX.

### 2026-06-10 — Consumer-page filter widgets

**Commit:** `be0bbc7`
**Tests:** +78 (KIND_REGISTRY unchanged at 132)
**What shipped:** Four consumer lake pages (`/lake/schema-impact`, `/lake/column-classification`, `/lake/entity-stitches`, `/lake/quality`) honor `upstream_*_id` URL params; composite filter SQL handles first-class columns, evidence JSON, and composite-merged multi-strategy rows; shared `ActiveFilterChips` component with clear-all link.
**Why:** Closes the navigation-depth TODO carried across all seven cross-axis chains. Clicking any reverse-arc badge or L4 ↔ L2 source/table/column badge lands on the consumer page already filtered to the relevant subset.

### 2026-06-10 — Producer-side deep-links

**Commit:** `bdee480`
**Tests:** +32 (KIND_REGISTRY unchanged at 132)
**What shipped:** Four producer pages (`/lake/lineage`, `/lake/semantic-types`, `/lake/column-classification`, `/lake/catalog-drift`) honor primary-key `?<entity>_id=` URL params; L4 → L2 evidence-link asymmetry closed via `readUpstreamEvidenceId` composite-merge-aware helper.
**Why:** Symmetric navigation completion. Every consumer-row "view producer" link now lands on a filtered producer page; every producer-row "view consumer" badge lands on a filtered consumer page. Bidirectional cross-axis architecture is now surfaced AND navigable as concrete UX.

### 2026-06-10 — Lake-Side Overview tab

**Commit:** `dafe3f5`
**Tests:** +32 (KIND_REGISTRY unchanged at 132)
**What shipped:** `/lake/overview` admin page with three sections — axis state grid (8 cards with correct affirmative-state labels per the 3-pattern doctrine), 7-row cross-axis chain panel including bidirectional flag for L4 ↔ L2, recent activity stream merged across all 8 lake projections with producer-side drill-in URLs.
**Why:** The dashboard surface now physically embodies the entire lake-side architecture. An admin opening `/lake/overview` for the first time can answer "how many axes have data flowing", "which axes feed which", and "what's happening right now" — three questions, one page.

### 2026-06-10 — L1/L4/L7/L8 PK deep-link filters

**Commit:** `711a52d`
**Tests:** +30 (KIND_REGISTRY unchanged at 132)
**What shipped:** Four remaining producer pages gain primary-key `?<entity>_id=` URL params; `lake-overview.ts` `producerParam` descriptor flipped from null to active for L1/L4/L7/L8; activity-stream drill-in now covers all eight axes.
**Why:** Symmetric navigation reaches 100% coverage. Every navigation flow across the 8-axis lake-side architecture is end-to-end navigable in both directions with single-click drill-in from the overview tab.

### 2026-06-10 — TS error polish bundle

**Commit:** `c18181f`
**Tests:** unchanged (KIND_REGISTRY unchanged at 132)
**What shipped:** Single-line fix in `apps/dashboard/lib/catalog-drift.ts:526` escapes two inner backtick pairs that were silently flipping a template literal into a tagged-template call against a `String`-typed identifier. `pnpm tsc --noEmit` now exits 0 across the dashboard.
**Why:** Carry-forward closed across five prior bundles. Clean tsc baseline established so any future TS errors come from the work that introduces them, not carried baggage.

---

## Phase 6 — Catalog-mirror Wave 2 & opaque-secret unblock (2026-06-10)

The final shipping day landed the per-table catalog substrate that unblocked four lake-side strategies whose Wave 1 posture was honest-empty-upstream, plus the per-connector extractor pattern that codifies the worm-core-side adapter doctrine, plus end-to-end credential-broker integration making opaque-secret connectors productive in the production onboarding flow.

### 2026-06-10 — Catalog-mirror Wave 2 (per-table substrate)

**Commit:** (Sub-wave C close-out)
**Tests:** +115 (KIND_REGISTRY 132 → 133; Migrations [1..29])
**What shipped:** New `catalog_table_imported` ledger kind with per-table column metadata; `projection_catalog_tables` migration with composite PK keyed on `(company_id, source_id, table_id, snapshot_hash)` so diff strategies are cheap; per-connector extractor registry as the canonical extensibility seam without touching the Connector Protocol; csv_local extractor productive end-to-end; dbt + snowflake productive via existing `TableMeta.columns`; L2 banner posture flips from `configured · empty-upstream` to `productive · per-connector` and L8 SchemaShape drops its currently-quiet qualifier.
**Why:** Four lake-side strategies (L2 TableSet / ColumnSet / ColumnType + L8 SchemaShape) unblocked. Default-OFF byte-identical preserved per-connector — unknown connector kinds get the safe no-op fallback. The per-connector extractor pattern mirrors Sampler activation: worm-core-side dispatch registry, honest empty default, additive connector graduation.

### 2026-06-10 — Per-connector extractor bundle

**Commit:** (addendum to catalog-mirror Wave 2)
**Tests:** +32 (KIND_REGISTRY unchanged at 133)
**What shipped:** Three connector extractors wired (postgres via `information_schema.columns`; s3_csv + http_csv via range-bounded CSV header parse); five honest-empty connectors documented with explicit per-kind rationale (bigquery / gsheets awaiting SDK; stripe deferring live API describe-cost design; salesforce / hubspot pending describe-API design pass).
**Why:** Adds productive coverage to four connector kinds beyond csv_local without touching the Connector Protocol. Codifies the worm-core-side adapter pattern: per-connector extractors are the well-paved extensibility path going forward.

### 2026-06-10 — CredentialBroker integration

**Commit:** (this close-out)
**Tests:** +26 (KIND_REGISTRY unchanged at 133)
**What shipped:** `LedgerSourceHandleProvider` now resolves opaque-secret connectors via `CredentialBroker.hold_data_account` when `WORMBASE_CREDENTIAL_BROKER_KIND` is set and `source_connected.credential_ref` is populated. Per-kind `OPAQUE_AUTH_HANDLE_ASSEMBLERS` dispatch for stripe / salesforce / hubspot / gsheets; additive `credential_ref` field on `SourceConnectedPayload`; separate env knob from the agent-gateway broker so sampler-side and gateway-side broker config ship independently.
**Why:** Stripe is end-to-end productive today; the other three are wired and waiting for their `sample()` impls to land. The architecture validates that handle reconstruction is a worm-core concern — the Connector Protocol stays unchanged at `authenticate / discover / profile / sample / watch`.

### 2026-06-10 — Source-builder credential_ref threading

**Commit:** (carry-forward closure)
**Tests:** +35 (KIND_REGISTRY unchanged at 133)
**What shipped:** `SourceBuilder.connect()` accepts `credential_ref` kwarg (additive); `CredentialInDmFlow` accepts a `credential_ref_resolver` host hook for provisioning broker slots at DM-time; new `CredentialRefInput` dashboard component renders only for opaque-secret kinds; `/api/sources/propose` route accepts and echoes `credential_ref` with honest `credential_ref_missing` flag.
**Why:** Converts the architecture from "wired and tested in test fixtures" to "fires in the production onboarding flow when the operator pastes a ref." Preserves the read-only broker posture — the dashboard accepts the operator-known reference, not the raw secret, keeping the dashboard out of the secret-handling perimeter. Honest-fail at `connect()`: opaque connectors without a ref land with a logged WARNING and `credential_ref_missing: true` in the propose response.

---

## Closing state

As of 2026-06-10:

| Metric | Value |
|---|---|
| KIND_REGISTRY | **133** (17 headroom under raised 150 ceiling) |
| L-axis family | **24 of 30** (6 headroom; doctrine review for L9+) |
| Cross-axis chains | **7** validated (6 single-direction + 1 bidirectional) |
| Reader Protocol instances | **8** (peer-axis × 4 + platform-projection × 3 + platform-substrate × 1) |
| Affirmative-state patterns | **3** (`confirmed` / `promoted` / `acknowledged`) |
| Optional-Effect Injection cases | **16+** (8 lake-axis composites via `LakeLoopComposite[T]`) |
| Migrations | **[1..29]** monotonic + forward-only |
| MCP tools | **21** |
| Reactivities | up to 14 enabled (5 default + 8 lake-side + subscriptions) |
| Admin dashboard tabs | **31** (8 lake-side + 23 other) |
| Env knobs | **77+** progressive opt-ins |
| Cumulative tests | **~5,000+** |
| ASML demo arc | **6/6** stable across all commits in the project |

The eight-axis lake-side compounding architecture is production-ready. Every axis ships default-OFF, each strategy is per-knob-gated, all banners are honest about upstream-richness gaps, and the orchestration substrate (ledger + projections + reactivities) is uniform across the entire family.

---

## 2026-05-17 — Continuous-lake philosophy + lake-surfaces rename complete

ADR-0013 issued. Wave A (anchor docs: `continuous-lake.md`,
`lake-side-loops.md`, ADR-0013), Wave B (README + ARCHITECTURE +
landing + DEVELOPERS rewrites), Wave C (polish across architecture
docs, ADR-0003 protocols-rehomed addendum), and Wave D (code rename
in 7 sub-tasks D1–D7) all shipped.

Wave D rolled out as 7 atomic commits with green tests between each:

| Commit | Sub-task |
|---|---|
| D1 | Rename `packages/connectors/` → `packages/lake-surfaces/`; rename Python module `wormbase_connectors` → `wormbase_lake_surfaces`; move `AcquirableSource` / `MaintainableSource` / `LakeStore` Protocols + `AcquirableSourceImpl` / `ConversationSource` / `EvidenceSource` impls + maintenance types from `lake-maintainer/` to `lake-surfaces/`; 47 Python files swept; `uv.lock` regenerated. |
| D2 | Rename Protocol `Connector` → `SurfaceDriver`; rename 15 concrete `*Connector` → `*SurfaceDriver` classes; rename registry `ConnectorRegistry` → `SurfaceDriverRegistry` and `register_connector` → `register_surface_driver`; 71 files touched. |
| D3 | TS catalog rename `connectors-catalog.ts` → `lake-surfaces-catalog.ts`; rename dashboard route `/lake/connectors` → `/lake/surfaces`; sweep all dashboard imports + UI strings (tab label, picker title, status copy, empty-state copy, testIds); 30 files touched. |
| D4 | Audit found no `*connector*` MCP tool names today; add `aliases.py` + smoke tests for the alias-mapping mechanism so future renames can register one-release aliases; new migration doc `docs/setup/migration-from-pre-rename.md`. |
| D5 | Full-regression run: 1153 pytest passed, 29 skipped, 14 pre-existing failures (verified against main, all unrelated to rename). 15/15 wire-replay determinism tests pass — ledger replay hashes unchanged. 2030/2030 dashboard tests pass. Lint sweep clean. |
| D6 | DB column audit: no `connector_kind` / `connector_type` columns in any migration or projection — no additive migration needed. Empty close-out commit. |
| D7 | Docs cleanup: `architecture-overview.md` §5 + §7.2 reframed to SurfaceDriver, `case-studies/openclaw-integration-patterns.md` reframed, `CONTRIBUTING-A-CONNECTOR.md` paths updated, ADR-0013 historic note. Lint final sweep returns empty for `class Connector(` and the legacy module name outside the spec/plan and the migration doc. |

Approximate delta: ~3000 LOC renamed (Python + TS), ~2400 LOC of new
docs (Waves A/B/C) earlier this week. Vocabulary stack fully migrated.
