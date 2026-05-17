# The Continuous Lake — Design Spec

> **Status:** Draft for review (2026-05-17)
> **Author:** Ricardo Alanis
> **Scope:** OSS release re-positioning + code rename to align with the
> "continuous lake" philosophy
> **Supersedes (for OSS framing only):** the implicit "agent + ledger
> with lake as output" framing in `README.md`, `ARCHITECTURE.md` §3,
> `landing/index.html`. Does NOT supersede ADR-0003 (lake-maintainer
> Protocol split) — extends it by promoting the Protocols' home and
> renaming the driver class.

---

## 1. Goal

Re-anchor the public OSS surface so the reader's mental model of WormBase is:

> **WormBase installs into your data lake (or boots you a fresh one) and
> tends it continuously. From the moment of install, the lake is
> agent-operated. The agent and the lake co-emerge.**

This is a re-positioning, not a new feature. Every piece of machinery already
exists (lake-maintainer, the 8 lake-side compounding loops L1–L8, the 15
connectors, catalog-mirror, conversation-as-source). The OSS-side framing
currently presents connectors as "input adapters feeding worm-core" and
treats the lake as a downstream output. That mental model is off-thesis.
The fix is to:

1. Re-anchor docs on the "continuous lake" philosophy (Wave A/B/C).
2. Rename the code so the abstraction names mirror the philosophy (Wave D):
   `packages/connectors/` → `packages/lake-surfaces/`; `Connector` Protocol
   → `SurfaceDriver`; Protocols home → `lake-surfaces/`.

---

## 2. Trigger / What's wrong today

### 2.1 The diagram is doing the wrong work

Current `README.md` architecture diagram (verbatim shape):

```
[Chat platforms] → [channel-adapter] → [worm-core] → [Postgres ledger]
                                          ↑
                                          │
                                  [Connector sources]
                                  • default local lake
                                  • Stripe
                                  • Postgres
                                  • Notion via MCP
```

This picture reads: **"worm-core consumes from external sources."** That is
not what the code does. The code treats Stripe/Postgres/Notion not as
upstream inputs but as **managed surfaces of a continuous lake**. The
ledger projects every surface's state; the lake-maintainer continuously
tends it; the 8 lake-side compounding loops continuously refine it.

The diagram should put **the continuous lake at the center**, with surfaces
(conversation, external, filedrop, evidence) as faces of that lake, and
worm-core depicted as the **operator inside the lake**, not consumer from
outside it. See §10 for the corrected diagram.

### 2.2 The lead vocabulary is pipeline-shaped

The README narrates "GROW THE LAKE" as a one-time act in step 2 of a 4-step
operational arc. ARCHITECTURE.md §3 titles the connector contract
"data sources are pluggable." `docs/architecture/connectors.md` (71 ln) is a
status-honesty doc, not a positioning doc. None of these convey:

- The lake is **continuous**, not built-then-served.
- Surfaces are **tended**, not consumed.
- The agent and the lake **co-emerge** from t=0.

### 2.3 The vocabulary is hidden where readers won't find it

`docs/superpowers/specs/2026-05-30-lake-side-compounding-*` through `L8` are
the canonical references for the continuous-tending behaviors. They live
in `superpowers/specs/` which reads as "internal-looking." Readers
encountering the OSS repo for the first time will land on README and never
discover that 8 compounding loops are continuously running on the lake.

### 2.4 The Protocols are home in the wrong package

ADR-0003 placed `AcquirableSource` + `MaintainableSource` in
`packages/lake-maintainer/` (because the maintainer consumes them).
That made sense at the time. Post-rename, with `lake-surfaces/` as the
canonical home of the philosophy, the Protocols belong with their
surfaces. The maintainer becomes a consumer, not the definer.

### 2.5 The driver-class name leaks legacy framing

`class StripeConnector(Connector)` reads as "Stripe is a data pipe."
`class StripeSurfaceDriver(SurfaceDriver)` reads as "Stripe is a managed
surface; this class is its acquisition driver." The rename costs
~15 class names + import sweep + tests, and buys the engineering audience
a vocabulary aligned with the user's chat/dashboard experience.

---

## 3. Research synthesis (positioning slot)

### 3.1 Industry vocabulary as of 2026

