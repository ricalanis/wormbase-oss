# The Continuous Lake — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-anchor the OSS public surface on the continuous-lake philosophy AND rename `packages/connectors/` → `packages/lake-surfaces/` with full vocabulary alignment, end-state matching the spec at `docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md`.

**Architecture:** Four waves.
- **Wave A** — 3 anchor docs (parallelizable; file-disjoint).
- **Wave B** — 4 public-facing rewrites (serial; vocabulary builds wave-on-wave).
- **Wave C** — ~9 polish edits (mostly parallelizable).
- **Wave D** — Code rename (serial-start to set imports, then parallel by language).

Spec is the source of truth for content. Each implementer subagent reads the spec, applies relevant sections to their task.

**Tech Stack:** Python 3.12 (uv + pyproject), Next.js 15 (pnpm + TypeScript), PostgreSQL, Markdown. Tests: `pytest` (Python), `pnpm test` (TS).

**Working directory:** `/Users/ricalanis/Dev/wormbase-oss-init/`

**Spec reference (read-this-first for every task):** `docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md`

---

## Dispatch shape

| Wave | Tasks | Dispatch | Wall-clock (est) |
|---|---|---|---|
| **A** | A1, A2, A3 | 3 parallel background subagents | ~10 min (slowest of 3) |
| **B** | B1 → B2 → B3 → B4 | Serial (each task builds vocabulary established by prior) | ~25 min |
| **C** | C1, C2 / C3, C4 / C5, C6, C7 | 3 batched parallel groups | ~15 min |
| **D** | D1 (rename) → D2 (TS+UI) → D3 (specs+ADRs) → D4 (regression) | Serial waves with intra-wave parallelism | ~45 min |

**Total estimate:** ~95 min wall-clock with parallel dispatch + serial review.

---

## Wave A — Anchor Docs

### Task A1: Create `docs/architecture/continuous-lake.md`

**Files:**
- Create: `docs/architecture/continuous-lake.md`

**Spec sections (read-this):** §1 Goal, §3 Research synthesis, §4 Thesis, §5 Vocabulary, §6 Two installations, §7 Source families, §8 Lake-side loops, §9 Architecture diagram correction.

- [ ] **Step 1: Read spec** — Read the full spec; pay closest attention to §3, §4, §6, §9.
- [ ] **Step 2: Draft umbrella doc with 9 sections:**
  - `# The Continuous Lake` (H1)
  - `## What this is` — thesis sentence + 2-paragraph elaboration
  - `## Positioning` — vs Acceldata / IBM / Snowflake / Databricks / Google Cloud / Atlan / Monte Carlo (use the table from spec §3.1; add 1-line WormBase-diff per row)
  - `## The two installations` — chat install + lake install (build OR connect); explain greenfield vs brownfield (spec §6)
  - `## Four kinds of surfaces` — external / filedrop / conversation / evidence as families; ASCII table per spec §7
  - `## Eight tending behaviors` — L1–L8 as the lake-side loops; ASCII table per spec §8 (each row links to `lake-side-loops.md` deep ref)
  - `## Architecture` — the corrected diagram from spec §9.2 (inline as ASCII)
  - `## What this isn't` — explicit non-claims: not a Fivetran replacement, not a Snowflake competitor, not bolt-on observability
  - `## Cross-references` — links to ADR-0013, ADR-0003, lake-side-loops.md, channel-adapters.md, surfaces.md (note this is the post-rename name)
- [ ] **Step 3: Verify file content** — Run `wc -l docs/architecture/continuous-lake.md` — expect 400–480 lines.
- [ ] **Step 4: Verify all spec-required terms appear** — Run `grep -c "continuous lake\|surface\|tending\|co-emergent\|install\|four families\|eight tending"` against the new doc — each pattern should appear ≥ 2 times.
- [ ] **Step 5: Commit** — `git add docs/architecture/continuous-lake.md && git commit -m "docs: continuous-lake umbrella narrative"`

### Task A2: Create `docs/architecture/lake-side-loops.md`

**Files:**
- Create: `docs/architecture/lake-side-loops.md`

**Spec sections:** §8 Lake-side loops (primary). Also read the 8 deep specs in `docs/superpowers/specs/2026-05-28-…` through `2026-06-09-…`.

