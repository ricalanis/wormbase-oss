# ADR-0013: The continuous lake — agent-installable, co-emergent

**Status:** Accepted
**Date:** 2026-05-17

## Context

WormBase's OSS-facing surface (README, ARCHITECTURE.md §3, `landing/index.html`)
treats data sources as upstream input adapters that feed worm-core, with the
lake depicted as a downstream output. The reference architecture diagram
puts "Connector sources" at the bottom of the picture and points an arrow
into worm-core. The README narrates "GROW THE LAKE" as a one-time act in a
four-step operational arc. ARCHITECTURE.md titles its third section "The
Connector contract — data sources are pluggable." None of this matches what
the code actually does. The code treats Stripe / Postgres / Notion-via-MCP
not as upstream inputs but as **managed surfaces of a lake that is being
tended continuously**, from the moment of install.

The canonical references for the continuous-tending behaviors — the eight
lake-side compounding loops L1–L8 — live in `docs/superpowers/specs/`,
which reads as internal-looking. Readers landing on the OSS repo for the
first time never discover that eight loops are continuously running on
the lake. The vocabulary stack is misaligned with the architecture, the
mental model handed to readers is off-thesis, and the loops that
differentiate WormBase from every other product in this space are hidden.

The industry discourse compounds the problem. Every vendor in 2026
positions agentic maintenance as a **bolt-on layer over an existing
lake**. IBM and Acceldata sell "Agentic data management" as AI agents on
top of an existing platform. Snowflake's "self-driving" optimizes a
managed warehouse. Databricks ships "self-healing pipelines" inside its
lakehouse. Atlan and DataHub run "active metadata" against catalogs
provisioned elsewhere. Monte Carlo and Bigeye install "data
observability" as a layer above the data plane. Google Cloud's "AI-native
lakehouse" gets closest to co-design but still assumes the lakehouse was
provisioned first and agents are tenants who arrive after. The shared
assumption across all of them: the lake pre-exists; the agents arrive
after to maintain it.

WormBase's actual slot inverts that assumption. The lake exists *because*
the agent is tending it. Installation IS the first act of maintenance.
Chat-install brings the first managed surface (the conversation stream).
Lurking is bronze ingestion. Memory is lake state. The ledger projects
every surface's state from t=0. There is no lake before the agent. The
agent and the lake co-emerge. This is genuinely differentiated, and the
public framing should make it visible.

## Decision

WormBase commits to the **continuous lake** as the umbrella concept for
the OSS surface, and to **co-emergence** as the architectural commitment
that distinguishes it from bolt-on agentic data management. The thesis:

> WormBase is the agent-installable continuous lake. It installs into
> your chat platform (Slack / Discord / Teams) and into your data lake —
> either by **building** one (default local: csv / sqlite / parquet) or
> by **connecting** to your existing lake (Postgres warehouse, Snowflake,
> BigQuery, S3 lakehouse, Notion via MCP, etc.). Both paths end at the
> same state: a continuous, governed, agent-tended lake. From the moment
> of install, the lake is continuous and agent-operated. The agent and
> the lake co-emerge.

**Two installations.** Every install of WormBase is two install acts: a
**chat install** (acquires the user-side surface; the worm joins Slack /
Discord / Teams) and a **lake install** (build OR connect). The build
path bootstraps a default local lake; the connect path attaches an
existing lake (Postgres, Snowflake, BigQuery, S3, Notion-via-MCP, etc.).
Both paths produce a `Source` instance, both trigger the same
`propose → execute → verify → resolve → trace` ledger sequence, both
activate the same lake-side loops. The continuous lake is **federated by
default**: surfaces can live anywhere the SurfaceDriver can reach, and
the ledger projects state from all of them uniformly.

**Vocabulary stack.** The OSS surface adopts this locked vocabulary:

| Term | Definition |
|---|---|
| **The continuous lake** | The umbrella organism: a lake + its agent-tending behaviors, co-emergent from t=0. |
| **Surface** | A managed face of the continuous lake. User-facing word; dashboard tab title. |
| **SurfaceDriver** | The Protocol that concrete surface implementations subclass. Replaces the prior `Connector` Protocol. |
| **Lake surface** | Synonym for "Surface" when context is ambiguous. |
| **Source families** | The four families: `external`, `filedrop`, `conversation`, `evidence`. Each is a kind of surface. |
| **Lake-side loops** | The eight continuous tending behaviors (L1–L8). Each loop is one way the agent is continuously tending the lake's state. |
| **Tending** / **Tend** | The action the agent performs on the lake. Replaces "build," "manage," "consume." |
| **Co-emergent** | The agent and the lake come into being together. There is no lake before the agent installed. |
| **Build or connect** | Two paths to lake-install. Build (default local) or connect (existing lake). |

**Four source families as kinds of surfaces.** The four families
articulated in ADR-0003 — `external`, `filedrop`, `conversation`,
`evidence` — are rearticulated as kinds of managed surfaces of the
continuous lake. All four are equally lake-resident. None is more "real"
than the others. The conversation stream IS a source family that the
agent has been tending since chat-install (lurking equals bronze
ingestion); the evidence lake of autoresearch-published notebooks and
data products is a first-class surface, not an auxiliary stream.

**Eight lake-side loops as continuous tending behaviors.** L1–L8 are
rearticulated as the eight continuous tending behaviors that run
concurrently from t=0 of install: candidate-source triage, catalog-drift
detection, semantic-type inference, schema-impact analysis, column
fingerprinting, classification refresh, quality checking, and entity
stitching. Each loop produces ledger entries; cross-axis chains compose
them into multi-step inferences. They are not pipelines that need
self-healing; they are the agent tending the lake.