| Vendor / source | Phrase | What it actually means |
|---|---|---|
| **IBM** | "Agentic data management" | AI agents on top of an existing platform |
| **Acceldata** | "Agentic data management" + "Agentic policy management" | Specialized agents for anomaly/quality/lineage on your existing stack |
| **Snowflake** | "Self-driving" | Managed warehouse auto-optimizes |
| **Google Cloud** | "AI-native lakehouse" / "always-on context" / "continuous feedback loops" | Lakehouse re-engineered to feed agents |
| **Databricks** | "Self-healing pipelines" | 80%+ of new DBs on Databricks platform now created by AI agents (Ali Ghodsi, 2026) |
| **Atlan / DataHub** | "Active metadata" | Metadata that drives action, not just stored |
| **Monte Carlo / Bigeye** | "Data observability" / "AI Trust Platform" | Detection + autonomous remediation as bolt-on layer |
| **CDO Magazine** | "Digital data steward" | AI agents that maintain catalog/quality |

### 3.2 The shared assumption

**Every vendor positions agentic maintenance as a bolt-on layer over an
existing lake/warehouse/lakehouse.** The lake pre-exists; the agents
arrive after to maintain it. Google's "AI-native lakehouse" gets closest
to co-design but still assumes the lakehouse was provisioned first;
agents are tenants who arrive after the substrate is built.

### 3.3 The slot WormBase actually occupies

WormBase inverts the shared assumption:

> **The lake exists *because* the agent is tending it.** Installation IS
> the first act of maintenance. Chat-install brings the first managed
> surface. Lurking is bronze ingestion. Memory is lake state. The
> conversation stream IS a source family. There is no lake *before* the
> agent. The agent and the lake co-emerge from t=0.

This is genuinely differentiated:

- **vs Acceldata / Monte Carlo / Bigeye**: They install AS a layer on top of your existing lake. WormBase installs INTO your lake (or boots you one).
- **vs Snowflake "self-driving"**: They optimize a managed warehouse. WormBase tends an open lake that may live in your warehouse, your S3, your Postgres, or a fresh local one.
- **vs Databricks "self-healing pipelines"**: They have pipelines that self-heal. WormBase doesn't have pipelines — it has continuous tending behaviors that work on whatever lake is installed-into.
- **vs Atlan / DataHub "active metadata"**: They have metadata that drives action. WormBase's ledger IS the metadata, and every action is hash-chained from the metadata.
- **vs Google "AI-native lakehouse"**: They re-engineered the lakehouse for agents. WormBase doesn't re-engineer the lake at all — it installs into whatever lake you have and tends it continuously.

### 3.4 Vocabulary to use and avoid