- [ ] **Step 1: Read spec §8 + skim the 8 deep specs** — Each deep spec has a "Summary" or "Goal" section at the top; that's the input for the public reference.
- [ ] **Step 2: Draft the public-friendly L1–L8 reference:**
  - `# Lake-side loops` (H1)
  - `## What a lake-side loop is` — one-paragraph definition; "continuous tending behavior," not "pipeline stage"
  - `## L1 — source-candidate triage` (heading + 2-paragraph plain-English explanation + 1 bullet about what triggers it + link to deep spec)
  - `## L2 — catalog-drift detection` (same shape)
  - `## L3 — semantic-type inference` (same)
  - `## L4 — schema-impact analysis` (same)
  - `## L5 — column fingerprinting` (same)
  - `## L6 — column-classification` (same)
  - `## L7 — quality checks` (same)
  - `## L8 — entity-stitching` (same)
  - `## Cross-axis chains` — L5→L7, L6→L4, L5→L4, L4↦L2 documented; each as a 3-line explanation
  - `## How loops compose` — short note on `LakeLoopComposite[T]` pattern (read internal name; keep public framing simple)
  - `## Cross-references` — back to continuous-lake.md, ADR-0013
- [ ] **Step 3: Verify** — `wc -l docs/architecture/lake-side-loops.md` — expect 250–320 lines.
- [ ] **Step 4: Verify each L# appears** — `grep -c '^## L[1-8]'` → expect 8.
- [ ] **Step 5: Commit** — `git add docs/architecture/lake-side-loops.md && git commit -m "docs: public-friendly L1-L8 lake-side-loops reference"`

### Task A3: Create `docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md`

**Files:**
- Create: `docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md`

**Spec sections:** §3 Research synthesis, §4 Thesis, §11 Wave plan (for scope-of-decision section), §12 Open decisions/risks.

**Style reference (read first):** `docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md` — match this ADR's tone, structure, sectioning.

