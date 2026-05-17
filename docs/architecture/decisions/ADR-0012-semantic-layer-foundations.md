# ADR-0012: Semantic layer foundations — catalog mirror, broker, and MCP audit chain

**Status:** Accepted
**Date:** 2026-05-10

## Context

WormBase's semantic layer extends the lake substrate from "what data
exists" to "what data means, how to query it, and who is allowed." Six
foundational design assumptions had to be validated against real
infrastructure before committing to a multi-wave plan:

1. dbt manifest → CatalogSnapshot lossless round-trip (catalog ingest
   from the most common warehouse-modeling tool).
2. Snowflake `INFORMATION_SCHEMA` reads for tags and masking policies
   (governance metadata preserved through the catalog mirror).
3. In-process MCP client → tool round-trip plus an `agent_query` PEVR
   chain plus an `inference_served` follow-on linked via `caused_by`
   (the dissolved-seam contract for query-time audit).
4. A `CredentialBroker` Protocol with a Vault backend serving both data
   and model credentials from one storage layer (unified broker amendment
   2026-05-10).
5. Lake-maintainer's existing `MaintainableSource` Protocol accommodating
   a dual-mode toggle (`wormbase_owned` vs `upstream_mirror`) without
   Protocol breakage.
6. Inference router extension with `AgentID` boundary-conversion plus
   `governance_context` plus a cache-key allow-list (so cache keys don't
   regress when new request fields land).

Each assumption was tested empirically against running infrastructure.

## Decision

All six assumptions validated **GO** (20/20 spike tests pass end-to-end).
The semantic layer proceeds with these architectural commitments:

### Catalog ingest is whitelist-by-resource-type, not model-only

The dbt manifest parser must treat both `model` and `seed` nodes as
tables (and likely sources, snapshots, exposures). The first cut filtered
to `resource_type == "model"`, which silently lost lineage because seeds
appeared as upstreams of staging models. The production parser carries an
explicit table-resource-types whitelist with tests.

### Snowflake catalog mirror reads via a two-step DESCRIBE pattern

`INFORMATION_SCHEMA.POLICY_REFERENCES` does **not** include `POLICY_BODY`
despite docs examples implying otherwise. The catalog mirror fetches the
reference set via `POLICY_REFERENCES`, then issues `DESCRIBE <KIND>
POLICY <fqn>` per policy to read the body. Cost is `O(tables) +
O(policies)`; production caches by `(policy_db, policy_schema,
policy_name, last_altered)`.

### MCP audit chain uses `caused_by` for query → inference linkage

Each MCP tool call writes an `agent_query` PEVR cycle. The router's
follow-on inference call writes an `inference_served` entry that
references the audit via `caused_by=<audit_id>`. This is the
dissolved-seam contract: every query is audit-complete, and every model
call is traceably caused by an auditable query.

### CredentialBroker is one Protocol, two upstream kinds, one Vault backend

The broker stores both data creds (snowflake) and model creds (kimi) at
the same `data/<upstream_kind>/<install_id>` path convention. One
`read_secret_version` code path serves both `hold_data_account` and
`hold_model_account`; the only difference is the returned
`AccountHandle.kind` tag. AWS Secrets Manager and customer KMS impls
follow the same Protocol shape.

### Lake-maintainer dual-mode is Source-instance type, not runtime branch

`source_mode` is a Source-instance attribute, not a Protocol-level
concern. The existing `wormbase_owned` Source families
(`AcquirableSourceImpl`, `ConversationSource`, `EvidenceSource`) get a
new sibling: `UpstreamMirrorSource`. The `SourceFamily` Literal extends
additively (or gets a parallel `SourceMode` axis). The W5a runner /
registry / Reactivity primitives remain unchanged.

### Router extension is boundary-conversion, not call-site sweep

`requested_by` retypes from `str = "unknown"` to `AgentID` **inside the
Router**, before emitting `inference_served`. Avoids touching every
call-site (chat-presence, process-extractor, voice-agent) at once.
`slots=True` on the existing `RouteRequest` blocks `__post_init__`
coercion, so boundary-conversion is the cleanest path. `_CACHE_KEY_FIELDS`
moves to a `ClassVar[tuple[str, ...]]` on `RouteRequest` with an
import-time assertion `set(_CACHE_KEY_FIELDS) <= {f.name for f in
fields(RouteRequest)}` to prevent silent drift when new fields land.

## Consequences

**Positive:**

- The semantic layer's foundations are all empirically validated against
  running infrastructure. No assumption survives into Wave 1 untested.
- Three production-Protocol path corrections discovered empirically (S5:
  module path is `protocols` plural, not `protocol`; S5: methods return
  typed dataclasses, not `dict`; S6: `requested_by` is already
  `str = "unknown"`) get baked into the Wave 1 plan rather than
  discovered mid-execution.
- Cache-key drift is preventable: the import-time assertion catches new
  `RouteRequest` fields that silently fall outside the allow-list.
- One CredentialBroker backend serves both data and model creds; the
  unified-broker amendment holds at the storage layer. Multi-tenancy via
  `install_id` UUID per `(tenant, upstream)` reuses the existing
  `Install` shape.

**Negative:**

- The model-only filter trap in dbt manifest parsing is real and silent
  if not tested. The Wave 1 parser must keep the whitelist explicit and
  the test fixture honest (jaffle_shop alone catches it; a separate
  MetricFlow fixture is needed for `semantic_models` / `metrics`
  coverage).
- The two-step DESCRIBE pattern for Snowflake policy bodies means refresh
  cost scales with policy count, not just table count. Caching by
  `last_altered` is on the critical path for tenants with thousands of
  policies.
- OAuth is the recurring production gap across multiple spikes (Snowflake
  password vs OAuth; Vault dev mode vs sealed production; Ollama
  Cloud's single-per-tenant key). Each Wave 1+ component must include
  OAuth registration as a tenancy-admin install step.
- The §4.5 compounding-loop amendment introduced `projection_query_outcomes`
  + `projection_query_templates` with `VECTOR(1536)` columns. The
  workspace Postgres deploy must include `pgvector ≥ 0.6`.

**Neutral:**

- The §4.5 compounding query layer doesn't need its own spike: PEVR is
  the loop (confirmed via the MCP audit chain) and the
  `agent_query → inference_served` chain via `caused_by` is empirically
  green.
- The `ServedBy` Literal already contains `"claude"` as a pre-amendment
  artifact. Kept for ledger provenance of external-agent-served content
  (the field documents which model produced this, not which client
  WormBase invoked).
- The kind registry sits at the doorstep of the raised ~100 threshold
  after Wave 2's 8 additional kinds. The freeze-pause review must trigger
  before Wave 2 dispatch — Wave 1 plan flags this; Wave 2 plan executes
  the review.

## Cross-references

- Related ADRs: ADR-0002 (MCP server whose audit chain this decision
  extends to query-time); ADR-0003 (lake-maintainer's `MaintainableSource`
  Protocol whose dual-mode this extends additively); ADR-0010 (the
  doctrine cycle that gates new entry kinds).
- Related specs: `docs/superpowers/specs/2026-05-10-semantic-layer-design.md`.
- Architecture: `ARCHITECTURE.md` §1 ("The substrate") and §3 ("The
  Connector contract") establish the surfaces this decision extends.