**Use (signals fluency without aping):**
- "Continuous feedback loops" (Google's phrase; load-bearing for us too)
- "Always-on context" (Google's phrase; lake-as-context is on-thesis)
- "Autonomous remediation" (industry vocabulary; describes what tending does)
- "Active" (Atlan family; the lake is active, not passive)

**Avoid (overloaded or off-thesis):**
- "Self-healing pipelines" (pipeline framing reasserts what we're rejecting)
- "Self-driving" (Snowflake-owned phrase; managed-platform connotation)
- "Data steward" (implies bolt-on role; humans-with-agents framing)
- "Agentic data management" (claimed by IBM + Acceldata; implies bolt-on)

**Coin / load-bear ourselves:**
- "Continuous lake" (the umbrella organism — co-emergent with the agent)
- "Lake surface" / "Surface" (managed face of the lake; user-facing word)
- "SurfaceDriver" (the Protocol; what concrete surface implementations subclass)
- "Tending" / "Tends" (the action; what the agent does to the lake)
- "Two installations" (chat + lake; both are install acts)
- "Co-emergent" (agent and lake come into being together; no lake before the agent)

---

## 4. The thesis

> **WormBase is the agent-installable continuous lake.**
>
> It installs into your chat platform (Slack / Discord / Teams) and into
> your data lake — either by **building** one (default local: csv/sqlite/
> parquet) or by **connecting** to your existing lake (Postgres warehouse,
> Snowflake, BigQuery, S3 lakehouse, Notion via MCP, etc.). Both paths
> end at the same state: a continuous, governed, agent-tended lake.
>
> From the moment of install, the lake is **continuous + agent-operated**.
> The agent and the lake co-emerge. Eight lake-side loops continuously
> tend the lake's state. Maintainable surfaces detect drift, refresh
> classification, signal staleness, and report lineage health on their
> own. Every action is hash-chained from the ledger.

---

## 5. Vocabulary stack (locked decisions)

| Term | Definition | Replaces / extends |
|---|---|---|
| **The continuous lake** | The umbrella organism: a lake + its agent-tending behaviors, co-emergent from t=0. Always-on. Always being tended. | New umbrella term |
| **Two installations** | Chat install (acquires user-side surface) + Lake install (build or connect). | Extends current "install into your chat" |
| **Surface** | A managed face of the continuous lake. User-facing word. Dashboard tab title. | Replaces "Connector" in user-facing surfaces |
| **SurfaceDriver** | Protocol for the acquisition face of an external/filedrop surface. `class StripeSurfaceDriver(SurfaceDriver)`. | Replaces `Connector` Protocol |
| **Lake surface** | Synonym for "Surface" when context is ambiguous. | New |
| **AcquirableSource** | Protocol (from ADR-0003, retained) — capability face for surfaces that can be discovered/profiled/sampled. | Unchanged structurally; rehomed to `lake-surfaces/` |
| **MaintainableSource** | Protocol (from ADR-0003, retained) — universal capability face: detect_drift / refresh_classification / staleness_signal / lineage_health. All four families implement this. | Unchanged structurally; rehomed to `lake-surfaces/` |
| **Source families** | The four families: `external`, `filedrop`, `conversation`, `evidence`. Each is a kind of managed surface. | Unchanged (from ADR-0003) |
| **Lake-side loops** | The 8 continuous tending behaviors (L1–L8). Each loop is one way the agent is continuously tending the lake's state. | Reframed from "compounding axes" |
| **Tending** / **Tend** | The action the agent performs on the lake. Replaces "build," "manage," "consume." | Verb anchor |
| **Co-emergent** | The agent and the lake come into being together. There is no lake before the agent installed. | Architectural commitment |
| **Build or connect** | Two paths to lake-install. Build (csv_local default) or connect (Postgres/Snowflake/Notion via MCP/etc.). | Surface acquisition modes |

### Vocabulary out of scope to change (intentionally retained)

- **Worm / worm-core** — Identity. Unchanged.
- **Ledger** — The substrate. Unchanged.
- **Reactivity / ReactivityRegistry** — Internal mechanism. Unchanged.
- **Medallion (bronze/silver/gold)** — Data tiering. Unchanged. Each tier is a layer of the continuous lake.
- **Source** (as a Python type) — Per-instance, has id/domain/owner. Distinct from `SurfaceDriver` (the driver class). The Source dataclass stays.

---

## 6. The two installations

### 6.1 Chat install

Familiar; already documented. `@connect slack` (or discord / teams).
Worm acquires a user-side surface. Default tier-0 onboarding.

### 6.2 Lake install — build OR connect

NEW explicit articulation:

**Build (greenfield):**
- Default: `csv_local` SurfaceDriver. Bootstraps `~/.wormbase/lake/{bronze,silver,gold}/` (or container-equivalent path).
- The build option is for prospects who don't have a data lake yet (most SMBs, demo paths, first-time installs).
- The agent immediately tends the freshly-built lake (medallion cascade, lake-side loops L1–L8 all run from t=0).

**Connect (brownfield):**
- One of: `postgres`, `snowflake`, `bigquery`, `s3_csv`, `http_csv`, `stripe`, `notion` (via MCP), `hubspot` (via MCP), `linear` (via MCP), `atlassian` (via MCP), etc.
- The agent installs into the existing lake (read-side access initially; write-side governed by Policy).
- Once connected, the existing lake is **tended by WormBase** — lake-side loops, drift detection, classification refresh, lineage health all begin operating from t=0 of connect.

**Same end-state, same code-path:**
- Both options produce a `Source` instance with `family={external|filedrop|...}`.
- Both options trigger the `propose → execute → verify → resolve → trace` ledger sequence (PEVR primitive).
- Both options activate the same lake-side loops (L1–L8).
- Both options become equally tended.

This is what the user means by "build or connect to a datalake and install ourselves in it."

### 6.3 Hybrid

The default-local + connected combination is the most common. A
prospect installs WormBase, gets a default local lake bootstrapped, then
connects their Postgres warehouse a week later. The continuous lake
spans both surfaces; the agent tends them both.

The continuous lake is **federated by default**. Surfaces can live
anywhere the SurfaceDriver can reach. The ledger projects state from
all surfaces uniformly.

---

## 7. The four source families (kinds of surfaces)

From ADR-0003, unchanged structurally but rearticulated as surfaces:

| Family | Examples | AcquirableSource? | MaintainableSource? |
|---|---|---|---|
| **external** | Postgres, Snowflake, BigQuery, S3, Stripe, Notion via MCP | ✅ | ✅ |
| **filedrop** | CSVs dropped in Slack, evidence uploads, one-off PDFs | ✅ | ✅ |
| **conversation** | The chat stream itself — every message, mention, thread, decision | ❌ (read-from-ledger, not acquirable in tabular shape) | ✅ |
| **evidence** | Autoresearch-published notebooks, data products | ❌ (produced internally, not acquired) | ✅ |

All four families are equally lake-resident. None is more "real" than the
others. The conversation lake and the evidence lake are first-class
sources, not auxiliary streams.

This re-articulation matters because: the OSS docs today treat
"connector sources" as the source story (with the chat as a separate
channel). The correct framing: **the chat stream IS a source family**
that the agent has been tending since chat-install (lurking = bronze
ingestion). The same medallion cascade applies.

---

## 8. The 8 lake-side loops (continuous tending behaviors)

Renarrated as continuous tending behaviors:

| Loop | Spec | Tending behavior |
|---|---|---|
| **L1** | `2026-06-08-lake-side-compounding-l1-design.md` | Continuously triages candidate sources mentioned in conversation → proposes new surfaces |
| **L2** | `2026-06-09-lake-side-compounding-l2-design.md` | Continuously detects catalog drift in connected surfaces → acknowledges or flags |
| **L3** | `2026-05-28-lake-side-compounding-l3-design.md` | Continuously discovers lineage edges between tables and columns → confirms or revises |
| **L4** | `2026-06-02-lake-side-compounding-l4-design.md` | Continuously computes schema-impact when surfaces change → elevates governance |
| **L5** | `2026-06-05-lake-side-compounding-l5-design.md` | Continuously fingerprints columns → identifies semantic types across the lake |
| **L6** | `2026-06-06-lake-side-compounding-l6-design.md` | Continuously classifies columns (PII / confidential / etc.) → confirms or escalates |
| **L7** | `2026-05-30-lake-side-compounding-l7-design.md` | Continuously runs quality checks → emits findings to the ledger |
| **L8** | `2026-06-07-lake-side-compounding-l8-design.md` | Continuously stitches entities across surfaces → resolves identity |

**Each loop is one way the agent is tending the lake's state.** All eight
run concurrently from t=0 of install. All eight produce ledger entries
that are projection-folded into the dashboard's `/lake/*` pages. Cross-axis
chains (L5→L7, L6→L4, L5→L4, L4↦L2) compose the loops into multi-step
inferences.

Public-friendly reference doc to be created: `docs/architecture/lake-side-loops.md`
(Wave A).

---

## 9. Architecture diagram correction

### 9.1 Current diagram (wrong)

Visualized in §2.1. Connector sources are a separate box at the bottom
feeding into worm-core. Reads as "worm-core consumes from external sources."

### 9.2 Corrected diagram (right)

The continuous lake is at the center. Surfaces are kinds of faces of the
lake, all equally lake-resident. Worm-core is depicted as the operator
inside the lake — not a consumer outside it.

```
                                    ┌────────────────────────────────────────────────┐
                                    │             The continuous lake                │
   ┌─────────────────┐               │                                                │
   │  Chat platforms │               │    ┌──conversation──┐    ┌────external────┐    │
   │  Slack/Discord  │ ←─ tending ─→ │    │ Slack/Discord  │    │ Postgres / SF  │    │
   │  Teams          │               │    │ threads        │    │ S3 / Notion(MCP)│   │
   └────────┬────────┘               │    │ decisions      │    │ Stripe / HubSpot│   │
            │                        │    │ mentions       │    └────────────────┘    │
   ┌────────▼────────┐               │    └────────────────┘                          │
   │ channel-adapter │ ─ writes ──→  │    ┌────filedrop────┐    ┌────evidence────┐    │
   └─────────────────┘               │    │ dropped CSVs   │    │ notebooks      │    │
                                    │    │ evidence PDFs  │    │ data products  │    │
                                    │    └────────────────┘    └────────────────┘    │
                                    │                                                │
                                    │    ┌─────────────────────────────────────────┐ │
                                    │    │           worm-core (the tender)        │ │
                                    │    │  8 lake-side loops │ lake-maintainer    │ │
                                    │    │  catalog-mirror │ autoresearch │ MCP    │ │
                                    │    └─────────────────────────────────────────┘ │
                                    └────────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                                    ┌─────────────────┐
                                                    │  Postgres ledger│
                                                    │ append-only     │
                                                    │ hash-chained    │
                                                    └─────────────────┘
                                                             ▲
                                              ┌──────────────┴──────────────┐
                                              │ Dashboard │ MCP server      │
                                              │ Next.js   │ FastMCP :9911   │
                                              └─────────────────────────────┘
```

Key visual properties:
- **Lake at the center**, not at the bottom.
- **Surfaces as faces** of the lake, four equal families.
- **Worm-core inside the lake**, not outside it.
- **Ledger below the lake**, the substrate — explicit relationship.
- **Chat platforms as a tending channel**, not a separate input source.

This corrected diagram is the canonical one for README, ARCHITECTURE,
landing, and continuous-lake.md.

---

## 10. Code rename scope (Wave D)

### 10.1 Package rename

- `packages/connectors/` → `packages/lake-surfaces/`
- `wormbase_connectors` Python module → `wormbase_lake_surfaces`
- Test directory + test names follow.
- `pyproject.toml` + `pnpm-workspace.yaml` workspace deps updated.
- `uv.lock` regenerated.

### 10.2 Protocols home

Per the locked decision: `AcquirableSource` and `MaintainableSource` move
from `packages/lake-maintainer/src/wormbase_lake_maintainer/protocols.py`
(or wherever they live today) **into** `packages/lake-surfaces/src/wormbase_lake_surfaces/protocols.py`.

- `lake-maintainer/` imports them from `lake-surfaces/`.
- `lake-maintainer/` keeps the Reactivity machinery
  (`wire_maintenance_for_source`, per-family factory, dispatch loop).
- The dependency direction becomes: `lake-maintainer/` → depends on → `lake-surfaces/`. (Previously `lake-surfaces/` did not exist; `lake-maintainer/` was self-contained.)
- Conversation + Evidence MaintainableSource impls also move into `lake-surfaces/` (they implement the Surface Protocols; the maintainer consumes them).

### 10.3 Driver class rename

- `class Connector(Protocol)` → `class SurfaceDriver(Protocol)` in `wormbase_lake_surfaces.protocols`
- Concrete classes renamed:
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
- Registry: `connectors/registry.py` → `lake-surfaces/registry.py`. Functions renamed (`register_connector` → `register_surface_driver`, etc.).

### 10.4 MCP preset rename

- `mcp_presets/atlassian_preset.py` (etc.) — module name unchanged but internal class refs rename per §10.3.
- MCP preset classes likely follow the SurfaceDriver pattern.

### 10.5 TypeScript / dashboard rename

- `apps/dashboard/lib/connectors-catalog.ts` → `apps/dashboard/lib/lake-surfaces-catalog.ts`.
- Status pin test renamed similarly: `connectors-catalog.test.ts` → `lake-surfaces-catalog.test.ts`.
- Every TS import sweep.
- Dashboard UI strings:
  - Tab label "Connectors" → "Lake surfaces" (or "Surfaces" — see §10.10).
  - Picker title "Add a connector" → "Add a lake surface."
  - Status pill text "Connector" → "Surface."
  - Error / success copy updated.

### 10.6 HTTP endpoint rename

Audit pending; likely:
- `/sources/*` — STAYS (already source-named, on-thesis).
- `/connectors/*` (if any) → `/lake-surfaces/*`.
- `/api/connectors/*` (if any) → `/api/lake-surfaces/*`.
- Probably very few or zero given the URL inventory already uses "sources."

### 10.7 MCP tool rename

Audit pending. Candidates likely include:
- `list_connectors` → `list_lake_surfaces` (with one-release alias)
- `connector_status` → `surface_status` (with alias)
- `add_connector` → `add_lake_surface` (with alias)
- Aliases dropped at v1.0.

Aliases lower the migration cost for early external clients (Claude Desktop,
Cursor, Cline users). Hard rename at v1.0 cutover.

### 10.8 Database projections / columns

Audit pending. Probably no rename required:
- `projection_sources` is already source-named.
- Surface family enum `external/filedrop/conversation/evidence` is on-thesis.
- Possible: `connector_kind` column → `surface_driver_kind` (additive migration if so; aliased read).

### 10.9 Docs / specs / ADRs rename

- `docs/architecture/connectors.md` → `docs/architecture/surfaces.md` (rename, no redirect file — OSS is fresh-snapshot so no inbound links to preserve).
- `ADR-0003-lake-maintainer-pattern.md` — text update for the rehomed Protocols; pin date of update.
- Other ADRs touching connector/Source naming — light edits.
- All `superpowers/specs/*` — light grep-sweep for `wormbase_connectors` / `packages/connectors` / `Connector(Protocol)` and update.
- README + ARCHITECTURE — covered by Wave B.

### 10.10 User-facing label decision

**Recommended:** Use **"Lake surfaces"** as the dashboard tab label, **"Surface"** as the noun in chat (singular) / picker, and **"Add a lake surface"** in CTAs. "Surface" alone (without "lake") is fine when context is clear; "Lake surface" is safer in onboarding.

### 10.11 Out of scope for the rename

- The 4 source-family names (external / filedrop / conversation / evidence) stay. They are kinds-of-surface, on-thesis already.
- The `Source` dataclass (per-instance id/domain/owner) stays. It is distinct from the `SurfaceDriver` driver class.
- The `Reactivity` machinery in `lake-maintainer` stays.
- `worm-core`, `ledger`, all other package names — unchanged.

---

## 11. Wave plan

### Wave A — Anchor docs (3 new files)

| File | Purpose | ~lines |
|---|---|---|
| `docs/architecture/continuous-lake.md` | Umbrella narrative. Positions vs industry. Four families as kinds of surfaces. 8 loops as tending behaviors. Two installations (chat + lake). Build-or-connect. Co-emergence thesis. Corrected diagram (§9.2). | ~450 |
| `docs/architecture/lake-side-loops.md` | Public-friendly L1–L8 reference. Each loop as a tending behavior. Cross-axis chains documented. Links to deep specs in `superpowers/specs/`. | ~280 |
| `docs/architecture/decisions/ADR-0013-continuous-lake-philosophy.md` | Architectural commitment. The lake exists because the agent is tending it. Co-emergent. Differentiated against bolt-on agentic layers. | ~190 |

### Wave B — Public-facing rewrites (4 file edits)

| File | Change | ~delta |
|---|---|---|
| `README.md` | New opening framing (continuous lake thesis). Replace architecture diagram with §9.2 version. "GROW" → "TEND." New "Tending the lake" section. Update "Adding a new connector" section → "Adding a new lake surface." | ~150 |
| `ARCHITECTURE.md` | Replace §3 "The Connector contract" with new §3 "The continuous lake." Four families, 8 loops, lake-maintainer, catalog-mirror as integrated aspects. Reframe SurfaceDriver as one capability surface (acquisition face). | ~320 |
| `landing/index.html` | New hero ("WormBase is the agent-installable continuous lake"). Two-installations articulation. New diagram (lake at center). Lake-side loops surfaced as named axes. | ~300 |
| `DEVELOPERS.md` | New "Extending the continuous lake" section. Patterns for adding a SurfaceDriver, a tending behavior, a lake-side loop, a catalog extractor. | ~110 |

### Wave C — Polish (~9 file edits)

| File | Change | ~delta |
|---|---|---|
| `docs/architecture/connectors.md` → rename to `surfaces.md` | Reframe lead. Status-honesty content retained. | ~70 |
| `docs/architecture/decisions/README.md` | Index update for ADR-0013. | ~5 |
| `docs/architecture/README.md` | Surface continuous-lake + lake-side-loops as primary entry points. | ~40 |
| `docs/architecture/channel-adapters.md` | Note that channel-adapter writes to the conversation surface (one of four families). | ~15 |
| `docs/architecture/synthesis/*.md` | Light edits where old framing leaks through. | variable |
| `docs/architecture/orchestration/*.md` | Light edits where old framing leaks through. | variable |
| `docs/DELIVERY_LOG.md` | Sanity-check lake-related phases are well-labeled. | light |
| `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md` | Verify vocabulary consistent. | light |
| `docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md` | Update Protocols-home pointer (Protocols moved). Add cross-ref to ADR-0013. | ~20 |

### Wave D — Code rename (~18 sub-tasks; full enumeration in plan)

| Sub-task | Files | Risk |
|---|---|---|
| D1 | Package directory rename `connectors/` → `lake-surfaces/` | Low (path-only) |
| D2 | Python module rename `wormbase_connectors` → `wormbase_lake_surfaces` | Medium (every import) |
| D3 | Move Protocols from `lake-maintainer/` to `lake-surfaces/` | Medium (cross-package deps) |
| D4 | Rename `Connector` Protocol → `SurfaceDriver` | Medium (every impl) |
| D5 | Rename 15 concrete `*Connector` → `*SurfaceDriver` | Medium (every callsite) |
| D6 | Rename registry functions | Low |
| D7 | TS catalog rename | Low |
| D8 | TS imports sweep | Medium |
| D9 | Dashboard UI string updates ("Connectors" → "Lake surfaces" etc.) | Low |
| D10 | MCP tool rename + alias | Medium (external clients) |
| D11 | DB column audit + optional rename `connector_kind` → `surface_driver_kind` | Low (likely no-op) |
| D12 | ADR-0003 text update | Low |
| D13 | Specs grep-sweep + light updates | Low |
| D14 | Test directory + file renames | Low |
| D15 | `pyproject.toml` + `pnpm-workspace.yaml` updates | Low |
| D16 | Full regression: `pytest` + dashboard `pnpm test` + integration | Medium |
| D17 | `uv.lock` + `pnpm-lock.yaml` regen | Low |
| D18 | Wire-replay tape regression (ensures ledger replay determinism unchanged) | Medium |

Per CLAUDE.md velocity calibration (~120 LOC/min sustained for well-specified
tasks), the full Wave A+B+C+D is estimated at 60–90 min wall-clock with
parallel subagents, assuming detailed Wave D enumeration in the plan
document. The rename's blast radius is bounded by the import graph; the
~2200 LOC of new docs + ~3000 LOC of renames sit at the rate-limit.

---

## 12. Open decisions / risks

### 12.1 Hard rename vs. release-cycle alias for MCP

**Decision:** Hard rename with **one-release alias** for MCP tool names.

- Aliases live in `wormbase_agent_gateway/aliases.py`; the gateway routes both names to the same handler.
- Aliases dropped at v1.0 cutover (~6 weeks out per current roadmap).
- Aliases are documented in `docs/setup/migration-from-pre-rename.md` (new file in Wave C).

### 12.2 Source dataclass — distinct from SurfaceDriver

Reiterating ADR-0003 §Neutral: `Source` (per-instance, `id`, `domain`, `owner`) is distinct from `SurfaceDriver` (the driver class, kind="postgres"). The rename keeps this distinction intact. Conflating them would re-invent one or the other.

### 12.3 What if someone calls `from wormbase_connectors import Connector`?

In the OSS public release, this import was never exposed (the OSS repo is fresh-snapshot). No backwards-compatibility shims required for OSS consumers. For internal consumers (none beyond the dev team), the rename is announced + sweep is exhaustive.

### 12.4 The Conversation + Evidence MaintainableSource impls

ADR-0003 places `ConversationSource` and `EvidenceSource` impls in `lake-maintainer/`. Post-Wave D, they move to `lake-surfaces/` alongside the Protocols. This is consistent with "surfaces define their faces" (§10.2).

### 12.5 Renaming `mcp_presets/`

`mcp_presets/` stays. The MCP preset is one shape of SurfaceDriver — a preset that wires a specific MCP server (Notion / HubSpot / Atlassian / etc.) as an external-family surface. The directory name is descriptive of what's inside.

### 12.6 What about the "default local lake" SurfaceDriver?

`LocalLakeSurfaceDriver` (renamed from `LocalLakeConnector`) is the build-option for greenfield installs. Per §6.2, it bootstraps `~/.wormbase/lake/{bronze,silver,gold}/`. It is on-thesis and stays. The OSS quickstart should default to this surface when no chat-attached file or external credential is offered during onboarding.

### 12.7 Risks

| Risk | Mitigation |
|---|---|
| Rename creates merge conflicts with any in-flight feature branches | Run rename as a single coordinated commit; pause feature branches for ~2 hours; rebase post-merge |
| MCP alias confusion | Explicit migration doc; clear deprecation timeline; CI test that both names route to the same handler |
| ADR-0003 reads stale | Wave C includes ADR-0003 text update (D12) |
| Some doc misses the rename and reads inconsistently | Wave C grep-sweep over `docs/`; CI lint that catches `wormbase_connectors` / `class Connector(` in tracked files |
| User confusion ("I thought you had connectors") | Single migration doc; landing page explicitly maps "connector" → "lake surface" with a one-paragraph note for industry-vocabulary readers |

---

## 13. Acceptance criteria

The work is complete when:

1. ✅ Three new anchor docs exist (continuous-lake.md, lake-side-loops.md, ADR-0013) and pass internal review.
2. ✅ README + ARCHITECTURE + landing + DEVELOPERS all use the new vocabulary stack from §5 consistently.
3. ✅ The architecture diagram in README + landing matches §9.2 (lake at center, worm inside, surfaces as faces).
4. ✅ `packages/lake-surfaces/` exists, is the home of `SurfaceDriver` Protocol, AcquirableSource, MaintainableSource, all 15 concrete drivers, MCP presets, ConversationSource impl, EvidenceSource impl.
5. ✅ `packages/lake-maintainer/` imports Protocols from `lake-surfaces/`. Reactivity machinery + factory remain. No Protocol definitions remain in `lake-maintainer/`.
6. ✅ Every `from wormbase_connectors import …` callsite is updated.
7. ✅ Dashboard UI uses "Lake surfaces" / "Surface" everywhere; no "Connector" text remains in user-facing strings.
8. ✅ MCP tool names renamed with one-release alias; alias documented; CI verifies both routes.
9. ✅ Full regression passes: `pytest` for every Python package, `pnpm test` for dashboard, wire-replay tape determinism check.
10. ✅ ADR-0003 updated to reflect Protocols-rehomed.
11. ✅ Migration doc for early external MCP consumers exists at `docs/setup/migration-from-pre-rename.md`.
12. ✅ CI lint catches re-introduction of legacy names in tracked files.

---

## 14. Out of scope

- Adding new connectors / surfaces (existing 15 retained).
- Changing the Source-family enumeration (external/filedrop/conversation/evidence stays).
- Restructuring the ledger schema.
- Replacing the Reactivity machinery.
- Changes to onboarding flow logic (Wave D is a rename; the install paths are unchanged).
- Re-licensing (license is still TBD per existing README).
- Adding multi-tenancy beyond what exists (separate spec).
- Renaming `worm-core`, `ledger`, `governance`, `inference-router`, or any other package.
- Database migrations beyond optional `connector_kind` → `surface_driver_kind` (which is itself optional and aliased).

---

## 15. Cross-references

- **ADR-0003** (`docs/architecture/decisions/ADR-0003-lake-maintainer-pattern.md`) — Source Protocol split; Protocols move per this spec.
- **ADR-0013** (NEW, this spec) — Continuous-lake philosophy.
- **Lake-side compounding L1–L8 specs** in `docs/superpowers/specs/2026-05-28-…` through `2026-06-09-…` — Deep references for the 8 tending behaviors.
- **Conversation-provenance spec** (`docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md`) — Conversation as first-class source family.
- **Catalog-mirror Wave 2** entries in `docs/DELIVERY_LOG.md` — Per-connector extractor bundle.
- **CLAUDE.md** sections "Agentic source-building" and "Conversations as a first-class data source" — Internal product axioms that this spec instantiates publicly. (CLAUDE.md is in `/Users/ricalanis/Dev/wormbase-internal-archive/` post-OSS-hygiene; the public expression of these axioms is this spec + continuous-lake.md.)

---

## 16. Notes for the implementer

When this spec converts to a writing-plan:

- **Wave A and Wave D are independent.** Dispatch them as parallel subagents.
- **Wave B (README/ARCHITECTURE/landing rewrites) depends on Wave A's anchor docs.** Cross-references should land first.
- **Wave C is mostly serial polish.** Light parallelism possible (synthesis + orchestration files are file-disjoint).
- **Test regression is the rate-limit on Wave D.** Run pytest in parallel across packages; dashboard tests sequentially.
- **Wire-replay tape determinism MUST pass post-rename.** This proves the rename is pure refactoring; semantic behavior unchanged.
- **Do NOT introduce new entry kinds or projection columns during Wave D.** This is rename + framing, not feature work.

---

*End of spec.*
