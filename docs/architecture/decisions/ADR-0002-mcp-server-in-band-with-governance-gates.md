# ADR-0002: Agent Gateway as in-band MCP server with governance gates

**Status:** Accepted
**Date:** 2026-04-27

## Context

Institutional AI requires that every external query into the substrate be
auditable, deterministic, and governable by the same rules that govern
internal writes. WormBase exposes an Agent Gateway that lets external
agents query the ledger, projections, KPIs, decisions, processes, and data
products via the Model Context Protocol (MCP).

Two architectural shapes were possible: an out-of-band MCP server that
proxies into the worm-core HTTP API, or an in-band MCP server that runs
inside the worm-core process and writes its audit entries through the same
PEVR primitive as every other ledger write. The latter aligns with the
project's "every write is PEVR; the gate is the trust boundary" principle;
the former would have created a parallel write path with separate audit
semantics.

A round-trip latency budget of 500ms per simple query was the initial SLO,
chosen to allow ample headroom for governance gating, projection reads, and
network hops.

## Decision

WormBase ships an **in-band MCP server** based on FastMCP (built into the
official `mcp` SDK), running inside the worm-core process. Every MCP tool
call writes a PEVR-wrapped `mcp_call_received` ledger entry — propose,
execute, verify, resolve — identical in shape to every other admin write.

The server uses `FastMCP(stateless_http=True, json_response=True)` for
hosted multi-tenant deployment. Each tool call's payload carries a canonical
`args_hash` (sha256 of sorted-keys canonical JSON), enabling replay-stable
audit and privacy-preserving comparison across calls (the audit doesn't leak
whether the call was crafted to extract PII).

Bearer-token authentication gates the inbound path. A denied call still
writes an `mcp_call_received` entry with `outcome: "denied"` and the same
`args_hash` shape — no information leaks in the rejection path.

Every Phase 1+ tool (`query_kpis`, `query_decisions`, `query_processes`,
`query_data_products`, `query_conversations`, plus write tools) drives the
same `record_mcp_call` orchestrator. Tool-specific detail goes into the
`args_hash` body, never into a new audit kind, keeping `projection_mcp_calls`
a single uniform surface for the audit dashboard.

The empirical evaluation of this shape measured median 3.7ms / p95 4.4ms
in-process round-trip latency across `query_ledger` calls — approximately
100× under the 500ms SLO.

## Consequences

**Positive:**

- One audit primitive for both internal and external writes. The ledger
  records every MCP call with full PEVR provenance.
- Stateless HTTP posture matches the 2026 MCP roadmap for hosted multi-tenant
  servers. No session manager required; multi-tenancy is encoded in the
  bearer token's tenant claim.
- Latency headroom is generous enough to ship the full 5-7 tool surface
  without latency-engineering anxiety. The dominant cost in production is
  Postgres `fetch_entries`, not MCP overhead.
- The `args_hash` shape is replay-stable: identical args produce identical
  hashes; only per-call UUIDs and timestamps differ across replays.
- The ledger is the OpenTelemetry substitute. Every call's shape lives in
  `projection_mcp_calls`; the dashboard's audit tab folds that table
  directly. OTel can be wired later with a one-line change if required.

**Negative:**

- The MCP server runs in-process, which couples its lifecycle to worm-core
  and shares the same crash blast radius. A standalone MCP frontier would
  require splitting the process boundary.
- Each MCP call performs a ledger fetch as part of authorization, adding
  one Postgres round-trip even when the call is cache-eligible. Phase 1+ can
  index `(company_id, ts DESC)` if needed, or serve from `projection_*`
  tables for high-frequency reads.
- Bearer tokens in v1 are not yet scoped to a `Person` row. The payload
  shape supports `caller_person_id: UUID | None` for non-breaking upgrade
  once `/settings/tokens` mints Person-bound tokens.

**Neutral:**

- The MCP server is off by default. `WORMBASE_MCP_ENABLED=1` plus the
  docker-compose port-pin is the opt-in posture for Phase 0/1. A future
  decision will flip it to default-on once the official MCP Registry path
  is ready.
- The SDK emits a `DeprecationWarning` on `streamablehttp_client` (renamed
  to `streamable_http_client`); WormBase tracks the rename when the new
  symbol becomes the stable recommendation.

## Cross-references

- Related ADRs: ADR-0001 (the ledger is the audit substrate the MCP server
  writes into); ADR-0011 (multi-tenant token scoping closes the v1 caller
  resolution gap).
- Related specs: `docs/superpowers/specs/2026-04-27-mcp-integration.md`.
- Architecture: `ARCHITECTURE.md` §1 ("The substrate: PEVR + ledger +
  projections") establishes the write primitive every MCP call extends.