**Protocols home.** Per this decision, `AcquirableSource` and
`MaintainableSource` (introduced in ADR-0003) move from
`packages/lake-maintainer/` to `packages/lake-surfaces/`. The Protocols
belong with their surfaces; the maintainer becomes a consumer of the
Protocols, not their definer. ADR-0003's structural split is retained
unchanged — `AcquirableSource` for external + filedrop, `MaintainableSource`
for all four families — only its home moves. The dependency direction
becomes `lake-maintainer/` → `lake-surfaces/`. Conversation and Evidence
`MaintainableSource` implementations also move alongside the Protocols.

The driver class is renamed from `Connector` to `SurfaceDriver`.
Fifteen concrete drivers (`StripeConnector` → `StripeSurfaceDriver`,
`PostgresConnector` → `PostgresSurfaceDriver`, etc.) are renamed in
Wave D. MCP tool names rename with a one-release alias to lower
migration cost for external clients; aliases drop at v1.0.

## Consequences

### Positive

- The user's mental model now matches what the code actually does. The
  reader who lands on the OSS surface sees a continuous lake at the
  center, surfaces as faces, the worm as the tender inside the lake —
  the architecture that ships, not a pipeline diagram inherited from
  pre-agent framing.
- WormBase's positioning slot becomes legible and differentiated. The
  industry sells agentic maintenance as a bolt-on; WormBase sells the
  lake itself as agent-installable and co-emergent. "Continuous lake"
  and "co-emergent" are coinable phrases that name the differentiator.
- Vocabulary aligns end-to-end. `SurfaceDriver` in the Protocol matches
  "Surface" in the dashboard tab, "Lake surface" in the picker, "Tend"
  in the chat copy, "Two installations" in onboarding. No code-vs-UX
  vocabulary drift; engineers and end users read the same words.
- The eight lake-side loops surface as named, public, continuously-running
  tending behaviors. A reader can find L1–L8 from the README in two
  clicks, instead of digging through `superpowers/specs/`.

### Negative

- Wave D rename has a real blast radius. Fifteen concrete driver
  classes, the `Connector` Protocol, the `packages/connectors/` package
  directory, the Python module name, the dashboard catalog file, every
  TS import, every MCP preset, and every doc that mentions
  `wormbase_connectors` get touched in a single coordinated commit.
  Estimated 60–90 min wall-clock under parallel subagent dispatch.
- Readers migrate from "connector" to "lake surface" in vocabulary. The
  industry word for what we ship is "connector"; the rename trades
  industry-search-engine alignment for thesis-alignment. A migration
  doc maps the old word to the new for first-time readers carrying
  industry vocabulary.
- MCP tool aliases (`list_connectors` ↔ `list_lake_surfaces`, etc.)
  carry tech-debt for one release cycle (~6 weeks per current roadmap).
  Two names route to the same handler in the gateway; aliases drop at
  v1.0 cutover. CI verifies both routes during the alias window.
- ADR-0003 reads stale until its Protocols-home pointer is updated.
  Wave C includes the ADR-0003 text update and a cross-reference back
  to this ADR.

### Neutral

- Code semantics are unchanged. The rename is pure refactoring: identical
  Reactivity dispatch, identical ledger entries, identical projection
  reads, identical PEVR primitive. The wire-replay tape determinism
  check is the regression contract — a tape recorded pre-rename replays
  identically post-rename.
- ADR-0003's structural split (`AcquirableSource` + `MaintainableSource`,
  drop `watch()` from v1, compose with W5a Reactivity registry) is
  retained verbatim. Only the Protocols' home moves. The maintainer's
  Reactivity machinery (`wire_maintenance_for_source`, per-family
  factory, dispatch loop) stays in `lake-maintainer/`.
- Source-family enumeration (`external`, `filedrop`, `conversation`,
  `evidence`) is unchanged. The `Source` dataclass (per-instance, `id`,
  `domain`, `owner`) stays distinct from `SurfaceDriver` (the driver
  class, `kind="postgres"`). Conflating them would re-invent one or
  the other.

## Cross-references

- Related ADRs: **ADR-0003** (Lake-Maintainer package pattern — the
  Protocols' home moves per this decision; structural split retained);
  **ADR-0006** (the four-wire boot path — lake-maintainer remains
  per-source-wired, not per-install-wired, post-rename); **ADR-0011**
  (multi-tenancy — every surface is `company_id`-scoped through the
  same ledger substrate this decision re-frames).
- Related specs: **design spec** at
  `docs/superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md`
  (§3 industry positioning, §4 thesis, §5 vocabulary, §10 rename scope,
  §11 wave plan); lake-side compounding **L1–L8 specs** in
  `docs/superpowers/specs/2026-05-28-…` through `2026-06-09-…`;
  **conversation-provenance spec** at
  `docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md`
  (conversation as a first-class source family).
- Sister docs: `docs/architecture/continuous-lake.md` (umbrella
  narrative; corrected architecture diagram; two-installations
  articulation); `docs/architecture/lake-side-loops.md` (public-friendly
  L1–L8 reference; cross-axis chains).
- Architecture: `ARCHITECTURE.md` §3 (re-anchored on the continuous lake
  post-Wave B; replaces the prior "Connector contract" framing).