- [ ] **Step 1: Read spec + ADR-0003**
- [ ] **Step 2: Draft ADR matching ADR-0003 format:**
  - `# ADR-0013: The continuous lake — agent-installable, co-emergent`
  - `**Status:** Accepted`
  - `**Date:** 2026-05-17`
  - `## Context` — re-state the gap from spec §2.1–§2.3 (off-thesis diagram, pipeline-shaped vocabulary, hidden loops, etc.). Cite the discourse synthesis (industry's bolt-on framing).
  - `## Decision` — the thesis (spec §4 verbatim or near-verbatim) + the vocabulary stack from spec §5 (compressed to a table) + the two-installations articulation
  - `## Consequences` —
    - **Positive:** clear differentiation from industry; vocabulary aligned with code; user mental model matches what code does
    - **Negative:** rename cost (Wave D); reader migration from "connector" word; aliases-as-tech-debt for ~1 release cycle
    - **Neutral:** code semantics unchanged (wire-replay determinism preserved); structural ADR-0003 split retained, only homed differently
  - `## Cross-references` — Related: ADR-0003 (Protocols home moved per this decision), spec at `docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md`, sister docs continuous-lake.md and lake-side-loops.md.
- [ ] **Step 3: Verify** — `wc -l docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md` — expect 170–220 lines.
- [ ] **Step 4: Verify required sections present** — `grep -c '^## '` → expect ≥ 4 (Context / Decision / Consequences / Cross-references).
- [ ] **Step 5: Commit** — `git add docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md && git commit -m "docs: ADR-0013 continuous-lake philosophy"`

---

## Wave B — Public-facing rewrites

### Task B1: Rewrite `README.md` — opening + diagram + vocabulary

**Files:**
- Modify: `README.md`

**Spec sections:** §4 Thesis, §6 Two installations, §9.2 Corrected diagram, §5 Vocabulary stack.

**Depends on:** Wave A complete (cross-references in README will point at the new anchor docs).

- [ ] **Step 1: Read spec + the new continuous-lake.md** to ground vocabulary.
- [ ] **Step 2: Identify the opening paragraph + diagram + flow-section blocks** in README that need rewriting. Use `grep -n` to find anchor points:
  - Opening paragraph (~lines 1–20)
  - Architecture diagram (currently `subgraph Sources[Connector sources]`)
  - "GROW THE LAKE" flow step
  - "Adding a new connector" section (~line 302)
- [ ] **Step 3: Rewrite opening paragraph** — replace with the continuous-lake thesis sentence + two-installations articulation. Use vocabulary from spec §5.
- [ ] **Step 4: Replace architecture diagram** — substitute with the corrected diagram from spec §9.2. Keep mermaid format if used; otherwise ASCII.
- [ ] **Step 5: Rewrite the 4-step flow ("INSTALL / GROW THE LAKE / BUILD CONCURRENTLY / PRODUCE")** — reorient as "INSTALL (twice) / TEND / COMPOUND / PRODUCE." Update language; same structure.
- [ ] **Step 6: Rewrite "Adding a new connector" section** — title becomes "Adding a new lake surface." Updated for `packages/lake-surfaces/`, `SurfaceDriver` Protocol, `register_surface_driver` (post-Wave D names — note this section's filenames will be valid after Wave D).
- [ ] **Step 7: Add `## Tending the continuous lake` section** below the architecture diagram — 2 paragraphs explaining the 8 lake-side loops + lake-maintainer + catalog-mirror as the tending machinery. Link to lake-side-loops.md.
- [ ] **Step 8: Update "Status" section** — add bullet about continuous-lake philosophy. Link to ADR-0013.
- [ ] **Step 9: Update cross-reference links** — every `connectors.md` → `surfaces.md`. Every "connector" in user-facing prose → "lake surface" (audit by grep).
- [ ] **Step 10: Verify** — `wc -l README.md` — expect 420–500 lines (current 408 + ~80 delta).
- [ ] **Step 11: Verify vocabulary** — `grep -c "continuous lake\|lake surface\|tending\|two installation"` against README → each ≥ 2.
- [ ] **Step 12: Commit** — `git add README.md && git commit -m "docs(readme): re-anchor on continuous-lake thesis + corrected diagram"`

### Task B2: Rewrite `ARCHITECTURE.md` §3 + supporting framing

**Files:**
- Modify: `ARCHITECTURE.md`

**Spec sections:** §4, §5, §7, §8, §9, §10.

**Depends on:** Wave A complete, B1 complete.

- [ ] **Step 1: Read spec + Wave A docs**
- [ ] **Step 2: Find current §3** ("The Connector contract — data sources are pluggable") at around line 169.
- [ ] **Step 3: Replace §3 with new §3 "The continuous lake"** — multi-subsection:
  - §3.1 What the continuous lake is (thesis)
  - §3.2 Two installations (chat + lake; build OR connect)
  - §3.3 Four kinds of surfaces (external / filedrop / conversation / evidence)
  - §3.4 Eight tending behaviors (L1–L8 with one-line each; link to lake-side-loops.md)
  - §3.5 The SurfaceDriver Protocol (post-rename name; show the Protocol; one paragraph; link to surfaces.md for details)
  - §3.6 Composition with lake-maintainer (one paragraph; AcquirableSource + MaintainableSource as capability faces; ADR-0003 reference; ADR-0013 reference)
- [ ] **Step 4: Audit other sections** for `Connector` (driver class name) → `SurfaceDriver`; "connector" (lowercase common noun, user-facing) → "lake surface"/"surface." Use `grep -n -i 'connector' ARCHITECTURE.md` — categorize each hit as "rename" vs "keep" (e.g. the word "channel-adapter" is unrelated).
- [ ] **Step 5: Update §10 (or wherever package layout listed)** — `connectors/` → `lake-surfaces/` (post-rename; this doc reflects end-state).
- [ ] **Step 6: Update cross-references** — add ADR-0013 references.
- [ ] **Step 7: Verify** — `wc -l ARCHITECTURE.md` → expect 520–580 (current 468 + ~250 delta in §3 + smaller updates elsewhere).
- [ ] **Step 8: Verify §3 structure** — `grep -c '^### 3\.' ARCHITECTURE.md` → expect ≥ 5 subsections.
- [ ] **Step 9: Commit** — `git add ARCHITECTURE.md && git commit -m "docs(architecture): replace §3 with continuous-lake framing"`

### Task B3: Rewrite `landing/index.html` — hero + 02 card + diagram

**Files:**
- Modify: `landing/index.html`

**Spec sections:** §4 Thesis, §6 Two installations, §9.2 Diagram, §3 Industry positioning.

**Depends on:** Wave A complete, B1+B2 complete (vocabulary already in flight on README+ARCHITECTURE).

- [ ] **Step 1: Read spec + B1+B2 outputs** to mirror vocabulary.
- [ ] **Step 2: Update `<meta name="description">`** — new copy emphasizing "agent-installable continuous lake."
- [ ] **Step 3: Update hero `<h1>` and hero paragraph** — new thesis-aligned headline; new sub-headline articulating two installations.
- [ ] **Step 4: Update "02 · lake" card** — replace "Grows your lake agentically" with "Tends a continuous lake" or similar; rewrite body copy; emphasize build-or-connect.
- [ ] **Step 5: Add new card "03 · install" between or near existing 01/02** — articulates two installations: chat install + lake install (build OR connect). Keep visual consistency with surrounding cards.
- [ ] **Step 6: Update architecture diagram** — find the existing SVG-like or ASCII inline diagram; replace with the corrected diagram from spec §9.2 (lake at center, surfaces as faces, worm-core inside).
- [ ] **Step 7: Update stat strip** — change "12+ connectors" to "15+ lake surfaces" (or appropriate count).
- [ ] **Step 8: Update CTAs** — any `git clone` or "install" copy → reflect two-install framing; primary CTA stays "Get started."
- [ ] **Step 9: Update final "License" note** — minor; ensure consistent voice.
- [ ] **Step 10: Verify HTML still validates** — `python -c "from html.parser import HTMLParser; ..."` or just visual eyeball; check no broken tags.
- [ ] **Step 11: Verify** — `wc -l landing/index.html` → expect 1100–1250 (current 893 + ~280 delta).
- [ ] **Step 12: Commit** — `git add landing/index.html && git commit -m "docs(landing): re-anchor hero + lake card + architecture diagram"`

### Task B4: Rewrite `DEVELOPERS.md` — extending the continuous lake

**Files:**
- Modify: `DEVELOPERS.md`

**Spec sections:** §5 Vocabulary, §10 Code rename scope, §11 Wave plan.

**Depends on:** Wave A complete, B1+B2+B3 complete.

- [ ] **Step 1: Read spec + Wave A+B output**
- [ ] **Step 2: Add new section "Extending the continuous lake"** — should be a primary section, not nested. Content:
  - "Adding a new lake surface" — pattern for SurfaceDriver impl + registry + tests (Python side) + dashboard catalog mirror (TS side)
  - "Adding a new tending behavior" — pattern for a maintenance Reactivity in lake-maintainer
  - "Adding a new lake-side loop" — pattern for a LakeLoopComposite + strategies + Reader Protocol
  - "Adding a new catalog extractor" — pattern for per-connector extractor in catalog-mirror
- [ ] **Step 3: Audit "Connector" / "connector" hits in existing content** — replace per the vocabulary policy.
- [ ] **Step 4: Add cross-references** to ADR-0013, continuous-lake.md, surfaces.md (post-rename).
- [ ] **Step 5: Verify** — `wc -l DEVELOPERS.md` → expect 230–280 (current 154 + ~100 delta).
- [ ] **Step 6: Commit** — `git add DEVELOPERS.md && git commit -m "docs(developers): add extending-the-continuous-lake section + vocabulary update"`

---

## Wave C — Polish

### Task C1: Rename `connectors.md` → `surfaces.md` + reframe lead

**Files:**
- Move: `docs/architecture/connectors.md` → `docs/architecture/surfaces.md`
- Modify: new `docs/architecture/surfaces.md`

- [ ] **Step 1: `git mv docs/architecture/connectors.md docs/architecture/surfaces.md`**
- [ ] **Step 2: Rewrite lead** — replace opening paragraphs with "Surfaces as managed faces of the continuous lake" framing. Keep all status-honesty content (production / preview / coming_soon, day-one inventory, cross-language sync sections — these are still accurate).
- [ ] **Step 3: Update title** — `# Surfaces — capability honesty and promotion bar` (or similar).
- [ ] **Step 4: Update every "connector" reference** in the file per vocabulary policy.
- [ ] **Step 5: Update inventory table** — currently lists `kind` and `Notes`; keep, just retitle column headers to match new vocabulary.
- [ ] **Step 6: Add forward-link** — note that the file paths in §Cross-language sync will change post-Wave D; if Wave D is not yet done at file-rename time, add a TODO comment to revisit.
- [ ] **Step 7: Verify** — `test -f docs/architecture/surfaces.md && ! test -f docs/architecture/connectors.md`.
- [ ] **Step 8: Commit** — `git add docs/architecture/surfaces.md && git commit -m "docs(surfaces): rename from connectors.md + reframe lead"`

### Task C2: Update `docs/architecture/decisions/README.md` index

**Files:**
- Modify: `docs/architecture/decisions/README.md`

- [ ] **Step 1: Read current index format**
- [ ] **Step 2: Add ADR-0013 entry** in the index list, in chronological order
- [ ] **Step 3: Verify list ordering**
- [ ] **Step 4: Commit** — `git add docs/architecture/decisions/README.md && git commit -m "docs: index ADR-0013"`

### Task C3: Update `docs/architecture/README.md`

**Files:**
- Modify: `docs/architecture/README.md` (verify it exists; if not, skip)

- [ ] **Step 1: Read current content**
- [ ] **Step 2: Surface continuous-lake.md and lake-side-loops.md as primary entry points** at the top of the doc.
- [ ] **Step 3: Update other links** for `connectors.md` → `surfaces.md`.
- [ ] **Step 4: Verify**
- [ ] **Step 5: Commit** — `git add docs/architecture/README.md && git commit -m "docs(architecture): surface continuous-lake as primary entry point"`

### Task C4: Update `docs/architecture/channel-adapters.md`

**Files:**
- Modify: `docs/architecture/channel-adapters.md`

- [ ] **Step 1: Read current content**
- [ ] **Step 2: Add 1-paragraph note** that channel-adapter writes to the conversation surface (one of four families per ADR-0003); reference ADR-0013 / continuous-lake.md.
- [ ] **Step 3: Commit** — `git add docs/architecture/channel-adapters.md && git commit -m "docs(channel-adapters): cross-ref continuous-lake conversation surface"`

### Task C5: Update `ADR-0003-lake-maintainer-pattern.md` — Protocols home moved

**Files:**
- Modify: `docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md`

- [ ] **Step 1: Read current content**
- [ ] **Step 2: Add an addendum section near the bottom** (above `## Cross-references`):
  - `## Update 2026-05-17 — Protocols rehomed`
  - Brief note: per ADR-0013, `AcquirableSource` + `MaintainableSource` Protocols moved from `lake-maintainer/` to `lake-surfaces/`. Behaviorally unchanged; import paths updated. `lake-maintainer/` now imports the Protocols from `lake-surfaces/`.
- [ ] **Step 3: Update §Cross-references** — add ADR-0013 link.
- [ ] **Step 4: Commit** — `git add docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md && git commit -m "docs(adr-0003): note protocols rehomed per ADR-0013"`

### Task C6: Grep-sweep `docs/architecture/synthesis/` + `docs/architecture/orchestration/`

**Files:**
- Modify (variable): any file in these directories that uses pipeline-framing or pre-rename names.

- [ ] **Step 1: `grep -rn -l 'connector\|Connector' docs/architecture/synthesis/ docs/architecture/orchestration/`** — list files containing the legacy term.
- [ ] **Step 2: For each file, review hits and decide** rename vs keep (e.g. "channel-adapter" stays; "Slack connector" → "Slack surface").
- [ ] **Step 3: Apply rename edits surgically.**
- [ ] **Step 4: Add 1-line cross-ref to continuous-lake.md** where appropriate.
- [ ] **Step 5: Commit** — `git add docs/architecture/synthesis/ docs/architecture/orchestration/ && git commit -m "docs: grep-sweep synthesis+orchestration for continuous-lake vocabulary"`

### Task C7: Verify `docs/DELIVERY_LOG.md` + `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`

**Files:**
- Read-only verification: `docs/DELIVERY_LOG.md`, `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`.
- Optional edit if surprising staleness found.

- [ ] **Step 1: `grep -n 'Connector\|connector\|connectors' docs/DELIVERY_LOG.md`** — review hits.
- [ ] **Step 2: Same for `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`**
- [ ] **Step 3: Only edit if a hit is misleadingly stale** — e.g. a sentence that asserts current state but uses the legacy term. Otherwise leave (DELIVERY_LOG is a historical record; legacy terms in past entries are acceptable).
- [ ] **Step 4: Commit if edits made** — `git add docs/DELIVERY_LOG.md docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md && git commit -m "docs: update playbook + delivery-log for continuous-lake vocabulary"`

---

## Wave D — Code rename

### Task D1: Rename package + Python module + move Protocols

**Files (Python — many):**
- Move: `packages/connectors/` → `packages/lake-surfaces/`
- Move: `packages/connectors/src/wormbase_connectors/` → `packages/lake-surfaces/src/wormbase_lake_surfaces/`
- Move: `packages/connectors/tests/` → `packages/lake-surfaces/tests/`
- Move: `packages/lake-maintainer/src/wormbase_lake_maintainer/protocols.py` (or whichever file defines AcquirableSource / MaintainableSource) → `packages/lake-surfaces/src/wormbase_lake_surfaces/protocols.py`
- Modify: `packages/lake-surfaces/pyproject.toml` — package name + module name
- Modify: `packages/lake-maintainer/src/wormbase_lake_maintainer/__init__.py` — import Protocols from `wormbase_lake_surfaces`
- Modify: workspace deps — `pyproject.toml` root, all consumers
- Regenerate: `uv.lock`

**Depends on:** Wave C complete (ADR-0003 already updated to reflect this state).

- [ ] **Step 1: `git mv packages/connectors packages/lake-surfaces`**
- [ ] **Step 2: `git mv packages/lake-surfaces/src/wormbase_connectors packages/lake-surfaces/src/wormbase_lake_surfaces`**
- [ ] **Step 3: Inside the renamed package: identify Protocol definition file** in `packages/lake-maintainer/src/wormbase_lake_maintainer/`. Likely `protocols.py` or similar. Audit: `grep -rn "AcquirableSource\|MaintainableSource\|SurfaceFamily" packages/lake-maintainer/src/`.
- [ ] **Step 4: Move that file** to `packages/lake-surfaces/src/wormbase_lake_surfaces/protocols.py`. Use `git mv`.
- [ ] **Step 5: Inside `lake-maintainer/__init__.py`**, replace direct definition with imports: `from wormbase_lake_surfaces.protocols import AcquirableSource, MaintainableSource, SurfaceFamily, …`. Re-export for backwards compatibility within lake-maintainer only.
- [ ] **Step 6: Move `ConversationSource` and `EvidenceSource` impls** from `lake-maintainer/` to `lake-surfaces/` if they exist there. Audit: `grep -rln "class ConversationSource\|class EvidenceSource" packages/`.
- [ ] **Step 7: Update `packages/lake-surfaces/pyproject.toml`** — `name = "wormbase-lake-surfaces"` (or matching format), `[tool.hatch.build.targets.wheel] packages = ["src/wormbase_lake_surfaces"]`, dependency on `wormbase-lake-maintainer` if previously there (likely no — direction reversed now).
- [ ] **Step 8: Update `packages/lake-maintainer/pyproject.toml`** — add dependency on `wormbase-lake-surfaces`.
- [ ] **Step 9: Update root `pyproject.toml`** — workspace member rename `connectors` → `lake-surfaces`.
- [ ] **Step 10: Sweep imports across repo** — `grep -rln "wormbase_connectors" --include="*.py" .` — every file. Replace `wormbase_connectors` → `wormbase_lake_surfaces`. Use sed or per-file edits.
- [ ] **Step 11: `uv sync` / `uv lock`** — regenerate lockfile.
- [ ] **Step 12: Run pytest per renamed package** — `cd packages/lake-surfaces && pytest -x` — expect green (no behavior changed).
- [ ] **Step 13: Run pytest for lake-maintainer** — `cd packages/lake-maintainer && pytest -x` — expect green.
- [ ] **Step 14: Run pytest for worm-core + all dependents** — `pytest -x` from root.
- [ ] **Step 15: Commit** — `git add -A && git commit -m "refactor(lake-surfaces): rename connectors package; move protocols home"`

### Task D2: Rename Protocol + concrete driver classes

**Files:**
- Modify: `packages/lake-surfaces/src/wormbase_lake_surfaces/protocols.py` — rename `Connector` → `SurfaceDriver`
- Modify: every concrete driver — `*Connector` → `*SurfaceDriver`
- Modify: `packages/lake-surfaces/src/wormbase_lake_surfaces/registry.py` — function names + dict keys
- Modify: every callsite

**Depends on:** D1 complete.

- [ ] **Step 1: Rename Protocol** — in `protocols.py`, `class Connector(Protocol)` → `class SurfaceDriver(Protocol)`.
- [ ] **Step 2: Rename concrete classes** per spec §10.3 (15 classes):
  - `StripeConnector` → `StripeSurfaceDriver`
  - `PostgresConnector` → `PostgresSurfaceDriver`
  - `SnowflakeConnector` → `SnowflakeSurfaceDriver`
  - `BigQueryConnector` → `BigQuerySurfaceDriver`
  - `SalesforceConnector` → `SalesforceSurfaceDriver`
  - `HubSpotConnector` → `HubSpotSurfaceDriver`
  - `NotionConnector` → `NotionSurfaceDriver`
  - `LinearConnector` → `LinearSurfaceDriver`
  - `GSheetsConnector` → `GSheetsSurfaceDriver`
  - `S3CsvConnector` → `S3CsvSurfaceDriver`
  - `HttpCsvConnector` → `HttpCsvSurfaceDriver`
  - `CsvLocalConnector` → `CsvLocalSurfaceDriver`
  - `LocalLakeConnector` → `LocalLakeSurfaceDriver`
  - `_SkeletalConnector` → `_SkeletalSurfaceDriver`
  - `MCPConnector` → `MCPSurfaceDriver`
- [ ] **Step 3: Update registry** — `register_connector` → `register_surface_driver`; dict keys; type hints.
- [ ] **Step 4: Sweep callsites** — `grep -rln "Connector\|connector" --include="*.py" packages/ apps/ tests/` — audit each. Many will be legitimate (e.g. "channel-adapter"); rename only `Connector` class references and `wormbase_connectors`.
- [ ] **Step 5: Update test class names** — `TestStripeConnector` → `TestStripeSurfaceDriver` etc. Mostly mechanical.
- [ ] **Step 6: Rename test files** — `test_postgres_connector.py` → `test_postgres_surface_driver.py` (if such files exist; audit).
- [ ] **Step 7: Run pytest** — `pytest -x` from root — expect green.
- [ ] **Step 8: Commit** — `git add -A && git commit -m "refactor(lake-surfaces): rename Connector Protocol + 15 concrete drivers → SurfaceDriver"`

### Task D3: TypeScript catalog + dashboard UI rename

**Files:**
- Move: `apps/dashboard/lib/connectors-catalog.ts` → `apps/dashboard/lib/lake-surfaces-catalog.ts`
- Modify: every TS importer
- Modify: dashboard UI strings (tab labels, button text, picker copy)
- Move: `apps/dashboard/tests/lib/connectors-catalog.test.ts` → `lake-surfaces-catalog.test.ts`

**Depends on:** D1 complete (status-pin tests rely on matching Python class names).

- [ ] **Step 1: `git mv apps/dashboard/lib/connectors-catalog.ts apps/dashboard/lib/lake-surfaces-catalog.ts`**
- [ ] **Step 2: `git mv apps/dashboard/tests/lib/connectors-catalog.test.ts apps/dashboard/tests/lib/lake-surfaces-catalog.test.ts`**
- [ ] **Step 3: Inside `lake-surfaces-catalog.ts`** — update internal `kind` strings if they referenced `*Connector` class names (probably they used the lowercase `kind="stripe"` form which doesn't change).
- [ ] **Step 4: Sweep TS imports** — `grep -rln "connectors-catalog" apps/ tests/` — replace.
- [ ] **Step 5: Dashboard UI strings** — find every user-facing "Connector" / "connector" in `apps/dashboard/` `.tsx` `.ts`. Replace:
  - "Connectors" tab → "Lake surfaces"
  - "Add a connector" button/title → "Add a lake surface"
  - "Connector" status pill noun → "Surface"
  - "Connector status" descriptions → "Surface status"
  - Empty-state copy → updated
- [ ] **Step 6: Audit URL routes** — `grep -rn "'/connectors\|\"/connectors" apps/dashboard/` — if any `/connectors/*` routes exist, rename to `/lake-surfaces/*` (or `/surfaces/*` — pick to match URL aesthetics).
- [ ] **Step 7: Run dashboard tests** — `cd apps/dashboard && pnpm test` — expect green.
- [ ] **Step 8: Run TypeScript build** — `cd apps/dashboard && pnpm build` — expect green.
- [ ] **Step 9: Run TS typecheck** — `cd apps/dashboard && pnpm typecheck` (or `tsc --noEmit` equivalent).
- [ ] **Step 10: Commit** — `git add -A && git commit -m "refactor(dashboard): rename connectors-catalog → lake-surfaces-catalog + UI strings"`

### Task D4: MCP tool renames + aliases

**Files:**
- Modify: `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/tools.py` (or equivalent) — find every MCP tool name containing "connector"
- Add: `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/aliases.py` — alias registry
- Add: `docs/setup/migration-from-pre-rename.md` — public migration note

**Depends on:** D2 complete.

- [ ] **Step 1: Audit MCP tools** — `grep -rn "connector\|Connector" packages/wormbase-agent-gateway/src/` and find tool names + handlers.
- [ ] **Step 2: For each tool name with "connector":**
  - Rename to `*surface*` or `*lake_surface*` equivalent.
  - Add alias entry in `aliases.py` mapping old → new with one-release deprecation timestamp.
- [ ] **Step 3: Update tool docstrings** — vocabulary aligned with surfaces.
- [ ] **Step 4: Create migration doc** at `docs/setup/migration-from-pre-rename.md`:
  - Title: "Migrating from pre-rename MCP tool names"
  - 1-paragraph context (the rename)
  - Table: old name → new name → deprecation removal version
  - One-line CTA: "Update your MCP client config; aliases work until v1.0."
- [ ] **Step 5: Run pytest for agent-gateway** — `cd packages/wormbase-agent-gateway && pytest -x`.
- [ ] **Step 6: Verify alias routing** — write a quick smoke test in the gateway's test suite: both names invoke the same handler. If not present already, add one.
- [ ] **Step 7: Commit** — `git add -A && git commit -m "refactor(agent-gateway): rename connector MCP tools + alias for one release"`

### Task D5: Regression — full pytest + dashboard test + wire-replay determinism

**Files (read-only verification):**
- All test directories
- Wire-replay tape (location TBD by audit; commonly in `tests/integration/wire-replay/`)

**Depends on:** D1+D2+D3+D4 complete.

- [ ] **Step 1: Run full pytest** — `pytest -x` from root.
- [ ] **Step 2: Run dashboard tests** — `cd apps/dashboard && pnpm test`.
- [ ] **Step 3: Run dashboard typecheck** — `cd apps/dashboard && pnpm typecheck` (or `tsc --noEmit`).
- [ ] **Step 4: Run dashboard build** — `cd apps/dashboard && pnpm build`.
- [ ] **Step 5: Wire-replay determinism check** — locate replay tape; run replay; verify ledger hash unchanged. (If no wire-replay tape exists yet, note as a follow-up; the rename should not regress determinism.)
- [ ] **Step 6: Lint sweep** — verify no `wormbase_connectors` or `class Connector(` or `from .connectors` references remain in tracked files: `! grep -rn 'wormbase_connectors\|class Connector(\|class.*Connector)' --include='*.py' --include='*.ts' --include='*.tsx' .`
- [ ] **Step 7: CI-style verify imports** — `python -c "import wormbase_lake_surfaces; import wormbase_lake_maintainer; print('ok')"` — expect "ok" output.
- [ ] **Step 8: Commit** — `git commit --allow-empty -m "chore: post-rename regression verified"`

### Task D6: Database column audit + optional rename

**Files:**
- Audit: every projection table SQL definition
- Modify if needed: migration `packages/ledger/src/wormbase_ledger/migrations/v0XX-rename-connector-column.sql`

**Depends on:** D5 complete.

- [ ] **Step 1: Audit** — `grep -rn 'connector_kind\|connector_type\|connector_' packages/ledger/src/wormbase_ledger/migrations/ packages/*/src/*/projections/` — list hits.
- [ ] **Step 2: If hits found:** decide rename strategy:
  - **Recommended:** additive migration. Add `surface_driver_kind` column; copy values from `connector_kind`; keep `connector_kind` for one release (dropped at v1.0). Update reader code to prefer `surface_driver_kind`, fall back to `connector_kind`.
  - **Alternative (if no production deployment yet):** hard rename. Risk: nuke fixtures + seed data.
- [ ] **Step 3: If hits not found:** done; skip migration.
- [ ] **Step 4: Run migrations** — `alembic upgrade head` (or project equivalent).
- [ ] **Step 5: Verify projection reads** — pytest the projection layer.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "refactor(ledger): rename connector_kind → surface_driver_kind (additive)"` — or empty commit "chore: no DB rename needed."

### Task D7: Final regression + close-out

**Depends on:** D5+D6 complete.

- [ ] **Step 1: Re-run full pytest** — `pytest -x` from root.
- [ ] **Step 2: Re-run dashboard build + tests**
- [ ] **Step 3: Re-run wire-replay** if available.
- [ ] **Step 4: Update DELIVERY_LOG.md** — append entry: "2026-05-17 — Continuous-lake philosophy + lake-surfaces rename complete. ADR-0013 issued. Wave A/B/C/D shipped. ~3000 LOC renamed, ~2400 LOC docs delta."
- [ ] **Step 5: Verify ADR-0013 cross-refs land** — `grep -rln 'ADR-0013\|continuous-lake' docs/` → all cross-refs resolve.
- [ ] **Step 6: Final commit** — `git add docs/DELIVERY_LOG.md && git commit -m "chore: close-out continuous-lake philosophy + rename"`

---

## Verification (run after every wave)

```bash
# Vocabulary sanity (should NOT find these in tracked files after Wave D):
! grep -rn 'wormbase_connectors\|class Connector(' --include='*.py' .

# Vocabulary sanity (should NOT find user-facing legacy term in dashboard):
! grep -rn '"Connectors"\|"Add a connector"' --include='*.tsx' --include='*.ts' apps/dashboard/

# Vocabulary sanity (should find new terms in docs):
grep -rln 'continuous lake\|lake surface\|SurfaceDriver' docs/ ARCHITECTURE.md README.md
```

---

## Notes for the dispatcher

- **Wave A subagents are file-disjoint** — dispatch all 3 as background subagents in a single message.
- **Wave B is serial** — each builds on the prior's vocabulary. Dispatch one at a time; spec-review between.
- **Wave C is mostly parallel** — C2/C3 are tiny index updates; C4/C5 are tiny; C6 is a sweep. Batch reasonably.
- **Wave D requires sequencing** — D1 (rename + Protocols move) FIRST. Then D2 (class renames) requires D1. D3 (TS) can begin after D1. D4 (MCP) after D2. D5 (regression) after all. D6 (DB) is optional and last. D7 (close-out) requires everything.
- **Review cadence:** spec-compliance after each task; code-quality after each. Per subagent-driven-development skill.
- **Status writes:** mark TaskCreate'd tasks completed as soon as each is verified green.

---

*End of plan.*
