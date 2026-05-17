"""Pure-function projection builder over the ledger.

Reads entries from the `ledger` table and folds them into deterministic
state: `sources`, `memory`, `kpi_nodes`, and the six-axis `ramp`. All output
collections are sorted by stable keys so two replays with identical inputs
produce byte-identical projections (this is the foundation of the Task 12
10x determinism gate).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from wormbase_ledger.repo import fetch_entries
from wormbase_ledger.schema import (
    projection_agent_grants,
    projection_agent_queries,
    projection_agents,
    projection_column_classifications,
    projection_credentials,
    projection_data_product_consumption,
    projection_data_product_runs,
    projection_data_products,
    projection_entity_stitches,
    projection_external_catalog,
    projection_external_lineage,
    projection_external_metric,
    projection_external_policy,
    projection_installs,
    projection_kpi_nodes,
    projection_lineage_edges,
    projection_mcp_calls,
    projection_memory,
    projection_notebook_runs,
    projection_notebooks,
    projection_person_identities,
    projection_persons,
    projection_quality_checks,
    projection_query_outcomes,
    projection_query_templates,
    projection_ramp,
    projection_roles,
    projection_schema_impacts,
    projection_semantic_types,
    projection_setup_progress,
    projection_catalog_drifts,
    projection_catalog_tables,
    projection_source_candidates,
    projection_sources,
    projection_topics,
)

# Deterministic axis order — also defines the ramp UI ordering.
RAMP_AXES: tuple[str, ...] = (
    "ontology",
    "schema",
    "business_definitions",
    "kpi_relational",
    "conversational",
    "operational",
)


@dataclass(frozen=True)
class Projections:
    sources: list[dict[str, Any]] = field(default_factory=list)
    memory: list[dict[str, Any]] = field(default_factory=list)
    kpi_nodes: list[dict[str, Any]] = field(default_factory=list)
    ramp: list[dict[str, Any]] = field(default_factory=list)
    persons: list[dict[str, Any]] = field(default_factory=list)
    person_identities: list[dict[str, Any]] = field(default_factory=list)
    installs: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)
    data_products: list[dict[str, Any]] = field(default_factory=list)
    data_product_runs: list[dict[str, Any]] = field(default_factory=list)
    data_product_consumption: list[dict[str, Any]] = field(default_factory=list)
    notebooks: list[dict[str, Any]] = field(default_factory=list)
    notebook_runs: list[dict[str, Any]] = field(default_factory=list)
    setup_progress: list[dict[str, Any]] = field(default_factory=list)
    mcp_calls: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    # Catalog-mirror Wave 1: one row per (source_id, snapshot_hash) for
    # ``external_catalog_imported`` and one row per edge tuple for
    # ``external_lineage_imported``.
    external_catalog: list[dict[str, Any]] = field(default_factory=list)
    external_lineage: list[dict[str, Any]] = field(default_factory=list)
    # Catalog-mirror Wave 1 (Wave 3 Task 6 dashboard surface):
    #   * ``external_policy`` — one row per upstream masking / row-access
    #     policy, keyed on ``(company_id, source_id, policy_fqn)``.
    #     ``body`` is NULLABLE per the S2 spike — read-only catalog roles
    #     lack APPLY privilege and cannot fetch the policy SQL.
    #   * ``external_metric`` — one row per semantic-layer metric
    #     definition, keyed on ``(company_id, source_id, name)``. Re-emits
    #     upsert in place; a metric rename is a new row.
    external_policy: list[dict[str, Any]] = field(default_factory=list)
    external_metric: list[dict[str, Any]] = field(default_factory=list)
    # Agent-gateway Wave 2/3 Task 2: one row per registered agent and
    # one row per (agent_id, grant_kind, grant_target) triple. Per
    # Addendum 3, status field consolidates assign + revoke on the
    # same row — a re-emit flips status rather than appending.
    agents: list[dict[str, Any]] = field(default_factory=list)
    agent_grants: list[dict[str, Any]] = field(default_factory=list)
    # Wave 3 Task 3 (SOC-2 credibility view):
    #   * ``agent_queries`` — one row per ``agent_query`` PEVR cycle
    #     keyed on ``audit_trail_id``; all four phase rows fold into
    #     the same row; ``status`` advances propose → execute →
    #     verify → resolve (or terminal ``denied`` on gate-fire).
    #   * ``credentials`` — one row per credential lifecycle event,
    #     threaded across four PEVR phases via write_primitive's
    #     linkage fields.
    agent_queries: list[dict[str, Any]] = field(default_factory=list)
    credentials: list[dict[str, Any]] = field(default_factory=list)
    # §4.5 compounding loop (Wave 3 Task 4 — /lake/query-improvement):
    #   * ``query_outcomes`` — one row per ``query_outcome_recorded``
    #     execute entry. Keyed on the execute entry_id so re-emit-by-
    #     uuid is idempotent. Folded from canonical-PEVR writes via
    #     ``tool="emit_query_outcome_recorded"`` (matches Wave 2 Task 8
    #     OutcomeToTemplatePromotion's predicate contract).
    #   * ``query_templates`` — one row per ``query_template_promoted``
    #     propose-phase entry. The OutcomeToTemplatePromotion Reactivity
    #     writes a typed-payload PEVR (no ``tool`` wrapping); fold
    #     detects by payload shape (``nl_intent`` +
    #     ``promoted_from_outcome_ids`` co-occurrence).
    query_outcomes: list[dict[str, Any]] = field(default_factory=list)
    query_templates: list[dict[str, Any]] = field(default_factory=list)
    # L3 Sub-wave A — lake-side lineage-discovery loop. One row per
    # ``(company_id, edge_id)`` pair, folded from the three
    # ``lineage_edge_*`` ledger kinds. ``state`` advances forward-only
    # via new ledger entries; the fold is replay-stable because the
    # composite PK collapses re-proposal onto the same projection row.
    lineage_edges: list[dict[str, Any]] = field(default_factory=list)
    # L7 Sub-wave A — lake-side quality-checks discovery loop. One row
    # per ``(company_id, check_id)`` pair, folded from the three
    # ``quality_check_*`` ledger kinds. Structurally identical to
    # ``lineage_edges`` — same forward-only fold semantics, same
    # composite-PK replay stability.
    quality_checks: list[dict[str, Any]] = field(default_factory=list)
    # L4 Sub-wave A — lake-side schema-evolution-impact discovery loop.
    # One row per ``(company_id, impact_id)`` pair, folded from the
    # three ``schema_impact_*`` ledger kinds. Structurally identical
    # to ``lineage_edges`` and ``quality_checks`` — same forward-only
    # fold semantics, same composite-PK replay stability.
    schema_impacts: list[dict[str, Any]] = field(default_factory=list)
    # L5 Sub-wave A — lake-side sample-data fingerprinting discovery
    # loop. One row per ``(company_id, type_id)`` pair, folded from
    # the three ``semantic_type_*`` ledger kinds. Structurally
    # identical to ``lineage_edges`` / ``quality_checks`` /
    # ``schema_impacts`` — same forward-only fold semantics, same
    # composite-PK replay stability.
    semantic_types: list[dict[str, Any]] = field(default_factory=list)
    # L6 Sub-wave A — lake-side column-level governance classification
    # discovery loop. One row per ``(company_id, classification_id)``
    # pair, folded from the three ``column_classification_*`` ledger
    # kinds. Structurally identical to ``lineage_edges`` /
    # ``quality_checks`` / ``schema_impacts`` / ``semantic_types`` —
    # same forward-only fold semantics, same composite-PK replay
    # stability. Rows may carry a non-NULL
    # ``upstream_semantic_type_id`` linking back to L5 when the
    # proposing strategy was ``semantic_type`` (the L6→L5 cross-axis
    # chain).
    column_classifications: list[dict[str, Any]] = field(default_factory=list)
    # L8 Sub-wave A — lake-side cross-source entity-stitch discovery
    # loop. One row per ``(company_id, stitch_id)`` pair, folded from
    # the three ``entity_stitch_*`` ledger kinds. Structurally
    # identical to ``lineage_edges`` / ``quality_checks`` /
    # ``schema_impacts`` / ``semantic_types`` / ``column_classifications`` —
    # same forward-only fold semantics, same composite-PK replay
    # stability. Rows may carry a non-NULL
    # ``upstream_semantic_type_id`` linking back to L5 when the
    # proposing strategy consulted a confirmed semantic type (the
    # L8→L5 cross-axis chain shared with L6).
    entity_stitches: list[dict[str, Any]] = field(default_factory=list)
    # L1 Sub-wave A — lake-side source-candidate triage loop. One row
    # per ``(company_id, candidate_id)`` pair, folded from the three
    # ``source_candidate_*`` ledger kinds. Structurally identical to
    # ``lineage_edges`` / ``quality_checks`` / ``schema_impacts`` /
    # ``semantic_types`` / ``column_classifications`` /
    # ``entity_stitches`` — same forward-only fold semantics, same
    # composite-PK replay stability. Rows may carry a non-NULL
    # ``downstream_source_proposed_id`` threading the candidate to its
    # resulting source-pipeline row when promoted (NOT a peer-L-axis
    # cross-axis link; it points downstream into the existing
    # source-pipeline lifecycle).
    source_candidates: list[dict[str, Any]] = field(default_factory=list)
    # L2 Sub-wave A — lake-side catalog-drift detection loop. One row
    # per ``(company_id, drift_id)`` pair, folded from the three
    # ``catalog_drift_*`` ledger kinds. Structurally identical to
    # ``source_candidates`` above — same forward-only fold semantics,
    # same composite-PK replay stability. Uses ``acknowledged`` as the
    # affirmative state (no downstream pipeline trigger, no cross-axis
    # effect — L2 records human-in-the-loop disposition only). L2 is
    # the FINAL planned axis in this generation per spec §11.
    catalog_drifts: list[dict[str, Any]] = field(default_factory=list)
    # Catalog-mirror Wave 2 Sub-wave A — per-table column metadata
    # substrate. One row per ``(company_id, source_id, table_id,
    # snapshot_hash)`` tuple, folded from the ``catalog_table_imported``
    # ledger kind. Carries the per-column ``CatalogColumnSpec`` list as
    # a JSON column. Substrate-only: unblocks L2 TableSet + L8
    # SchemaShape productivity (each snapshot's table set + per-table
    # column lists become first-class ledger-resident state). Same
    # logical (source, table) across multiple snapshots is multiple
    # rows because each snapshot is a point-in-time — the
    # snapshot_hash leg of the composite PK keeps them isolated.
    catalog_tables: list[dict[str, Any]] = field(default_factory=list)


def grants_for(projections: Projections, person_id: UUID) -> list[dict[str, Any]]:
    """Return all unrevoked role grants for a Person across every facet.

    The /people surface uses this to render a Person's full role surface as
    a flat join over the three independent facets (tenancy, domain, resource).
    Sorted by ``(facet, role, scope_id)`` for deterministic UI output.
    """
    grants = [
        g
        for g in projections.roles
        if g["person_id"] == person_id and g["revoked_at"] is None
    ]
    return sorted(
        grants,
        key=lambda g: (
            g["facet"],
            g["role"],
            "" if g["scope_id"] is None else str(g["scope_id"]),
        ),
    )


def _identity_uuid(*parts: str) -> UUID:
    """Deterministic identity_id from (tenant, platform, platform_user_id).

    PersonIdentity rows must be byte-identical across replays for the
    determinism gate, so we derive the UUID from the natural unique key
    rather than calling uuid4().
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    # Construct a UUID from the first 16 bytes of the hash; bit-stable.
    return UUID(bytes=h[:16])


def _role_grant_uuid(*parts: str) -> UUID:
    """Deterministic grant_id keyed on (tenant, person, facet, role, scope, seq).

    Including ``seq`` distinguishes repeat grants of the same role to the
    same person without colliding (admin-revoked-then-readded). Replay
    determinism holds because seq is itself replay-stable.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _data_product_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (tenant, data_product_id, seq).

    Used for ``data_product_runs`` (run_id is in the payload, but the seq
    breaks ties when replay produces multiple runs at the same id) and
    ``data_product_consumption`` (consumption_id derived from the
    consume entry's seq).
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _notebook_run_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (tenant, notebook_id, seq).

    Mirrors ``_data_product_uuid``. Used when the notebook_run payload's
    run_id is in the JSON body but the projection row id needs to be
    bit-stable for the determinism gate.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _external_catalog_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (company, source_id, snapshot_hash).

    Replay-stable: re-running the projection builder over the same ledger
    stream produces byte-identical ``id`` columns for the same
    ``external_catalog_imported`` execute entry. Re-imports of the same
    snapshot (same source_id + same snapshot_hash, e.g. a no-op refresh)
    collapse to the same row by design.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _external_lineage_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (company, source_id, upstream, downstream).

    Per-edge stable id: a re-import that includes the same edge tuples
    lands on the same row, supporting the tenant-scoped delete+insert
    persist pattern without breaking referential stability for downstream
    consumers (lineage tab, drift diff).
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _external_policy_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (company, source_id, policy_fqn).

    Re-import of the same policy fqn upserts in place; a rename produces
    a new row. Matches the v010 SQL ``UNIQUE`` index on
    ``(source_id, policy_fqn)``.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _external_metric_uuid(*parts: str) -> UUID:
    """Deterministic projection-row id keyed on (company, source_id, name).

    Re-import of the same metric name upserts in place; a rename produces
    a new row. Matches the v011 SQL ``UNIQUE`` index on
    ``(source_id, name)``.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16])


def _agent_grant_uuid(*parts: str) -> str:
    """Deterministic projection-row id keyed on (company, agent_id, grant_kind, grant_target).

    Returns a hex string (not a UUID instance) because the v013 schema
    column is String. Replay-stable: a re-emit of the SAME triple
    (with status flipping active to revoked per Addendum 3) lands on the
    same row id, so the projection-fold cleanly upserts on revoke.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16]).hex


def _query_outcome_uuid(*parts: str) -> str:
    """Deterministic projection-row id for ``query_outcome_recorded``.

    Keyed on (company_id, execute_entry_id). Re-emit of the SAME
    execute row (replay) lands on the same projection row; a new
    outcome (different execute entry_id) is a new row. The v016
    schema column is ``String``, so we return hex.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16]).hex


def _query_template_uuid(*parts: str) -> str:
    """Deterministic projection-row id for ``query_template_promoted``.

    Keyed on (company_id, propose_entry_id). The
    OutcomeToTemplatePromotion Reactivity dedups on
    ``(domain_id, canonical_nl_intent)`` BEFORE writing, so a single
    propose entry maps 1:1 with one promotion. The v017 schema
    column is ``String``, so we return hex.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16]).hex


def _parse_topic_ts(raw: Any) -> datetime:
    """Parse a topic_proposed timestamp arg.

    The Reactivity hands ISO-8601 strings to the ledger writer; on
    replay these come back as strings and need rehydration. Native
    datetimes pass through unchanged. Naive timestamps are coerced to
    UTC — defensive only, the payload validator already requires
    tz-aware in writes.
    """
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str) and raw:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    raise ValueError(f"unparseable topic ts: {raw!r}")


def _credential_uuid(*parts: str) -> str:
    """Deterministic projection-row id keyed on (company_id, propose_entry_id).

    Credentials write a 4-entry PEVR cycle per lifecycle event; the
    propose entry's UUID is the natural anchor for the cycle. Returns
    hex to match the v015 schema's ``String`` primary key.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16]).hex


def _parse_iso_ts(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp arg, returning None on any failure."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str) and raw:
        try:
            normalized = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _is_agent_query_payload(payload: dict[str, Any]) -> bool:
    """Recognize an agent_query PEVR envelope by its payload shape.

    Detection key: co-occurrence of ``audit_trail_id``, ``phase``,
    ``mcp_tool``, ``route_mode`` — fields unique to the AgentQueryPayload
    (single-kind-with-phase per Addendum 3).
    """
    if not isinstance(payload, dict):
        return False
    return (
        "audit_trail_id" in payload
        and "phase" in payload
        and "mcp_tool" in payload
        and "route_mode" in payload
    )


def _is_credential_payload(payload: dict[str, Any]) -> bool:
    """Recognize a credential PEVR envelope by its payload shape.

    Detection key: ``credential_kind`` ∈ {data, model} plus
    ``ttl_expires_at`` plus ``issued_by`` — these co-occur only on
    CredentialPayload rows.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("credential_kind") not in ("data", "model"):
        return False
    return "ttl_expires_at" in payload and "issued_by" in payload


def _is_query_template_promoted_payload(payload: dict[str, Any]) -> bool:
    """Recognize a ``query_template_promoted`` PEVR envelope by payload shape.

    The OutcomeToTemplatePromotion Reactivity writes a typed-payload
    PEVR (NOT the canonical ``{tool: emit_*, args: ...}`` envelope) —
    payload fields land directly on the envelope. Detection key:
    co-occurrence of ``nl_intent`` + ``promoted_from_outcome_ids`` +
    ``query_spec``, the three fields unique to the
    ``QueryTemplatePromotedPayload`` shape.
    """
    if not isinstance(payload, dict):
        return False
    return (
        "nl_intent" in payload
        and "promoted_from_outcome_ids" in payload
        and "query_spec" in payload
    )


def _apply_pevr_envelope(entry: dict[str, Any], state: dict[str, Any]) -> None:
    """Fold an ``agent_query`` or ``credential`` PEVR envelope entry.

    Runs for every PEVR envelope kind {propose, execute, verify, resolve};
    dispatches via payload-shape detection so normal ``emit_*`` writes
    fall through to ``_apply_execute``.
    """
    payload = entry.get("payload") or {}
    envelope_kind = entry["kind"]

    if _is_agent_query_payload(payload):
        audit_id = payload["audit_trail_id"]
        existing = state["agent_queries"].get(audit_id)
        if existing is None:
            state["agent_queries"][audit_id] = {
                "id": audit_id,
                "company_id": str(entry["company_id"]),
                "agent_id": payload["agent_id"],
                "mcp_tool": payload["mcp_tool"],
                "args": payload.get("args", {}),
                "route_mode": payload["route_mode"],
                "status": payload.get("phase", envelope_kind),
                "row_count": payload.get("row_count"),
                "cost_usd": payload.get("cost_usd"),
                "latency_ms": payload.get("latency_ms"),
                "caused_by": payload.get("caused_by"),
                "started_at": entry["ts"],
            }
        else:
            existing["status"] = payload.get("phase", envelope_kind)
            for field_name in ("row_count", "cost_usd", "latency_ms"):
                v = payload.get(field_name)
                if v is not None:
                    existing[field_name] = v
            if payload.get("caused_by") is not None:
                existing["caused_by"] = payload["caused_by"]
        return

    if _is_credential_payload(payload):
        prior_ref = (
            payload.get("verify_entry_id")
            or payload.get("execute_entry_id")
            or payload.get("propose_entry_id")
        )
        if envelope_kind == "propose":
            row_id = _credential_uuid(
                str(entry["company_id"]), str(entry["entry_id"]),
            )
            state["credential_chain"][str(entry["entry_id"])] = row_id
            state["credentials"][row_id] = {
                "id": row_id,
                "company_id": str(entry["company_id"]),
                "agent_id": payload["agent_id"],
                "credential_kind": payload["credential_kind"],
                "target": payload["target"],
                "status": payload["status"],
                "ttl_expires_at": _parse_iso_ts(payload["ttl_expires_at"]),
                "issued_by": payload["issued_by"],
                "issued_at": entry["ts"],
            }
        else:
            row_id = state["credential_chain"].get(str(prior_ref or ""))
            if row_id is None:
                row_id = _credential_uuid(
                    str(entry["company_id"]), str(entry["entry_id"]),
                )
                state["credentials"][row_id] = {
                    "id": row_id,
                    "company_id": str(entry["company_id"]),
                    "agent_id": payload["agent_id"],
                    "credential_kind": payload["credential_kind"],
                    "target": payload["target"],
                    "status": payload["status"],
                    "ttl_expires_at": _parse_iso_ts(payload["ttl_expires_at"]),
                    "issued_by": payload["issued_by"],
                    "issued_at": entry["ts"],
                }
            state["credential_chain"][str(entry["entry_id"])] = row_id
            existing = state["credentials"].get(row_id)
            if existing is not None:
                existing["status"] = payload["status"]
                ttl = _parse_iso_ts(payload["ttl_expires_at"])
                if ttl is not None:
                    existing["ttl_expires_at"] = ttl
                if envelope_kind == "resolve":
                    existing["issued_at"] = entry["ts"]
        return

    if _is_query_template_promoted_payload(payload):
        # --------------------------------------------------------------
        # === §4.5 compounding loop — query_template_promoted fold ===
        #
        # The OutcomeToTemplatePromotion W5a Reactivity writes one
        # 4-phase PEVR per cluster promotion, with the
        # ``QueryTemplatePromotedPayload`` fields landing directly on
        # the envelope (no ``tool/args`` wrapping). All four phases
        # carry the SAME payload body; we anchor on the propose phase
        # (= 1 row per cluster promotion). verify/execute/resolve are
        # no-ops on the projection side because the Reactivity is
        # observation-only at the promote step — the propose IS the
        # side-effect.
        # --------------------------------------------------------------
        if envelope_kind != "propose":
            return
        row_id = _query_template_uuid(
            str(entry["company_id"]), str(entry["entry_id"]),
        )
        promoted_ids = payload.get("promoted_from_outcome_ids", []) or []
        # pydantic round-trips tuples as lists across JSON; accept
        # both so the fold sees the same shape as the in-memory write.
        if isinstance(promoted_ids, (list, tuple)):
            promoted_ids_list = [str(x) for x in promoted_ids]
        else:
            promoted_ids_list = []
        query_spec = payload.get("query_spec") or {}
        if not isinstance(query_spec, dict):
            query_spec = {}
        state["query_templates"][row_id] = {
            "id": row_id,
            "company_id": str(entry["company_id"]),
            "domain_id": str(payload.get("domain_id") or ""),
            "nl_intent": str(payload.get("nl_intent") or ""),
            "query_spec": query_spec,
            "promoted_from_outcome_ids": promoted_ids_list,
            "quality_score": str(payload.get("quality_score") or "0"),
            "hit_count": 0,
            "promoted_at": entry["ts"],
        }
        return


def _apply_execute(entry: dict[str, Any], state: dict[str, Any]) -> None:
    payload = entry["payload"]
    tool = payload.get("tool")
    args = payload.get("args", {})

    if tool == "emit_source_proposed":
        sid = args["source_id"]
        state["sources"][sid] = {
            "source_id": UUID(sid),
            "status": "proposed",
            "kind": args["source_kind"],
            "uri": args["uri"],
            "classification": args["suggested_classification"],
            "domain_id": None,
            "added_by_person": None,
            "added_via_flow": args["added_via_flow"],
            "added_at": entry["ts"],
            "last_entry_hash": entry["hash"],
        }
    elif tool == "emit_source_confirmed":
        sid = args["source_id"]
        if sid in state["sources"]:
            s = state["sources"][sid]
            s.update(
                {
                    "status": "confirmed",
                    "domain_id": UUID(args["domain_id"]) if args.get("domain_id") else None,
                    "classification": args.get("classification", s["classification"]),
                    "added_by_person": UUID(args["confirmed_by_person"]),
                    "last_entry_hash": entry["hash"],
                }
            )
    elif tool == "emit_source_connected":
        sid = args["source_id"]
        if sid in state["sources"]:
            state["sources"][sid]["status"] = "connected"
            state["sources"][sid]["last_entry_hash"] = entry["hash"]
    elif tool == "emit_source_profiled":
        sid = args["source_id"]
        if sid in state["sources"]:
            state["sources"][sid]["status"] = "profiled"
            state["sources"][sid]["last_entry_hash"] = entry["hash"]
    elif tool == "emit_memory_written":
        state["memory"].append(
            {
                "memory_id": UUID(args["memory_id"]),
                "content": args["content"],
                "tags": list(args.get("tags", [])),
                "written_at": entry["ts"],
            }
        )
    elif tool == "emit_kpi_node":
        # Generic KPI tree write: shape matches `KpiNode`.
        state["kpi_nodes"][args["id"]] = dict(args)
    elif tool == "emit_person_proposed":
        pid = args["person_id"]
        tid = args["tenant_id"]
        state["persons"][pid] = {
            "person_id": UUID(pid),
            "tenant_id": UUID(tid),
            "name": args["name"],
            "email": args.get("email"),
            "position": args.get("position"),
            "status": "proposed",
            "proposed_by": args.get("proposed_by"),
            "confirmed_by": None,
            "created_at": entry["ts"],
            "last_updated_seq": entry["seq"],
        }
        # Initial PersonIdentity row for the platform the worm first saw them
        # on. Deterministic identity_id keyed on (tenant, platform, platform_user_id)
        # so a re-replay produces byte-identical state.
        platform = args.get("platform")
        platform_user_id = args.get("platform_user_id")
        if platform and platform_user_id:
            iid = _identity_uuid(tid, platform, platform_user_id)
            key = (tid, platform, platform_user_id)
            # on_conflict_do_nothing semantics: keep the first row we saw.
            state["person_identities"].setdefault(
                key,
                {
                    "identity_id": iid,
                    "person_id": UUID(pid),
                    "tenant_id": UUID(tid),
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "display_name": args["name"],
                    "email_at_platform": args.get("email"),
                    "avatar_url": None,
                    "added_at": entry["ts"],
                },
            )
    elif tool == "emit_person_confirmed":
        pid = args["person_id"]
        if pid in state["persons"]:
            p = state["persons"][pid]
            p.update(
                {
                    "status": "active",
                    "confirmed_by": UUID(args["confirmed_by"]),
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_person_archived":
        pid = args["person_id"]
        if pid in state["persons"]:
            p = state["persons"][pid]
            p.update(
                {
                    "status": "archived",
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_identity_linked":
        pid = args["person_id"]
        platform = args["platform"]
        platform_user_id = args["platform_user_id"]
        # tenant_id falls back to the entry's company_id (linked entries do
        # not carry tenant_id explicitly — they are already tenant-scoped).
        tid = str(entry["company_id"])
        iid = _identity_uuid(tid, platform, platform_user_id)
        key = (tid, platform, platform_user_id)
        state["person_identities"].setdefault(
            key,
            {
                "identity_id": iid,
                "person_id": UUID(pid),
                "tenant_id": UUID(tid),
                "platform": platform,
                "platform_user_id": platform_user_id,
                "display_name": None,
                "email_at_platform": None,
                "avatar_url": None,
                "added_at": entry["ts"],
            },
        )
    elif tool == "emit_identity_unlinked":
        platform = args["platform"]
        platform_user_id = args["platform_user_id"]
        tid = str(entry["company_id"])
        key = (tid, platform, platform_user_id)
        state["person_identities"].pop(key, None)
    elif tool == "emit_install_completed":
        tid = args["tenant_id"]
        platform = args["platform"]
        # Unique on (tenant_id, platform): on conflict, update. setup_mode +
        # setup_completed_at default to None until the Block G entries land.
        key = (tid, platform)
        # Preserve any setup_mode / setup_completed_at if a re-install
        # arrives after the user already picked a mode (rare; only when the
        # admin re-installs the chat platform mid-bot-path).
        prior = state["installs"].get(key, {})
        state["installs"][key] = {
            "install_id": UUID(args["install_id"]),
            "tenant_id": UUID(tid),
            "platform": platform,
            "installer_person_id": UUID(args["installer_person_id"]),
            "oauth_grant_ref": args["oauth_grant_ref"],
            "scopes": list(args.get("scopes", [])),
            "bot_user_id": args["bot_user_id"],
            "status": "active",
            "installed_at": entry["ts"],
            "setup_mode": prior.get("setup_mode"),
            "setup_completed_at": prior.get("setup_completed_at"),
            "last_updated_seq": entry["seq"],
        }
    elif tool == "emit_install_revoked":
        target_install_id = args["install_id"]
        for inst in state["installs"].values():
            if str(inst["install_id"]) == target_install_id:
                inst["status"] = "revoked"
                inst["last_updated_seq"] = entry["seq"]
                break
    elif tool == "emit_role_assigned":
        # Tenancy-facet grant. scope_id / scope_type are None for tenancy.
        tid = str(entry["company_id"])
        pid = args["person_id"]
        role = args["role"]
        seq = entry["seq"]
        gid = _role_grant_uuid(tid, pid, "tenancy", role, "", str(seq))
        state["roles"][gid] = {
            "grant_id": gid,
            "tenant_id": UUID(tid),
            "person_id": UUID(pid),
            "facet": "tenancy",
            "role": role,
            "scope_id": None,
            "scope_type": None,
            "granted_by": UUID(args["granted_by"]),
            "granted_at": entry["ts"],
            "revoked_at": None,
            "last_updated_seq": seq,
        }
    elif tool == "emit_role_revoked":
        # Find the matching unrevoked tenancy grant for (person_id, role) and
        # stamp ``revoked_at``. Iteration order is deterministic because
        # ``state["roles"]`` is keyed on the deterministic grant_id.
        target_pid = args["person_id"]
        target_role = args["role"]
        for grant in state["roles"].values():
            if (
                grant["facet"] == "tenancy"
                and str(grant["person_id"]) == target_pid
                and grant["role"] == target_role
                and grant["revoked_at"] is None
            ):
                grant["revoked_at"] = entry["ts"]
                grant["last_updated_seq"] = entry["seq"]
                break
    elif tool == "emit_domain_role_assigned":
        tid = str(entry["company_id"])
        pid = args["person_id"]
        domain_id = args["domain_id"]
        role = args["role"]
        seq = entry["seq"]
        gid = _role_grant_uuid(tid, pid, "domain", role, domain_id, str(seq))
        state["roles"][gid] = {
            "grant_id": gid,
            "tenant_id": UUID(tid),
            "person_id": UUID(pid),
            "facet": "domain",
            "role": role,
            "scope_id": UUID(domain_id),
            "scope_type": "domain",
            "granted_by": UUID(args["granted_by"]),
            "granted_at": entry["ts"],
            "revoked_at": None,
            "last_updated_seq": seq,
        }
    elif tool == "emit_resource_role_assigned":
        tid = str(entry["company_id"])
        pid = args["person_id"]
        resource_id = args["resource_id"]
        resource_type = args["resource_type"]
        role = args["role"]
        seq = entry["seq"]
        gid = _role_grant_uuid(tid, pid, "resource", role, resource_id, str(seq))
        state["roles"][gid] = {
            "grant_id": gid,
            "tenant_id": UUID(tid),
            "person_id": UUID(pid),
            "facet": "resource",
            "role": role,
            "scope_id": UUID(resource_id),
            "scope_type": resource_type,
            "granted_by": UUID(args["granted_by"]),
            "granted_at": entry["ts"],
            "revoked_at": None,
            "last_updated_seq": seq,
        }
    elif tool == "emit_position_proposed":
        # Wave B.5 G.3: worm-inferred position proposal.
        # Per Doctrine Addendum 2 §E this is the *propose-step* kind for
        # PositionInferenceReactivity (G.4). The fold writes the position
        # onto the existing Person row; admin override via the confirm-step
        # ``emit_position_assigned`` (or a discard via PEVR resolve)
        # supersedes per latest-wins semantics.
        pid = args["person_id"]
        if pid in state["persons"]:
            p = state["persons"][pid]
            p.update(
                {
                    "position": args["position"],
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_position_confirmed":
        # Wave H Phase 2 Task 2C: admin confirmed a worm-proposed position.
        # The position field is already set on the Person from the
        # optimistic-write at propose time; this fold is a no-op against
        # the projection_persons schema (no review-status column at v1).
        # Kept as an explicit branch for fold discoverability and for
        # the queue-projection layer (which folds confirmed/rejected
        # via the same execute scan).
        pass
    elif tool == "emit_position_rejected":
        # Wave H Phase 2 Task 2C: admin rejected a worm-proposed position.
        # Clears the optimistic position write so the Reactivity's dedup
        # gate (rehydrate_known_positions) frees this Person for
        # re-proposal once richer signal accumulates. ``position_assigned``
        # (admin-driven direct assignment) supersedes a rejection per
        # latest-wins; this branch only clears when the current position
        # matches the rejected one.
        pid = args["person_id"]
        rejected_position = args["position"]
        if pid in state["persons"]:
            p = state["persons"][pid]
            if p.get("position") == rejected_position:
                p.update(
                    {
                        "position": None,
                        "last_updated_seq": entry["seq"],
                    }
                )
    elif tool == "emit_resource_role_proposed":
        # Wave B.5 G.3: worm-inferred resource-role proposal.
        # Per Doctrine Addendum 2 §E this is the *propose-step* kind for
        # ResourceOwnershipReactivity (G.5). Writes a row into
        # ``state["roles"]`` with ``facet='resource'``; ``granted_by``
        # carries the proposer's UUID (the worm's own Person id when the
        # Reactivity emits, an admin's id when manually proposed).
        # ``scope_type`` is the literal ``"resource"`` since this
        # propose-step does not carry a typed resource-type — the
        # confirm-step ``emit_resource_role_assigned`` is where the
        # typed resource_type lands.
        tid = str(entry["company_id"])
        pid = args["person_id"]
        resource_id = args["resource_id"]
        role = args["role"]
        seq = entry["seq"]
        gid = _role_grant_uuid(
            tid, pid, "resource", role, resource_id, str(seq),
        )
        state["roles"][gid] = {
            "grant_id": gid,
            "tenant_id": UUID(tid),
            "person_id": UUID(pid),
            "facet": "resource",
            "role": role,
            "scope_id": UUID(resource_id),
            "scope_type": "resource",
            "granted_by": UUID(args["proposed_by"]),
            "granted_at": entry["ts"],
            "revoked_at": None,
            "last_updated_seq": seq,
        }
    elif tool == "emit_data_product_proposed":
        tid = str(entry["company_id"])
        dpid = args["data_product_id"]
        state["data_products"][dpid] = {
            "data_product_id": UUID(dpid),
            "tenant_id": UUID(tid),
            "name": args["name"],
            "kind": args["kind"],
            "status": "proposed",
            "requested_by_person_id": UUID(args["requested_by_person_id"]),
            "domain_id": (
                UUID(args["domain_id"]) if args.get("domain_id") else None
            ),
            "latest_run_seq": None,
            "generated_at": None,
            "content_hash": None,
            "contents_uri": None,
            "last_updated_seq": entry["seq"],
        }
    elif tool == "emit_data_product_generated":
        tid = str(entry["company_id"])
        dpid = args["data_product_id"]
        seq = entry["seq"]
        run_id = _data_product_uuid(tid, dpid, "run", str(seq))
        state["data_product_runs"][run_id] = {
            "run_id": run_id,
            "data_product_id": UUID(dpid),
            "tenant_id": UUID(tid),
            "generated_by": args["generated_by"],
            "ts": entry["ts"],
            "source_hashes": list(args.get("source_hashes", [])),
            "content_hash": args["content_hash"],
            "duration_ms": int(args["duration_ms"]),
        }
        if dpid in state["data_products"]:
            dp = state["data_products"][dpid]
            dp.update(
                {
                    "status": "generated",
                    "latest_run_seq": seq,
                    "generated_at": entry["ts"],
                    "content_hash": args["content_hash"],
                    "contents_uri": args["contents_uri"],
                    "last_updated_seq": seq,
                }
            )
    elif tool == "emit_data_product_consumed":
        tid = str(entry["company_id"])
        dpid = args["data_product_id"]
        seq = entry["seq"]
        consumption_id = _data_product_uuid(tid, dpid, "consume", str(seq))
        state["data_product_consumption"][consumption_id] = {
            "consumption_id": consumption_id,
            "data_product_id": UUID(dpid),
            "tenant_id": UUID(tid),
            "person_id": UUID(args["consumed_by_person_id"]),
            "surface": args["surface"],
            "channel": args.get("channel"),
            "ts": entry["ts"],
        }
    elif tool == "emit_data_product_archived":
        dpid = args["data_product_id"]
        if dpid in state["data_products"]:
            dp = state["data_products"][dpid]
            dp.update(
                {
                    "status": "archived",
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_notebook_proposed":
        tid = str(entry["company_id"])
        nid = args["notebook_id"]
        state["notebooks"][nid] = {
            "notebook_id": UUID(nid),
            "tenant_id": UUID(tid),
            "name": args["name"],
            "kernel": args["kernel"],
            "status": "proposed",
            "owner_person_id": UUID(args["proposed_by_person_id"]),
            "domain_id": (
                UUID(args["domain_id"]) if args.get("domain_id") else None
            ),
            "latest_run_id": None,
            "latest_published_run_id": None,
            "version": None,
            "last_updated_seq": entry["seq"],
            # Cells stashed in projection state for replay convenience; not
            # exposed in the schema (the source-of-truth is the ledger row).
            "_cells": list(args.get("cells", [])),
        }
    elif tool == "emit_notebook_run":
        tid = str(entry["company_id"])
        nid = args["notebook_id"]
        seq = entry["seq"]
        run_id = _notebook_run_uuid(tid, nid, "run", str(seq))
        state["notebook_runs"][run_id] = {
            "run_id": run_id,
            "notebook_id": UUID(nid),
            "tenant_id": UUID(tid),
            "status": args["status"],
            "ts": entry["ts"],
            "run_by": args["run_by"],
            "kernel_state_hash": args["kernel_state_hash"],
            "duration_ms": int(args["duration_ms"]),
        }
        if nid in state["notebooks"]:
            nb = state["notebooks"][nid]
            nb.update(
                {
                    "status": "run",
                    "latest_run_id": run_id,
                    "last_updated_seq": seq,
                }
            )
    elif tool == "emit_notebook_published":
        tid = str(entry["company_id"])
        nid = args["notebook_id"]
        seq = entry["seq"]
        # The published run_id refers to a previous run entry whose
        # projection row id is derived from the seq it landed at; we don't
        # try to resolve that here. Instead store the (deterministic) seq-
        # based id of the publish entry itself for downstream cross-linking.
        published_run_id = _notebook_run_uuid(tid, nid, "publish", str(seq))
        if nid in state["notebooks"]:
            nb = state["notebooks"][nid]
            nb.update(
                {
                    "status": "published",
                    "latest_published_run_id": published_run_id,
                    "version": args["version"],
                    "owner_person_id": UUID(args["owner_person_id"]),
                    "domain_id": (
                        UUID(args["domain_id"]) if args.get("domain_id") else nb.get("domain_id")
                    ),
                    "last_updated_seq": seq,
                }
            )
    elif tool == "emit_notebook_archived":
        nid = args["notebook_id"]
        if nid in state["notebooks"]:
            nb = state["notebooks"][nid]
            nb.update(
                {
                    "status": "archived",
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_setup_mode_chosen":
        # Stamp setup_mode on the (tenant, *) install rows. Tenant-level
        # choice — if N installs exist for the tenant (rare during onboarding;
        # only after multi-platform connect), all are stamped to keep reads
        # cheap on the dashboard's redirect-guard query.
        target_tid = args["tenant_id"]
        mode = args["mode"]
        for inst in state["installs"].values():
            if str(inst["tenant_id"]) == target_tid:
                inst["setup_mode"] = mode
                inst["last_updated_seq"] = entry["seq"]
    elif tool == "emit_setup_completed":
        target_tid = args["tenant_id"]
        for inst in state["installs"].values():
            if str(inst["tenant_id"]) == target_tid:
                inst["setup_completed_at"] = entry["ts"]
                inst["last_updated_seq"] = entry["seq"]
    elif tool == "emit_mcp_call_received":
        # Phase 0 MCP spike. One row per external MCP tool invocation; the
        # mcp_call_id in the payload is unique per call (uuid4 at the
        # server) so collisions are impossible across replays.
        mcp_id = args["mcp_call_id"]
        state["mcp_calls"][mcp_id] = {
            "mcp_call_id": UUID(mcp_id),
            "tenant_id": UUID(args["tenant_id"]),
            "caller_person_id": (
                UUID(args["caller_person_id"])
                if args.get("caller_person_id")
                else None
            ),
            "tool_name": args["tool_name"],
            "args_hash": args["args_hash"],
            "client_ua": args.get("client_ua"),
            "started_at": entry["ts"],
            "outcome": args["outcome"],
            "latency_ms": int(args["latency_ms"]),
        }
    elif tool == "emit_setup_step_advanced":
        # Cursor advance on the bot-path YAML. One row per tenant; the
        # ``steps_completed`` list grows in advance order. Replay-stable
        # because seq is replay-stable.
        target_tid = args["tenant_id"]
        step_id = args["step_id"]
        tid_uuid = UUID(target_tid)
        existing = state["setup_progress"].get(tid_uuid)
        if existing is None:
            state["setup_progress"][tid_uuid] = {
                "tenant_id": tid_uuid,
                "current_step": step_id,
                "steps_completed": [step_id],
                "last_advance_seq": entry["seq"],
                "last_advance_ts": entry["ts"],
            }
        else:
            completed = list(existing["steps_completed"])
            if step_id not in completed:
                completed.append(step_id)
            existing.update(
                {
                    "current_step": step_id,
                    "steps_completed": completed,
                    "last_advance_seq": entry["seq"],
                    "last_advance_ts": entry["ts"],
                }
            )
    elif tool == "emit_external_catalog_imported":
        # ----------------------------------------------------------------
        # === Catalog-mirror Wave 1 — external_catalog_imported handler ===
        #
        # Folds a catalog-mirror snapshot import into
        # ``projection_external_catalog``. The CatalogImportReactivity
        # (and the future CatalogDriftReactivity refresh path) writes a
        # PEVR cycle whose execute-row carries the canonical
        # ``ExternalCatalogImportedPayload`` body under ``payload.args``.
        #
        # Replay semantics: deterministic ``id`` keyed on
        # ``(company_id, source_id, snapshot_hash)`` means re-runs over
        # the same ledger stream produce byte-identical rows. A re-import
        # of the exact same snapshot (no-op refresh) collapses onto the
        # same row; a real drift detection lands a NEW row with a
        # different ``snapshot_hash`` and is preserved alongside the prior
        # one — the dashboard's /lake/catalog accessor selects the
        # most-recent-per-source-id at read time.
        # ----------------------------------------------------------------
        company_id = entry["company_id"]
        source_id_str = args["source_id"]
        snapshot_hash = args["snapshot_hash"]
        row_id = _external_catalog_uuid(
            str(company_id), source_id_str, snapshot_hash,
        )
        state["external_catalog"][row_id] = {
            "id": row_id,
            "company_id": company_id,
            "source_id": UUID(source_id_str),
            "domain_id": UUID(args["domain_id"]),
            "source_kind": args["source_kind"],
            "snapshot_hash": snapshot_hash,
            "table_count": int(args["table_count"]),
            "edge_count": int(args["edge_count"]),
            "metric_count": int(args["metric_count"]),
            "import_mode": args["import_mode"],
            "imported_at": entry["ts"],
        }
    elif tool == "emit_external_lineage_imported":
        # ----------------------------------------------------------------
        # === Catalog-mirror Wave 1 — external_lineage_imported handler ===
        #
        # Folds the flattened edge list into
        # ``projection_external_lineage`` — one row per edge tuple per
        # snapshot import. Edges are tuples of fully-qualified node ids:
        # e.g. dbt's ``"source.raw.events" → "model.staging.events"``.
        #
        # Replay semantics: deterministic ``id`` keyed on
        # ``(company_id, source_id, upstream, downstream)``. A re-import
        # with identical edges lands on the same row; an edge added by
        # an upstream catalog change shows up as a new row. The
        # tenant-scoped delete+insert persist pattern handles drift in
        # the natural way.
        # ----------------------------------------------------------------
        company_id = entry["company_id"]
        source_id_str = args["source_id"]
        edges = args.get("edges", []) or []
        for edge in edges:
            # Edges may arrive as tuples from native pydantic round-trip
            # or as 2-element lists from JSON re-hydration; accept both.
            if isinstance(edge, (list, tuple)) and len(edge) == 2:
                upstream, downstream = edge[0], edge[1]
            else:
                # Defensive: skip malformed edges rather than crash the
                # fold for a single bad payload. The payload validator
                # already rejects these at write time.
                continue
            row_id = _external_lineage_uuid(
                str(company_id), source_id_str, str(upstream), str(downstream),
            )
            state["external_lineage"][row_id] = {
                "id": row_id,
                "company_id": company_id,
                "source_id": UUID(source_id_str),
                "upstream": str(upstream),
                "downstream": str(downstream),
                "imported_at": entry["ts"],
            }
    elif tool == "emit_external_policy_imported":
        # ----------------------------------------------------------------
        # === Catalog-mirror Wave 1 — external_policy_imported handler ===
        #
        # Folds an upstream masking / row-access policy mirror into
        # ``projection_external_policy``. The CatalogImportReactivity
        # writes one PEVR per upstream policy in
        # ``snap.policies``; the execute payload carries the canonical
        # ``ExternalPolicyImportedPayload`` body under ``payload.args``.
        #
        # S2 spike contract: ``body`` is NULL when the catalog credential
        # lacks APPLY privilege (typical for read-only Snowflake
        # roles). The dashboard renders a "Body unavailable
        # (insufficient APPLY privilege)" placeholder when this is the
        # case; the policy is still tracked because drift detection
        # only requires existence, not body.
        #
        # Replay semantics: deterministic ``id`` keyed on
        # ``(company_id, source_id, policy_fqn)`` means re-imports
        # upsert in place. A rename (different ``policy_fqn``) is a
        # new row.
        # ----------------------------------------------------------------
        company_id = entry["company_id"]
        source_id_str = args["source_id"]
        policy_fqn = args["policy_fqn"]
        row_id = _external_policy_uuid(
            str(company_id), source_id_str, policy_fqn,
        )
        applied_to_raw = args.get("applied_to", []) or []
        # pydantic round-trips tuples as lists across JSON; accept both
        # so the fold sees the same shape from disk as from a native
        # write.
        applied_to_list = list(applied_to_raw)
        state["external_policy"][row_id] = {
            "id": row_id,
            "company_id": company_id,
            "source_id": UUID(source_id_str),
            "policy_fqn": policy_fqn,
            "policy_kind": args["policy_kind"],
            "body": args.get("body"),
            "applied_to": applied_to_list,
            "imported_at": entry["ts"],
        }
    elif tool == "emit_external_metric_imported":
        # ----------------------------------------------------------------
        # === Catalog-mirror Wave 1 — external_metric_imported handler ===
        #
        # Folds a semantic-layer metric definition mirror into
        # ``projection_external_metric``. The CatalogImportReactivity
        # writes one PEVR per metric in ``snap.metrics``; the execute
        # payload carries the canonical
        # ``ExternalMetricImportedPayload`` body under ``payload.args``.
        #
        # Replay semantics: deterministic ``id`` keyed on
        # ``(company_id, source_id, name)`` means re-imports of the
        # same metric name upsert in place (latest-wins on
        # ``expression`` / ``time_grain`` / ``dimensions`` /
        # ``description``). A rename produces a new row.
        #
        # ``expression`` / ``time_grain`` / ``description`` are
        # nullable because upstream catalogs differ on which fields
        # they expose — the projection preserves NULLs verbatim
        # rather than synthesizing placeholders.
        # ----------------------------------------------------------------
        company_id = entry["company_id"]
        source_id_str = args["source_id"]
        metric_name = args["name"]
        row_id = _external_metric_uuid(
            str(company_id), source_id_str, metric_name,
        )
        dimensions_raw = args.get("dimensions", []) or []
        dimensions_list = list(dimensions_raw)
        state["external_metric"][row_id] = {
            "id": row_id,
            "company_id": company_id,
            "source_id": UUID(source_id_str),
            "name": metric_name,
            "expression": args.get("expression"),
            "time_grain": args.get("time_grain"),
            "dimensions": dimensions_list,
            "description": args.get("description"),
            "imported_at": entry["ts"],
        }
    elif tool == "emit_agent_registered":
        # ----------------------------------------------------------------
        # === Agent-gateway Wave 3 Task 2 — agent_registered handler ===
        #
        # Folds an admin-driven register_agent execution into
        # projection_agents. One row per agent; id is the same
        # value as agent_id (Wave 2 v1: agent_id == person_id 1:1).
        # status defaults to active on insert per the v012
        # schema; the agent lifecycle status field becomes meaningful
        # later when an admin retires an agent (status=inactive).
        # ----------------------------------------------------------------
        agent_id = args["agent_id"]
        tid = args.get("company_id") or str(entry["company_id"])
        state["agents"][agent_id] = {
            "id": agent_id,
            "company_id": tid,
            "person_id": args["person_id"],
            "external_provider": args["external_provider"],
            "display_name": args["display_name"],
            "registered_at": entry["ts"],
            "status": "active",
        }
    elif tool == "emit_agent_grant":
        # ----------------------------------------------------------------
        # === Agent-gateway Wave 3 Task 2 — agent_grant handler ===
        #
        # Folds an agent_grant execution into projection_agent_grants.
        # Per Addendum 3 this is a SINGLE kind with a status field —
        # assign and revoke land on the same row keyed by the
        # (agent_id, grant_kind, grant_target) triple. The row id is
        # deterministic over the triple so re-emits upsert in place
        # rather than creating a new row.
        #
        # budget_remaining_usd is preserved verbatim; only model.access
        # grants populate it. Data grants leave it None per v013.
        # ----------------------------------------------------------------
        agent_id = args["agent_id"]
        grant_kind = args["grant_kind"]
        grant_target = args["grant_target"]
        tid = args.get("company_id") or str(entry["company_id"])
        row_id = _agent_grant_uuid(tid, agent_id, grant_kind, grant_target)
        state["agent_grants"][row_id] = {
            "id": row_id,
            "company_id": tid,
            "agent_id": agent_id,
            "grant_kind": grant_kind,
            "grant_target": grant_target,
            "status": args["status"],
            "granted_by": args["granted_by"],
            "granted_at": entry["ts"],
            "budget_remaining_usd": args.get("budget_remaining_usd"),
        }
    elif tool == "emit_query_outcome_recorded":
        # ----------------------------------------------------------------
        # === §4.5 compounding loop — query_outcome_recorded handler ===
        #
        # Folds a recorded outcome into projection_query_outcomes
        # (v016 schema). The MCP tool ``lake.query.record_outcome``
        # writes a canonical PEVR cycle with ``tool=
        # "emit_query_outcome_recorded"`` + the
        # ``QueryOutcomeRecordedPayload`` body under ``payload.args``
        # (Wave 3 Task 0 prep landed this shape).
        #
        # Replay semantics: deterministic ``id`` keyed on
        # ``(company_id, execute_entry_id)`` collapses re-emit of the
        # SAME execute row (replay) onto the same projection row. A
        # new outcome (different execute entry_id) is a new row by
        # design — outcomes accumulate.
        #
        # v2.B Phase 3b (2026-05-12): ``embedding`` IS folded now —
        # write-time embedding produced by EmbeddingService lands on
        # the payload's ``embedding`` field; the fold preserves it
        # verbatim. The schema mirror in schema.py adds the column
        # as JSON for SQLite portability; the Postgres migration
        # path stores it as Vector(768). The fold writes a Python
        # list of floats either way; SQLAlchemy adapts the type via
        # the column definition.
        #
        # Replay determinism: embeddings are written-once at the
        # MCP-tool boundary, never recomputed at replay. The fold's
        # job is just to copy the field; the inference call already
        # happened upstream.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        row_id = _query_outcome_uuid(tid, str(entry["entry_id"]))
        final_query_spec = args.get("final_query_spec") or {}
        if not isinstance(final_query_spec, dict):
            final_query_spec = {}
        result_summary = args.get("result_summary") or {}
        if not isinstance(result_summary, dict):
            result_summary = {}
        # Embedding is optional (additive field per Rule 2). Coerce to
        # ``list[float]`` if present; None preserves the always-NULL
        # column path for pre-Phase-3b ledgers / disabled service.
        raw_emb = args.get("embedding")
        embedding: list[float] | None
        if isinstance(raw_emb, (list, tuple)) and raw_emb:
            try:
                embedding = [float(v) for v in raw_emb]
            except (TypeError, ValueError):
                embedding = None
        else:
            embedding = None
        state["query_outcomes"][row_id] = {
            "id": row_id,
            "company_id": tid,
            "agent_query_id": str(args.get("agent_query_id") or ""),
            "nl_question": str(args.get("nl_question") or ""),
            "final_query_spec": final_query_spec,
            "result_summary": result_summary,
            "used": bool(args.get("used", False)),
            "useful": bool(args.get("useful", False)),
            "user_correction": args.get("user_correction"),
            # quality_score arrives as a string-formatted Decimal in
            # [0.0, 1.0]; preserve verbatim. The Numeric(6,4) column
            # accepts string input on insert.
            "quality_score": str(args.get("quality_score") or "0"),
            "embedding": embedding,
            "recorded_at": entry["ts"],
        }
    elif tool == "emit_topic_proposed":
        # Phase 2 Task 2B — silver-conversations topic clusters. Re-emit
        # on a growing cluster (same topic_id, larger cluster_size)
        # updates the row in place; first_seen_at is preserved across
        # re-emits, last_seen_at + label + confidence + served_by track
        # the latest payload.
        topic_id = args["topic_id"]
        existing = state["topics"].get(topic_id)
        # Confidence is stored as a 4-char string ("0.78") for byte
        # stability in the projection table; the in-memory builder
        # output mirrors that shape so persist_projections is a
        # straight pass-through.
        confidence_str = f"{float(args.get('confidence', 0.5)):.2f}"
        if existing is None:
            state["topics"][topic_id] = {
                "topic_id": UUID(topic_id),
                "label": args["label"],
                "cluster_signature": args["cluster_signature"],
                "cluster_size": int(args["cluster_size"]),
                "member_message_ids": list(args.get("member_message_ids", [])),
                "first_seen_at": _parse_topic_ts(args["first_seen_at"]),
                "last_seen_at": _parse_topic_ts(args["last_seen_at"]),
                "confidence": confidence_str,
                "served_by": args.get("served_by", "heuristic"),
                "last_updated_seq": entry["seq"],
            }
        else:
            existing.update(
                {
                    "label": args["label"],
                    "cluster_signature": args["cluster_signature"],
                    "cluster_size": int(args["cluster_size"]),
                    "member_message_ids": list(
                        args.get("member_message_ids", [])
                    ),
                    "last_seen_at": _parse_topic_ts(args["last_seen_at"]),
                    "confidence": confidence_str,
                    "served_by": args.get("served_by", "heuristic"),
                    "last_updated_seq": entry["seq"],
                }
            )
    elif tool == "emit_lineage_edge_proposed":
        # ----------------------------------------------------------------
        # === L3 Sub-wave A — lineage_edge_proposed handler ===
        #
        # Inference strategy proposes a candidate edge (or re-proposes
        # the same logical edge from a different strategy). Folds into
        # projection_lineage_edges via the deterministic
        # ``(company_id, edge_id)`` composite key.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of an edge
        # that's already confirmed/rejected DOES update the row's
        # evidence + reasoning + confidence (the latest strategy's view)
        # but does NOT regress the state — that requires the operator
        # to explicitly emit a new confirm/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        edge_id = str(args.get("edge_id") or "")
        if not edge_id:
            # Skip malformed proposals; the payload-side validator
            # should have rejected at write time, so this is defensive.
            logger.warning(
                "v021 fold: lineage_edge_proposed with empty edge_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, edge_id)
            existing = state["lineage_edges"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            if existing is None:
                state["lineage_edges"][row_key] = {
                    "company_id": tid,
                    "edge_id": edge_id,
                    "src_table_id": str(args.get("src_table_id") or ""),
                    "src_column": args.get("src_column"),
                    "tgt_table_id": str(args.get("tgt_table_id") or ""),
                    "tgt_column": args.get("tgt_column"),
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy — the
                # latest proposal's view). State stays whatever it was
                # — only confirm/reject entries advance the state.
                existing.update(
                    {
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_lineage_edge_confirmed":
        # ----------------------------------------------------------------
        # === L3 Sub-wave A — lineage_edge_confirmed handler ===
        #
        # Admin approves a previously-proposed edge. The fold UPDATES
        # the existing row's state → "confirmed" and records the
        # approving Person UUID + ts. An unknown edge_id (no prior
        # proposal in the same replay) is logged + skipped: this can
        # only happen via mis-ordered replays or external write paths
        # that bypass the L3 axis; the fold stays defensive rather
        # than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        edge_id = str(args.get("edge_id") or "")
        if not edge_id:
            logger.warning(
                "v021 fold: lineage_edge_confirmed with empty edge_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, edge_id)
            existing = state["lineage_edges"].get(row_key)
            if existing is None:
                logger.warning(
                    "v021 fold: lineage_edge_confirmed for unknown "
                    "edge_id=%s (company=%s) at seq=%s; skipping",
                    edge_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_lineage_edge_rejected":
        # ----------------------------------------------------------------
        # === L3 Sub-wave A — lineage_edge_rejected handler ===
        #
        # Admin rejects a previously-proposed edge with a categorical
        # reason. Mirror of the confirmed handler: UPDATE state →
        # "rejected", record the rejecting Person UUID + ts. Unknown
        # edge_id: log + skip (same defensive posture as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        edge_id = str(args.get("edge_id") or "")
        if not edge_id:
            logger.warning(
                "v021 fold: lineage_edge_rejected with empty edge_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, edge_id)
            existing = state["lineage_edges"].get(row_key)
            if existing is None:
                logger.warning(
                    "v021 fold: lineage_edge_rejected for unknown "
                    "edge_id=%s (company=%s) at seq=%s; skipping",
                    edge_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_quality_check_proposed":
        # ----------------------------------------------------------------
        # === L7 Sub-wave A — quality_check_proposed handler ===
        #
        # Inference strategy proposes a candidate check (or re-proposes
        # the same logical check from a different strategy). Folds into
        # projection_quality_checks via the deterministic
        # ``(company_id, check_id)`` composite key.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a check
        # that's already confirmed/rejected DOES update the row's
        # evidence + reasoning + confidence (the latest strategy's view)
        # but does NOT regress the state — that requires the operator
        # to explicitly emit a new confirm/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        check_id = str(args.get("check_id") or "")
        if not check_id:
            # Skip malformed proposals; the payload-side validator
            # should have rejected at write time, so this is defensive.
            logger.warning(
                "v022 fold: quality_check_proposed with empty check_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, check_id)
            existing = state["quality_checks"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            config = args.get("config") or {}
            if not isinstance(config, dict):
                config = {}
            confidence = float(args.get("confidence", 0.0))
            if existing is None:
                state["quality_checks"][row_key] = {
                    "company_id": tid,
                    "check_id": check_id,
                    "table_id": str(args.get("table_id") or ""),
                    "column": args.get("column"),
                    "check_kind": str(args.get("check_kind") or ""),
                    "config": config,
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy / config —
                # the latest proposal's view). State stays whatever it was
                # — only confirm/reject entries advance the state.
                existing.update(
                    {
                        "config": config,
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_quality_check_confirmed":
        # ----------------------------------------------------------------
        # === L7 Sub-wave A — quality_check_confirmed handler ===
        #
        # Admin approves a previously-proposed check. The fold UPDATES
        # the existing row's state → "confirmed" and records the
        # approving Person UUID + ts. An unknown check_id (no prior
        # proposal in the same replay) is logged + skipped: this can
        # only happen via mis-ordered replays or external write paths
        # that bypass the L7 axis; the fold stays defensive rather
        # than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        check_id = str(args.get("check_id") or "")
        if not check_id:
            logger.warning(
                "v022 fold: quality_check_confirmed with empty check_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, check_id)
            existing = state["quality_checks"].get(row_key)
            if existing is None:
                logger.warning(
                    "v022 fold: quality_check_confirmed for unknown "
                    "check_id=%s (company=%s) at seq=%s; skipping",
                    check_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_quality_check_rejected":
        # ----------------------------------------------------------------
        # === L7 Sub-wave A — quality_check_rejected handler ===
        #
        # Admin rejects a previously-proposed check with a categorical
        # reason. Mirror of the confirmed handler: UPDATE state →
        # "rejected", record the rejecting Person UUID + ts. Unknown
        # check_id: log + skip (same defensive posture as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        check_id = str(args.get("check_id") or "")
        if not check_id:
            logger.warning(
                "v022 fold: quality_check_rejected with empty check_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, check_id)
            existing = state["quality_checks"].get(row_key)
            if existing is None:
                logger.warning(
                    "v022 fold: quality_check_rejected for unknown "
                    "check_id=%s (company=%s) at seq=%s; skipping",
                    check_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_schema_impact_proposed":
        # ----------------------------------------------------------------
        # === L4 Sub-wave A — schema_impact_proposed handler ===
        #
        # Inference strategy proposes a candidate schema-evolution
        # impact (or re-proposes the same logical impact from a
        # different strategy — e.g. the L3 confirmed-edge consumer
        # proposes first, then the dbt-test consumer re-proposes the
        # same impact with stronger evidence). Folds into
        # projection_schema_impacts via the deterministic
        # ``(company_id, impact_id)`` composite key.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of an
        # impact that's already confirmed/rejected DOES update the
        # row's evidence + reasoning + confidence (the latest
        # strategy's view) but does NOT regress the state — that
        # requires the operator to explicitly emit a new confirm/
        # reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        impact_id = str(args.get("impact_id") or "")
        if not impact_id:
            # Skip malformed proposals; the payload-side validator
            # should have rejected at write time, so this is defensive.
            logger.warning(
                "v023 fold: schema_impact_proposed with empty impact_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, impact_id)
            existing = state["schema_impacts"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            upstream_edge = args.get("upstream_lineage_edge_id")
            # Normalize empty string → None so the column carries
            # genuine NULL semantics for type_coercion-strategy
            # proposals that have no upstream L3 edge.
            if upstream_edge == "":
                upstream_edge = None
            if existing is None:
                state["schema_impacts"][row_key] = {
                    "company_id": tid,
                    "impact_id": impact_id,
                    "source_id": str(args.get("source_id") or ""),
                    "src_table": str(args.get("src_table") or ""),
                    "src_column": str(args.get("src_column") or ""),
                    "change_kind": str(args.get("change_kind") or ""),
                    "impact_kind": str(args.get("impact_kind") or ""),
                    "tgt_table_id": str(args.get("tgt_table_id") or ""),
                    "tgt_column": str(args.get("tgt_column") or ""),
                    "upstream_lineage_edge_id": upstream_edge,
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy /
                # upstream_lineage_edge_id — the latest proposal's
                # view). State stays whatever it was — only confirm/
                # reject entries advance the state.
                existing.update(
                    {
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                        "upstream_lineage_edge_id": upstream_edge,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_schema_impact_confirmed":
        # ----------------------------------------------------------------
        # === L4 Sub-wave A — schema_impact_confirmed handler ===
        #
        # Admin approves a previously-proposed impact. The fold UPDATES
        # the existing row's state → "confirmed" and records the
        # approving Person UUID + ts. An unknown impact_id (no prior
        # proposal in the same replay) is logged + skipped: this can
        # only happen via mis-ordered replays or external write paths
        # that bypass the L4 axis; the fold stays defensive rather
        # than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        impact_id = str(args.get("impact_id") or "")
        if not impact_id:
            logger.warning(
                "v023 fold: schema_impact_confirmed with empty impact_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, impact_id)
            existing = state["schema_impacts"].get(row_key)
            if existing is None:
                logger.warning(
                    "v023 fold: schema_impact_confirmed for unknown "
                    "impact_id=%s (company=%s) at seq=%s; skipping",
                    impact_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_schema_impact_rejected":
        # ----------------------------------------------------------------
        # === L4 Sub-wave A — schema_impact_rejected handler ===
        #
        # Admin rejects a previously-proposed impact with a categorical
        # reason. Mirror of the confirmed handler: UPDATE state →
        # "rejected", record the rejecting Person UUID + ts. Unknown
        # impact_id: log + skip (same defensive posture as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        impact_id = str(args.get("impact_id") or "")
        if not impact_id:
            logger.warning(
                "v023 fold: schema_impact_rejected with empty impact_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, impact_id)
            existing = state["schema_impacts"].get(row_key)
            if existing is None:
                logger.warning(
                    "v023 fold: schema_impact_rejected for unknown "
                    "impact_id=%s (company=%s) at seq=%s; skipping",
                    impact_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_semantic_type_proposed":
        # ----------------------------------------------------------------
        # === L5 Sub-wave A — semantic_type_proposed handler ===
        #
        # Fingerprinting strategy proposes a candidate semantic type for
        # a column (e.g. "this looks like an email address"). Strategies
        # may re-propose the same logical type (e.g. column_name first,
        # then value_pattern with stronger evidence) — the composite PK
        # ``(company_id, type_id)`` collapses re-emission onto the same
        # projection row.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a
        # type that's already confirmed/rejected DOES update the
        # row's evidence + reasoning + confidence + strategy (the
        # latest strategy's view) but does NOT regress the state —
        # that requires the operator to explicitly emit a new
        # confirm/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        type_id = str(args.get("type_id") or "")
        if not type_id:
            logger.warning(
                "v024 fold: semantic_type_proposed with empty type_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, type_id)
            existing = state["semantic_types"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            if existing is None:
                state["semantic_types"][row_key] = {
                    "company_id": tid,
                    "type_id": type_id,
                    "table_id": str(args.get("table_id") or ""),
                    "column": str(args.get("column") or ""),
                    "semantic_type": str(args.get("semantic_type") or ""),
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy /
                # semantic_type — the latest proposal's view). State
                # stays whatever it was — only confirm/reject entries
                # advance the state.
                existing.update(
                    {
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                        "semantic_type": str(args.get("semantic_type") or ""),
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_semantic_type_confirmed":
        # ----------------------------------------------------------------
        # === L5 Sub-wave A — semantic_type_confirmed handler ===
        #
        # Admin approves a previously-proposed semantic type. The fold
        # UPDATES the existing row's state → "confirmed" and records
        # the approving Person UUID + ts. An unknown type_id (no prior
        # proposal in the same replay) is logged + skipped: this can
        # only happen via mis-ordered replays or external write paths
        # that bypass the L5 axis; the fold stays defensive rather
        # than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        type_id = str(args.get("type_id") or "")
        if not type_id:
            logger.warning(
                "v024 fold: semantic_type_confirmed with empty type_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, type_id)
            existing = state["semantic_types"].get(row_key)
            if existing is None:
                logger.warning(
                    "v024 fold: semantic_type_confirmed for unknown "
                    "type_id=%s (company=%s) at seq=%s; skipping",
                    type_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_semantic_type_rejected":
        # ----------------------------------------------------------------
        # === L5 Sub-wave A — semantic_type_rejected handler ===
        #
        # Admin rejects a previously-proposed semantic type with a
        # categorical reason. Mirror of the confirmed handler:
        # UPDATE state → "rejected", record the rejecting Person UUID
        # + ts. Unknown type_id: log + skip (same defensive posture
        # as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        type_id = str(args.get("type_id") or "")
        if not type_id:
            logger.warning(
                "v024 fold: semantic_type_rejected with empty type_id at "
                "seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, type_id)
            existing = state["semantic_types"].get(row_key)
            if existing is None:
                logger.warning(
                    "v024 fold: semantic_type_rejected for unknown "
                    "type_id=%s (company=%s) at seq=%s; skipping",
                    type_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_column_classification_proposed":
        # ----------------------------------------------------------------
        # === L6 Sub-wave A — column_classification_proposed handler ===
        #
        # Inference strategy proposes a governance classification level
        # for a column (e.g. inferred PII → ``regulated``). Strategies
        # may re-propose the same logical classification (e.g.
        # naming_pattern first, then semantic_type with stronger
        # evidence) — the composite PK ``(company_id,
        # classification_id)`` collapses re-emission onto the same
        # projection row.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a
        # classification that's already confirmed/rejected DOES update
        # the row's evidence + reasoning + confidence + strategy +
        # upstream_semantic_type_id (the latest strategy's view) but
        # does NOT regress the state — that requires the operator to
        # explicitly emit a new confirm/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        classification_id = str(args.get("classification_id") or "")
        if not classification_id:
            logger.warning(
                "v025 fold: column_classification_proposed with empty "
                "classification_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, classification_id)
            existing = state["column_classifications"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            upstream = args.get("upstream_semantic_type_id")
            upstream_str = str(upstream) if upstream else None
            if existing is None:
                state["column_classifications"][row_key] = {
                    "company_id": tid,
                    "classification_id": classification_id,
                    "table_id": str(args.get("table_id") or ""),
                    "column": str(args.get("column") or ""),
                    "classification_level": str(
                        args.get("classification_level") or ""
                    ),
                    "upstream_semantic_type_id": upstream_str,
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy /
                # classification_level / upstream_semantic_type_id —
                # the latest proposal's view). State stays whatever it
                # was — only confirm/reject entries advance the state.
                existing.update(
                    {
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                        "classification_level": str(
                            args.get("classification_level") or ""
                        ),
                        "upstream_semantic_type_id": upstream_str,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_column_classification_confirmed":
        # ----------------------------------------------------------------
        # === L6 Sub-wave A — column_classification_confirmed handler ===
        #
        # Admin approves a previously-proposed column classification.
        # The fold UPDATES the existing row's state → "confirmed" and
        # records the approving Person UUID + ts. An unknown
        # classification_id (no prior proposal in the same replay) is
        # logged + skipped: this can only happen via mis-ordered
        # replays or external write paths that bypass the L6 axis; the
        # fold stays defensive rather than fabricate a row from
        # incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        classification_id = str(args.get("classification_id") or "")
        if not classification_id:
            logger.warning(
                "v025 fold: column_classification_confirmed with empty "
                "classification_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, classification_id)
            existing = state["column_classifications"].get(row_key)
            if existing is None:
                logger.warning(
                    "v025 fold: column_classification_confirmed for "
                    "unknown classification_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    classification_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_column_classification_rejected":
        # ----------------------------------------------------------------
        # === L6 Sub-wave A — column_classification_rejected handler ===
        #
        # Admin rejects a previously-proposed column classification
        # with a categorical reason. Mirror of the confirmed handler:
        # UPDATE state → "rejected", record the rejecting Person UUID
        # + ts. Unknown classification_id: log + skip (same defensive
        # posture as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        classification_id = str(args.get("classification_id") or "")
        if not classification_id:
            logger.warning(
                "v025 fold: column_classification_rejected with empty "
                "classification_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, classification_id)
            existing = state["column_classifications"].get(row_key)
            if existing is None:
                logger.warning(
                    "v025 fold: column_classification_rejected for "
                    "unknown classification_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    classification_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_entity_stitch_proposed":
        # ----------------------------------------------------------------
        # === L8 Sub-wave A — entity_stitch_proposed handler ===
        #
        # Inference strategy proposes a cross-source entity stitch
        # bridging two ``(source, table, column)`` triples that
        # probably reference the same underlying entity (e.g.
        # ``stripe.customers.email`` ↔ ``salesforce.contacts.email``).
        # Strategies may re-propose the same logical stitch with
        # stronger evidence (e.g. ``name_match`` first, then
        # ``sample_overlap`` after sampling completes) — the composite
        # PK ``(company_id, stitch_id)`` collapses re-emission onto
        # the same projection row.
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a
        # stitch that's already confirmed/rejected DOES update the
        # row's evidence + reasoning + confidence + strategy +
        # upstream_semantic_type_id + entity_kind (the latest
        # strategy's view) but does NOT regress the state — that
        # requires the operator to explicitly emit a new
        # confirm/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        stitch_id = str(args.get("stitch_id") or "")
        if not stitch_id:
            logger.warning(
                "v026 fold: entity_stitch_proposed with empty "
                "stitch_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, stitch_id)
            existing = state["entity_stitches"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            upstream = args.get("upstream_semantic_type_id")
            upstream_str = str(upstream) if upstream else None
            if existing is None:
                state["entity_stitches"][row_key] = {
                    "company_id": tid,
                    "stitch_id": stitch_id,
                    "src_source_id_a": str(args.get("src_source_id_a") or ""),
                    "src_table_a": str(args.get("src_table_a") or ""),
                    "src_column_a": str(args.get("src_column_a") or ""),
                    "src_source_id_b": str(args.get("src_source_id_b") or ""),
                    "src_table_b": str(args.get("src_table_b") or ""),
                    "src_column_b": str(args.get("src_column_b") or ""),
                    "upstream_semantic_type_id": upstream_str,
                    "entity_kind": str(args.get("entity_kind") or ""),
                    "confidence": confidence,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (evidence / confidence / reasoning / strategy /
                # entity_kind / upstream_semantic_type_id — the
                # latest proposal's view). State stays whatever it
                # was — only confirm/reject entries advance the state.
                existing.update(
                    {
                        "confidence": confidence,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "evidence": evidence,
                        "entity_kind": str(args.get("entity_kind") or ""),
                        "upstream_semantic_type_id": upstream_str,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_entity_stitch_confirmed":
        # ----------------------------------------------------------------
        # === L8 Sub-wave A — entity_stitch_confirmed handler ===
        #
        # Admin approves a previously-proposed cross-source entity
        # stitch. The fold UPDATES the existing row's state →
        # "confirmed" and records the approving Person UUID + ts. An
        # unknown stitch_id (no prior proposal in the same replay) is
        # logged + skipped: this can only happen via mis-ordered
        # replays or external write paths that bypass the L8 axis;
        # the fold stays defensive rather than fabricate a row from
        # incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        stitch_id = str(args.get("stitch_id") or "")
        if not stitch_id:
            logger.warning(
                "v026 fold: entity_stitch_confirmed with empty "
                "stitch_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, stitch_id)
            existing = state["entity_stitches"].get(row_key)
            if existing is None:
                logger.warning(
                    "v026 fold: entity_stitch_confirmed for "
                    "unknown stitch_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    stitch_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "confirmed"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("confirmed_by_person_id") or ""
                )
    elif tool == "emit_entity_stitch_rejected":
        # ----------------------------------------------------------------
        # === L8 Sub-wave A — entity_stitch_rejected handler ===
        #
        # Admin rejects a previously-proposed cross-source entity
        # stitch with a categorical reason. Mirror of the confirmed
        # handler: UPDATE state → "rejected", record the rejecting
        # Person UUID + ts. Unknown stitch_id: log + skip (same
        # defensive posture as confirmed).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        stitch_id = str(args.get("stitch_id") or "")
        if not stitch_id:
            logger.warning(
                "v026 fold: entity_stitch_rejected with empty "
                "stitch_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, stitch_id)
            existing = state["entity_stitches"].get(row_key)
            if existing is None:
                logger.warning(
                    "v026 fold: entity_stitch_rejected for "
                    "unknown stitch_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    stitch_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_source_candidate_proposed":
        # ----------------------------------------------------------------
        # === L1 Sub-wave A — source_candidate_proposed handler ===
        #
        # Inference strategy (or one of the 5 source-acquisition trigger
        # flows) proposes a candidate data source for admin triage.
        # Strategies may re-propose the same logical candidate with
        # stronger evidence (e.g. ``kpi_gap`` first, then
        # ``complementarity`` later under the same strategy name as the
        # inference loop matures) — the composite PK
        # ``(company_id, candidate_id)`` collapses re-emission onto
        # the same projection row when ``candidate_id`` matches
        # (deterministic hash of kind/identifier/strategy).
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a
        # candidate that's already promoted/rejected DOES update the
        # row's inference fields (evidence / reasoning / confidence /
        # domain_id_hint / proposed_kind / proposed_identifier — the
        # latest strategy's view) but does NOT regress the state —
        # that requires the operator to explicitly emit a new
        # promote/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        candidate_id = str(args.get("candidate_id") or "")
        if not candidate_id:
            logger.warning(
                "v027 fold: source_candidate_proposed with empty "
                "candidate_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, candidate_id)
            existing = state["source_candidates"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            domain_hint = args.get("domain_id_hint")
            domain_hint_str = str(domain_hint) if domain_hint else None
            if existing is None:
                state["source_candidates"][row_key] = {
                    "company_id": tid,
                    "candidate_id": candidate_id,
                    "proposed_kind": str(args.get("proposed_kind") or ""),
                    "proposed_identifier": str(
                        args.get("proposed_identifier") or ""
                    ),
                    "domain_id_hint": domain_hint_str,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "confidence": confidence,
                    "evidence": evidence,
                    "downstream_source_proposed_id": None,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (proposed_kind / proposed_identifier / domain_id_hint /
                # strategy / reasoning / confidence / evidence — the
                # latest proposal's view). State stays whatever it was
                # — only promote/reject entries advance the state.
                existing.update(
                    {
                        "proposed_kind": str(args.get("proposed_kind") or ""),
                        "proposed_identifier": str(
                            args.get("proposed_identifier") or ""
                        ),
                        "domain_id_hint": domain_hint_str,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "confidence": confidence,
                        "evidence": evidence,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_source_candidate_promoted":
        # ----------------------------------------------------------------
        # === L1 Sub-wave A — source_candidate_promoted handler ===
        #
        # Admin approves a previously-proposed source candidate for
        # promotion into the existing source-pipeline. The fold UPDATES
        # the existing row's state → "promoted" and records the
        # approving Person UUID + ts + optional
        # ``downstream_source_proposed_id`` threading the candidate to
        # its resulting source-pipeline row. An unknown candidate_id
        # (no prior proposal in the same replay) is logged + skipped:
        # this can only happen via mis-ordered replays or external
        # write paths that bypass the L1 axis; the fold stays
        # defensive rather than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        candidate_id = str(args.get("candidate_id") or "")
        if not candidate_id:
            logger.warning(
                "v027 fold: source_candidate_promoted with empty "
                "candidate_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, candidate_id)
            existing = state["source_candidates"].get(row_key)
            if existing is None:
                logger.warning(
                    "v027 fold: source_candidate_promoted for "
                    "unknown candidate_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    candidate_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "promoted"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("promoted_by_person_id") or ""
                )
                downstream = args.get("downstream_source_proposed_id")
                if downstream:
                    existing["downstream_source_proposed_id"] = str(downstream)
    elif tool == "emit_source_candidate_rejected":
        # ----------------------------------------------------------------
        # === L1 Sub-wave A — source_candidate_rejected handler ===
        #
        # Admin rejects a previously-proposed source candidate with a
        # categorical reason. Mirror of the promoted handler: UPDATE
        # state → "rejected", record the rejecting Person UUID + ts.
        # The reason itself is captured on the ledger entry (not on
        # the projection row) — surfaces re-derive via target_id
        # join when they need to display reasons in aggregate (Sub-
        # wave D dashboard rationale). Unknown candidate_id: log +
        # skip (same defensive posture as promoted).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        candidate_id = str(args.get("candidate_id") or "")
        if not candidate_id:
            logger.warning(
                "v027 fold: source_candidate_rejected with empty "
                "candidate_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, candidate_id)
            existing = state["source_candidates"].get(row_key)
            if existing is None:
                logger.warning(
                    "v027 fold: source_candidate_rejected for "
                    "unknown candidate_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    candidate_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_catalog_drift_proposed":
        # ----------------------------------------------------------------
        # === L2 Sub-wave A — catalog_drift_proposed handler ===
        #
        # Inference strategy (``table_set`` / ``column_set`` /
        # ``column_type``) detects a structural change in an external-
        # catalog snapshot and proposes a drift for admin triage.
        # Strategies may re-propose the same logical drift with stronger
        # evidence — the composite PK ``(company_id, drift_id)``
        # collapses re-emission onto the same projection row when
        # ``drift_id`` matches (deterministic hash of source_id /
        # table_id / column / drift_kind / before / after).
        #
        # State transitions are forward-only per the doctrine: every
        # state change emits a new ledger entry. Re-proposal of a drift
        # that's already acknowledged/rejected DOES update the row's
        # inference fields (evidence / reasoning / confidence /
        # before / after / strategy — the latest strategy's view) but
        # does NOT regress the state — that requires the operator to
        # explicitly emit a new acknowledge/reject entry.
        #
        # Replay-stable: the composite PK collapses re-emission onto
        # the same row regardless of replay order. The fold is
        # idempotent — applying the same ledger stream twice produces
        # byte-identical projection rows.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        drift_id = str(args.get("drift_id") or "")
        if not drift_id:
            logger.warning(
                "v028 fold: catalog_drift_proposed with empty "
                "drift_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, drift_id)
            existing = state["catalog_drifts"].get(row_key)
            evidence = args.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            confidence = float(args.get("confidence", 0.0))
            column_val = args.get("column")
            column_str = str(column_val) if column_val else None
            before_val = args.get("before")
            after_val = args.get("after")
            if existing is None:
                state["catalog_drifts"][row_key] = {
                    "company_id": tid,
                    "drift_id": drift_id,
                    "source_id": str(args.get("source_id") or ""),
                    "table_id": str(args.get("table_id") or ""),
                    "column": column_str,
                    "drift_kind": str(args.get("drift_kind") or ""),
                    "before": before_val,
                    "after": after_val,
                    "strategy": str(args.get("strategy") or ""),
                    "reasoning": str(args.get("reasoning") or ""),
                    "confidence": confidence,
                    "evidence": evidence,
                    "state": "proposed",
                    "state_changed_at": entry["ts"],
                    "state_changed_by": None,
                }
            else:
                # Re-proposal updates the inference fields verbatim
                # (source_id / table_id / column / drift_kind /
                # before / after / strategy / reasoning / confidence /
                # evidence — the latest proposal's view). State stays
                # whatever it was — only acknowledge/reject entries
                # advance the state.
                existing.update(
                    {
                        "source_id": str(args.get("source_id") or ""),
                        "table_id": str(args.get("table_id") or ""),
                        "column": column_str,
                        "drift_kind": str(args.get("drift_kind") or ""),
                        "before": before_val,
                        "after": after_val,
                        "strategy": str(args.get("strategy") or ""),
                        "reasoning": str(args.get("reasoning") or ""),
                        "confidence": confidence,
                        "evidence": evidence,
                    }
                )
                if existing["state"] == "proposed":
                    # While still pending resolution, the most recent
                    # proposal owns state_changed_at so the surface
                    # can show "last proposed at" honestly.
                    existing["state_changed_at"] = entry["ts"]
    elif tool == "emit_catalog_drift_acknowledged":
        # ----------------------------------------------------------------
        # === L2 Sub-wave A — catalog_drift_acknowledged handler ===
        #
        # Admin acknowledges a previously-proposed catalog drift as
        # known/expected. The fold UPDATES the existing row's state →
        # "acknowledged" and records the acknowledging Person UUID +
        # ts. No downstream pipeline trigger, no cross-axis effect (L2
        # records human-in-the-loop disposition only). An unknown
        # drift_id (no prior proposal in the same replay) is logged +
        # skipped: this can only happen via mis-ordered replays or
        # external write paths that bypass the L2 axis; the fold stays
        # defensive rather than fabricate a row from incomplete signal.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        drift_id = str(args.get("drift_id") or "")
        if not drift_id:
            logger.warning(
                "v028 fold: catalog_drift_acknowledged with empty "
                "drift_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, drift_id)
            existing = state["catalog_drifts"].get(row_key)
            if existing is None:
                logger.warning(
                    "v028 fold: catalog_drift_acknowledged for "
                    "unknown drift_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    drift_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "acknowledged"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("acknowledged_by_person_id") or ""
                )
    elif tool == "emit_catalog_drift_rejected":
        # ----------------------------------------------------------------
        # === L2 Sub-wave A — catalog_drift_rejected handler ===
        #
        # Admin rejects a previously-proposed catalog drift with a
        # categorical reason. Mirror of the acknowledged handler:
        # UPDATE state → "rejected", record the rejecting Person UUID
        # + ts. The reason itself is captured on the ledger entry (not
        # on the projection row) — surfaces re-derive via target_id
        # join when they need to display reasons in aggregate (Sub-
        # wave D dashboard rationale). Unknown drift_id: log + skip
        # (same defensive posture as acknowledged).
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        drift_id = str(args.get("drift_id") or "")
        if not drift_id:
            logger.warning(
                "v028 fold: catalog_drift_rejected with empty "
                "drift_id at seq=%s; skipping",
                entry.get("seq"),
            )
        else:
            row_key = (tid, drift_id)
            existing = state["catalog_drifts"].get(row_key)
            if existing is None:
                logger.warning(
                    "v028 fold: catalog_drift_rejected for "
                    "unknown drift_id=%s (company=%s) at "
                    "seq=%s; skipping",
                    drift_id,
                    tid,
                    entry.get("seq"),
                )
            else:
                existing["state"] = "rejected"
                existing["state_changed_at"] = entry["ts"]
                existing["state_changed_by"] = str(
                    args.get("rejected_by_person_id") or ""
                )
    elif tool == "emit_catalog_table_imported":
        # ----------------------------------------------------------------
        # === Catalog-mirror Wave 2 Sub-wave A — catalog_table_imported
        #     handler ===
        #
        # Folds a per-table column-metadata import into
        # ``projection_catalog_tables``. The connector emits ONE PEVR
        # cycle per discovered table per snapshot — alongside the
        # summary ``external_catalog_imported`` entry — carrying the
        # ``CatalogColumnSpec`` list for that table.
        #
        # Replay semantics: composite key
        # ``(company_id, source_id, table_id, snapshot_hash)`` collapses
        # re-emission of the same per-table row onto the same projection
        # entry (replay-stable). Different snapshots produce different
        # rows because ``snapshot_hash`` is part of the key — that's the
        # property L2 TableSet needs to diff baseline vs current
        # snapshots from the ledger alone.
        #
        # ``columns`` round-trips as a list of ``{"name", "type"}`` dicts
        # — the ``CatalogColumnSpec`` payload is serialized by the
        # pydantic ``model_dump`` boundary at write time and re-hydrated
        # to ``args`` here as plain dicts. Both forms ('list of dicts'
        # from the wire + 'list of CatalogColumnSpec' from native
        # roundtrip) are accepted defensively; empty columns are valid.
        # ----------------------------------------------------------------
        tid = str(entry["company_id"])
        source_id = str(args.get("source_id") or "")
        snapshot_hash = str(args.get("snapshot_hash") or "")
        table_id = str(args.get("table_id") or "")
        if not source_id or not snapshot_hash or not table_id:
            logger.warning(
                "v029 fold: catalog_table_imported with empty key "
                "(source_id=%r snapshot_hash=%r table_id=%r) at seq=%s; "
                "skipping",
                source_id,
                snapshot_hash,
                table_id,
                entry.get("seq"),
            )
        else:
            raw_columns = args.get("columns", []) or []
            columns_list: list[dict[str, Any]] = []
            for col in raw_columns:
                if isinstance(col, dict):
                    name = col.get("name")
                    if not isinstance(name, str) or not name:
                        # Skip malformed entries defensively; payload
                        # validator already rejects them at write time.
                        continue
                    type_val = col.get("type")
                    columns_list.append(
                        {
                            "name": name,
                            "type": str(type_val) if type_val is not None else None,
                        }
                    )
                else:
                    # Pydantic CatalogColumnSpec instances arrive after
                    # native round-trip through ``model_dump``; handle
                    # both shapes.
                    name = getattr(col, "name", None)
                    if not isinstance(name, str) or not name:
                        continue
                    type_val = getattr(col, "type", None)
                    columns_list.append(
                        {
                            "name": name,
                            "type": str(type_val) if type_val is not None else None,
                        }
                    )
            row_key = (tid, source_id, table_id, snapshot_hash)
            state["catalog_tables"][row_key] = {
                "company_id": tid,
                "source_id": source_id,
                "table_id": table_id,
                "snapshot_hash": snapshot_hash,
                "columns": columns_list,
                "ts": entry["ts"],
            }


def _recompute_ramp(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic formulas: integer percentages 0..100, returned as str."""
    src_count = len(state["sources"])
    profiled = sum(1 for s in state["sources"].values() if s["status"] == "profiled")
    mem_count = len(state["memory"])
    values = {
        "ontology": min(100, mem_count * 5),
        "schema": min(100, profiled * 20),
        "business_definitions": min(100, mem_count * 10),
        "kpi_relational": min(100, src_count * 15),
        "conversational": min(100, state["chat_count"] * 2),
        "operational": min(100, state["resolve_count"] * 5),
    }
    return [{"axis": a, "value": str(values[a])} for a in RAMP_AXES]


def _initial_projection_state() -> dict[str, Any]:
    """Seed dict for both DB-backed and in-memory replay folds.

    Every key here is touched by some branch of `_apply_execute` (or the
    chat / resolve counters at the call site). Keep the two paths aligned
    by sharing this initializer — see O-A1 for the drift bug this prevents.
    """
    return {
        "sources": {},
        "memory": [],
        "kpi_nodes": {},
        "persons": {},
        "person_identities": {},
        "installs": {},
        "roles": {},
        "data_products": {},
        "data_product_runs": {},
        "data_product_consumption": {},
        "notebooks": {},
        "notebook_runs": {},
        "setup_progress": {},
        "mcp_calls": {},
        "topics": {},
        "external_catalog": {},
        "external_lineage": {},
        "external_policy": {},
        "external_metric": {},
        "agents": {},
        "agent_grants": {},
        # Wave 3 Task 3 — agent_query + credential PEVR folds.
        "agent_queries": {},
        "credentials": {},
        # Wave 3 Task 4 — §4.5 compounding-loop folds.
        "query_outcomes": {},
        "query_templates": {},
        # L3 Sub-wave A — lake-side lineage-discovery loop. Keyed on
        # ``(company_id, edge_id)`` tuple so re-proposal collapses onto
        # the same row regardless of replay order.
        "lineage_edges": {},
        # L7 Sub-wave A — lake-side quality-checks discovery loop. Keyed
        # on ``(company_id, check_id)`` tuple — same composite-PK
        # collapse pattern as ``lineage_edges``.
        "quality_checks": {},
        # L4 Sub-wave A — lake-side schema-evolution-impact discovery
        # loop. Keyed on ``(company_id, impact_id)`` tuple — same
        # composite-PK collapse pattern as ``lineage_edges`` and
        # ``quality_checks``.
        "schema_impacts": {},
        # L5 Sub-wave A — lake-side sample-data fingerprinting discovery
        # loop. Keyed on ``(company_id, type_id)`` tuple — same
        # composite-PK collapse pattern as ``lineage_edges`` /
        # ``quality_checks`` / ``schema_impacts``.
        "semantic_types": {},
        # L6 Sub-wave A — lake-side column-level governance
        # classification discovery loop. Keyed on
        # ``(company_id, classification_id)`` tuple — same composite-PK
        # collapse pattern as ``semantic_types`` above.
        "column_classifications": {},
        # L8 Sub-wave A — lake-side cross-source entity-stitch
        # discovery loop. Keyed on ``(company_id, stitch_id)`` tuple
        # — same composite-PK collapse pattern as
        # ``column_classifications`` above.
        "entity_stitches": {},
        # L1 Sub-wave A — lake-side source-candidate triage loop.
        # Keyed on ``(company_id, candidate_id)`` tuple — same
        # composite-PK collapse pattern as ``entity_stitches`` above.
        "source_candidates": {},
        # L2 Sub-wave A — lake-side catalog-drift detection loop.
        # Keyed on ``(company_id, drift_id)`` tuple — same composite-
        # PK collapse pattern as ``source_candidates`` above. L2 is
        # the FINAL planned axis in this generation per spec §11.
        "catalog_drifts": {},
        # Catalog-mirror Wave 2 Sub-wave A — per-table column-metadata
        # substrate. Keyed on
        # ``(company_id, source_id, table_id, snapshot_hash)`` so that
        # the same (source, table) across multiple snapshots produces
        # distinct rows (L2 TableSet needs baseline + current to
        # coexist for diff computation).
        "catalog_tables": {},
        # Map (prior phase's entry_id) → credential row id so subsequent
        # PEVR phases thread back to the same projection row.
        "credential_chain": {},
        "chat_count": 0,
        "resolve_count": 0,
    }


def _state_to_projections(state: dict[str, Any]) -> Projections:
    """Materialize a `Projections` dataclass from a folded state dict.

    Shared by `build_projections` (DB-backed) and `InMemoryLedger.replay()`
    so the two paths produce byte-identical output for the same row stream.
    See O-A1 for the drift bug this prevents.
    """
    # Deterministic iteration: sort by source_id / kpi_id / written_at + memory_id.
    sources = [state["sources"][k] for k in sorted(state["sources"].keys())]
    kpi_nodes = [state["kpi_nodes"][k] for k in sorted(state["kpi_nodes"].keys())]
    memory = sorted(state["memory"], key=lambda m: (str(m["memory_id"]),))
    persons = [state["persons"][k] for k in sorted(state["persons"].keys())]
    person_identities = [
        state["person_identities"][k]
        for k in sorted(state["person_identities"].keys())
    ]
    installs = [state["installs"][k] for k in sorted(state["installs"].keys())]
    roles = [state["roles"][k] for k in sorted(state["roles"].keys(), key=str)]
    # Strip private bookkeeping (`_cells`) before exposing notebooks.
    notebooks = []
    for k in sorted(state["notebooks"].keys()):
        nb = dict(state["notebooks"][k])
        nb.pop("_cells", None)
        notebooks.append(nb)
    data_products = [
        state["data_products"][k] for k in sorted(state["data_products"].keys())
    ]
    data_product_runs = [
        state["data_product_runs"][k]
        for k in sorted(state["data_product_runs"].keys(), key=str)
    ]
    data_product_consumption = [
        state["data_product_consumption"][k]
        for k in sorted(state["data_product_consumption"].keys(), key=str)
    ]
    notebook_runs = [
        state["notebook_runs"][k]
        for k in sorted(state["notebook_runs"].keys(), key=str)
    ]
    setup_progress = [
        state["setup_progress"][k]
        for k in sorted(state["setup_progress"].keys(), key=str)
    ]
    mcp_calls = [
        state["mcp_calls"][k]
        for k in sorted(state["mcp_calls"].keys(), key=str)
    ]
    topics = [
        state["topics"][k]
        for k in sorted(state["topics"].keys(), key=str)
    ]
    external_catalog = [
        state["external_catalog"][k]
        for k in sorted(state["external_catalog"].keys(), key=str)
    ]
    external_lineage = [
        state["external_lineage"][k]
        for k in sorted(state["external_lineage"].keys(), key=str)
    ]
    external_policy = [
        state["external_policy"][k]
        for k in sorted(state["external_policy"].keys(), key=str)
    ]
    external_metric = [
        state["external_metric"][k]
        for k in sorted(state["external_metric"].keys(), key=str)
    ]
    agents = [
        state["agents"][k]
        for k in sorted(state["agents"].keys(), key=str)
    ]
    agent_grants = [
        state["agent_grants"][k]
        for k in sorted(state["agent_grants"].keys(), key=str)
    ]
    # Wave 3 Task 3 — sort by row id for byte stability. The /trace
    # surface joins back via audit_trail_id (== row id) so ordering
    # by id keeps re-renders stable.
    agent_queries = [
        state["agent_queries"][k]
        for k in sorted(state["agent_queries"].keys(), key=str)
    ]
    credentials = [
        state["credentials"][k]
        for k in sorted(state["credentials"].keys(), key=str)
    ]
    # Wave 3 Task 4 — sort by row id for byte stability. Per-tenant
    # delete+insert persist + deterministic row ids means a re-fold
    # produces byte-identical projection_query_* state.
    query_outcomes = [
        state["query_outcomes"][k]
        for k in sorted(state["query_outcomes"].keys(), key=str)
    ]
    query_templates = [
        state["query_templates"][k]
        for k in sorted(state["query_templates"].keys(), key=str)
    ]
    # L3 Sub-wave A — sort by (company_id, edge_id) for byte stability.
    # Per-tenant delete+insert persist + deterministic composite PK means
    # a re-fold produces byte-identical projection_lineage_edges state.
    lineage_edges = [
        state["lineage_edges"][k]
        for k in sorted(state["lineage_edges"].keys(), key=lambda t: (t[0], t[1]))
    ]
    # L7 Sub-wave A — sort by (company_id, check_id) for byte stability.
    # Same shape as lineage_edges above; the composite PK keeps re-fold
    # byte-identical across replays.
    quality_checks = [
        state["quality_checks"][k]
        for k in sorted(state["quality_checks"].keys(), key=lambda t: (t[0], t[1]))
    ]
    # L4 Sub-wave A — sort by (company_id, impact_id) for byte stability.
    # Same shape as lineage_edges / quality_checks above; the composite
    # PK keeps re-fold byte-identical across replays.
    schema_impacts = [
        state["schema_impacts"][k]
        for k in sorted(state["schema_impacts"].keys(), key=lambda t: (t[0], t[1]))
    ]
    # L5 Sub-wave A — sort by (company_id, type_id) for byte stability.
    # Same shape as schema_impacts above; the composite PK keeps re-fold
    # byte-identical across replays.
    semantic_types = [
        state["semantic_types"][k]
        for k in sorted(state["semantic_types"].keys(), key=lambda t: (t[0], t[1]))
    ]
    # L6 Sub-wave A — sort by (company_id, classification_id) for byte
    # stability. Same shape as semantic_types above; the composite PK
    # keeps re-fold byte-identical across replays.
    column_classifications = [
        state["column_classifications"][k]
        for k in sorted(
            state["column_classifications"].keys(), key=lambda t: (t[0], t[1])
        )
    ]
    # L8 Sub-wave A — sort by (company_id, stitch_id) for byte
    # stability. Same shape as column_classifications above; the
    # composite PK keeps re-fold byte-identical across replays.
    entity_stitches = [
        state["entity_stitches"][k]
        for k in sorted(
            state["entity_stitches"].keys(), key=lambda t: (t[0], t[1])
        )
    ]
    # L1 Sub-wave A — sort by (company_id, candidate_id) for byte
    # stability. Same shape as entity_stitches above; the composite
    # PK keeps re-fold byte-identical across replays.
    source_candidates = [
        state["source_candidates"][k]
        for k in sorted(
            state["source_candidates"].keys(), key=lambda t: (t[0], t[1])
        )
    ]
    # L2 Sub-wave A — sort by (company_id, drift_id) for byte
    # stability. Same shape as source_candidates above; the composite
    # PK keeps re-fold byte-identical across replays. L2 is the FINAL
    # planned axis in this generation per spec §11.
    catalog_drifts = [
        state["catalog_drifts"][k]
        for k in sorted(
            state["catalog_drifts"].keys(), key=lambda t: (t[0], t[1])
        )
    ]
    # Catalog-mirror Wave 2 Sub-wave A — sort by
    # (company_id, source_id, table_id, snapshot_hash) for byte
    # stability. The composite PK keeps re-fold byte-identical
    # across replays; the snapshot_hash leg lets multiple snapshots
    # of the same (source, table) coexist as distinct rows so
    # downstream L2/L8 strategies can diff them.
    catalog_tables = [
        state["catalog_tables"][k]
        for k in sorted(
            state["catalog_tables"].keys(),
            key=lambda t: (t[0], t[1], t[2], t[3]),
        )
    ]

    return Projections(
        sources=sources,
        memory=memory,
        kpi_nodes=kpi_nodes,
        ramp=_recompute_ramp(state),
        persons=persons,
        person_identities=person_identities,
        installs=installs,
        roles=roles,
        data_products=data_products,
        data_product_runs=data_product_runs,
        data_product_consumption=data_product_consumption,
        notebooks=notebooks,
        notebook_runs=notebook_runs,
        setup_progress=setup_progress,
        mcp_calls=mcp_calls,
        topics=topics,
        external_catalog=external_catalog,
        external_lineage=external_lineage,
        external_policy=external_policy,
        external_metric=external_metric,
        agents=agents,
        agent_grants=agent_grants,
        agent_queries=agent_queries,
        credentials=credentials,
        query_outcomes=query_outcomes,
        query_templates=query_templates,
        lineage_edges=lineage_edges,
        quality_checks=quality_checks,
        schema_impacts=schema_impacts,
        semantic_types=semantic_types,
        column_classifications=column_classifications,
        entity_stitches=entity_stitches,
        source_candidates=source_candidates,
        catalog_drifts=catalog_drifts,
        catalog_tables=catalog_tables,
    )


async def build_projections(
    session: AsyncSession,
    company_id: UUID,
    until_ts: datetime | None = None,
) -> Projections:
    rows = await fetch_entries(session, company_id, until_ts=until_ts)
    state: dict[str, Any] = _initial_projection_state()
    for e in rows:
        k = e["kind"]
        # Wave 3 Task 3 — agent_query + credential PEVR cycles write the
        # typed payload directly at every envelope phase; fold them via
        # the envelope-aware handler regardless of which phase the entry
        # carries. Shape detection inside ``_apply_pevr_envelope`` keeps
        # this safe for normal ``emit_*`` writes (they're skipped).
        if k in ("propose", "execute", "verify", "resolve"):
            _apply_pevr_envelope(e, state)
        if k == "execute":
            _apply_execute(e, state)
        elif k in ("chat_received", "chat_sent"):
            state["chat_count"] += 1
        elif k in (
            "chat_reply_proposed",
            "chat_reply_executed",
            "chat_reply_verified",
            "chat_reply_resolved",
        ):
            # v1: chat_reply_* entries are audit-only; no projection table fold.
            # Future wave can add a projection_chat_replies if needed for /trace.
            pass
        elif k == "resolve":
            state["resolve_count"] += 1

    return _state_to_projections(state)


# ---------------------------------------------------------------------------
# Persisting projections to the SQL projection_* tables.
#
# The in-memory ``Projections`` dataclass is the canonical fold; this helper
# materialises it into the SQL tables so dashboards and read-only consumers
# can serve queries without re-folding the entire ledger on every request.
#
# Strategy: tenant-scoped delete + insert. Cheaper than per-row upserts and
# safe because the in-memory fold is the single source of truth — no other
# writer touches projection_* tables. Per-tenant scoping ensures a runner
# for tenant A never blows away tenant B's rows.
#
# Backend-portable: uses Core insert/delete (no Postgres-specific
# ``ON CONFLICT``) so the same code path runs on Postgres (production) and
# SQLite (tests). The whole batch lands inside the caller's transaction.
# ---------------------------------------------------------------------------


def _ramp_rows_for_persist(
    company_id: UUID,
    ramp: list[dict[str, Any]],
    *,
    as_of: datetime,
) -> list[dict[str, Any]]:
    return [
        {
            "company_id": company_id,
            "axis": r["axis"],
            "value": r["value"],
            "as_of": as_of,
        }
        for r in ramp
    ]


def _kpi_node_rows_for_persist(
    company_id: UUID, kpi_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate the in-memory KPI dict (``id`` keyed) to the table row shape.

    The builder stashes the raw ``KpiNode`` payload (``args``) which uses
    ``id`` as the stable string key. The SQL column is ``node_id`` and the
    table is keyed on ``(company_id, node_id)``.
    """
    out: list[dict[str, Any]] = []
    for n in kpi_nodes:
        out.append(
            {
                "company_id": company_id,
                "node_id": n.get("node_id") or n.get("id"),
                "name": n["name"],
                "domain_id": n.get("domain_id"),
                "owner_person_id": n.get("owner_person_id"),
                "parent_node_id": n.get("parent_node_id"),
                "source_resource_id": n.get("source_resource_id"),
                "metric_type": n.get("metric_type", "other"),
                "confidence": n.get("confidence", "proposed"),
            }
        )
    return out


async def persist_projections(
    conn: AsyncConnection,
    company_id: UUID,
    projections: Projections,
    *,
    as_of: datetime | None = None,
) -> None:
    """Materialize ``projections`` into the ``projection_*`` SQL tables.

    Tenant-scoped: only rows belonging to ``company_id`` (or its
    ``tenant_id`` synonym in the identity tables) are deleted before the
    rebuild. Idempotent — calling twice with the same ``Projections``
    leaves the tables in the same state byte-for-byte.

    Designed to be called from a background runner (see
    ``apps/worm-core/src/wormbase_core/projection_runner.py``) with the
    full ``Projections`` from a fresh ``build_projections`` fold.
    """
    now = as_of or datetime.now(tz=UTC)

    # ------------------------------------------------------------------
    # Tenant-scoped wipe of prior rows.
    # ------------------------------------------------------------------
    await conn.execute(
        delete(projection_sources).where(projection_sources.c.company_id == company_id)
    )
    await conn.execute(
        delete(projection_memory).where(projection_memory.c.company_id == company_id)
    )
    await conn.execute(
        delete(projection_kpi_nodes).where(
            projection_kpi_nodes.c.company_id == company_id
        )
    )
    await conn.execute(
        delete(projection_ramp).where(projection_ramp.c.company_id == company_id)
    )
    await conn.execute(
        delete(projection_persons).where(projection_persons.c.tenant_id == company_id)
    )
    await conn.execute(
        delete(projection_person_identities).where(
            projection_person_identities.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_installs).where(
            projection_installs.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_setup_progress).where(
            projection_setup_progress.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_roles).where(projection_roles.c.tenant_id == company_id)
    )
    await conn.execute(
        delete(projection_data_products).where(
            projection_data_products.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_data_product_runs).where(
            projection_data_product_runs.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_data_product_consumption).where(
            projection_data_product_consumption.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_notebooks).where(
            projection_notebooks.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_notebook_runs).where(
            projection_notebook_runs.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_mcp_calls).where(
            projection_mcp_calls.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_topics).where(
            projection_topics.c.tenant_id == company_id
        )
    )
    await conn.execute(
        delete(projection_external_catalog).where(
            projection_external_catalog.c.company_id == company_id
        )
    )
    await conn.execute(
        delete(projection_external_lineage).where(
            projection_external_lineage.c.company_id == company_id
        )
    )
    await conn.execute(
        delete(projection_external_policy).where(
            projection_external_policy.c.company_id == company_id
        )
    )
    await conn.execute(
        delete(projection_external_metric).where(
            projection_external_metric.c.company_id == company_id
        )
    )
    # projection_agents / projection_agent_grants columns are String per
    # v012 + v013, so the tenant-scoped delete compares against
    # str(company_id) rather than the raw UUID.
    await conn.execute(
        delete(projection_agents).where(
            projection_agents.c.company_id == str(company_id)
        )
    )
    await conn.execute(
        delete(projection_agent_grants).where(
            projection_agent_grants.c.company_id == str(company_id)
        )
    )
    # ``projection_agent_queries`` / ``projection_credentials`` are
    # ``String``-keyed (v014 + v015 migrations) — compare against the
    # stringified company_id for the tenant-scoped wipe.
    await conn.execute(
        delete(projection_agent_queries).where(
            projection_agent_queries.c.company_id == str(company_id)
        )
    )
    await conn.execute(
        delete(projection_credentials).where(
            projection_credentials.c.company_id == str(company_id)
        )
    )
    # ``projection_query_outcomes`` / ``projection_query_templates`` are
    # ``String``-keyed (v016 + v017 migrations) — compare against the
    # stringified company_id for the tenant-scoped wipe.
    await conn.execute(
        delete(projection_query_outcomes).where(
            projection_query_outcomes.c.company_id == str(company_id)
        )
    )
    await conn.execute(
        delete(projection_query_templates).where(
            projection_query_templates.c.company_id == str(company_id)
        )
    )
    # ``projection_lineage_edges`` is ``String``-keyed on company_id
    # (v021 composite PK with edge_id) — compare against the
    # stringified company_id for the tenant-scoped wipe.
    await conn.execute(
        delete(projection_lineage_edges).where(
            projection_lineage_edges.c.company_id == str(company_id)
        )
    )
    # ``projection_quality_checks`` is ``String``-keyed on company_id
    # (v022 composite PK with check_id) — same tenant-scoped wipe
    # pattern as projection_lineage_edges above.
    await conn.execute(
        delete(projection_quality_checks).where(
            projection_quality_checks.c.company_id == str(company_id)
        )
    )
    # ``projection_schema_impacts`` is ``String``-keyed on company_id
    # (v023 composite PK with impact_id) — same tenant-scoped wipe
    # pattern as projection_lineage_edges / projection_quality_checks
    # above.
    await conn.execute(
        delete(projection_schema_impacts).where(
            projection_schema_impacts.c.company_id == str(company_id)
        )
    )
    # ``projection_semantic_types`` is ``String``-keyed on company_id
    # (v024 composite PK with type_id) — same tenant-scoped wipe
    # pattern as projection_schema_impacts above.
    await conn.execute(
        delete(projection_semantic_types).where(
            projection_semantic_types.c.company_id == str(company_id)
        )
    )
    # ``projection_column_classifications`` is ``String``-keyed on
    # company_id (v025 composite PK with classification_id) — same
    # tenant-scoped wipe pattern as projection_semantic_types above.
    await conn.execute(
        delete(projection_column_classifications).where(
            projection_column_classifications.c.company_id == str(company_id)
        )
    )
    # ``projection_entity_stitches`` is ``String``-keyed on company_id
    # (v026 composite PK with stitch_id) — same tenant-scoped wipe
    # pattern as projection_column_classifications above.
    await conn.execute(
        delete(projection_entity_stitches).where(
            projection_entity_stitches.c.company_id == str(company_id)
        )
    )
    # ``projection_source_candidates`` is ``String``-keyed on company_id
    # (v027 composite PK with candidate_id) — same tenant-scoped wipe
    # pattern as projection_entity_stitches above.
    await conn.execute(
        delete(projection_source_candidates).where(
            projection_source_candidates.c.company_id == str(company_id)
        )
    )
    # ``projection_catalog_drifts`` is ``String``-keyed on company_id
    # (v028 composite PK with drift_id) — same tenant-scoped wipe
    # pattern as projection_source_candidates above.
    await conn.execute(
        delete(projection_catalog_drifts).where(
            projection_catalog_drifts.c.company_id == str(company_id)
        )
    )
    # ``projection_catalog_tables`` is ``String``-keyed on company_id
    # (v029 composite PK with source_id, table_id, snapshot_hash) —
    # same tenant-scoped wipe pattern as projection_catalog_drifts
    # above. Wave 2 substrate for L2 TableSet + L8 SchemaShape.
    await conn.execute(
        delete(projection_catalog_tables).where(
            projection_catalog_tables.c.company_id == str(company_id)
        )
    )

    # ------------------------------------------------------------------
    # Re-insert from the freshly folded Projections dataclass.
    # ------------------------------------------------------------------
    if projections.sources:
        rows = [{"company_id": company_id, **s} for s in projections.sources]
        await conn.execute(projection_sources.insert(), rows)

    if projections.memory:
        rows = [{"company_id": company_id, **m} for m in projections.memory]
        await conn.execute(projection_memory.insert(), rows)

    kpi_rows = _kpi_node_rows_for_persist(company_id, projections.kpi_nodes)
    if kpi_rows:
        await conn.execute(projection_kpi_nodes.insert(), kpi_rows)

    if projections.ramp:
        await conn.execute(
            projection_ramp.insert(),
            _ramp_rows_for_persist(company_id, projections.ramp, as_of=now),
        )

    if projections.persons:
        await conn.execute(projection_persons.insert(), list(projections.persons))

    if projections.person_identities:
        await conn.execute(
            projection_person_identities.insert(),
            list(projections.person_identities),
        )

    if projections.installs:
        await conn.execute(projection_installs.insert(), list(projections.installs))

    if projections.setup_progress:
        await conn.execute(
            projection_setup_progress.insert(), list(projections.setup_progress),
        )

    if projections.roles:
        await conn.execute(projection_roles.insert(), list(projections.roles))

    if projections.data_products:
        await conn.execute(
            projection_data_products.insert(), list(projections.data_products),
        )

    if projections.data_product_runs:
        await conn.execute(
            projection_data_product_runs.insert(),
            list(projections.data_product_runs),
        )

    if projections.data_product_consumption:
        await conn.execute(
            projection_data_product_consumption.insert(),
            list(projections.data_product_consumption),
        )

    if projections.notebooks:
        await conn.execute(projection_notebooks.insert(), list(projections.notebooks))

    if projections.notebook_runs:
        await conn.execute(
            projection_notebook_runs.insert(), list(projections.notebook_runs),
        )

    if projections.mcp_calls:
        await conn.execute(
            projection_mcp_calls.insert(), list(projections.mcp_calls),
        )

    if projections.topics:
        # Topic rows carry the tenant_id explicitly because the same
        # row dict serves both the in-memory builder output and the
        # SQL persist path. Mirror the patterns used by the other
        # *_runs / *_consumption tables (per-row dict).
        topic_rows = [{"tenant_id": company_id, **t} for t in projections.topics]
        await conn.execute(projection_topics.insert(), topic_rows)

    if projections.external_catalog:
        # Builder rows already carry ``company_id`` because the fold reads
        # it from the entry; pass them through unchanged. Same shape as
        # the projection_topics path: tenant-scoped delete already cleared
        # the prior rows, and the deterministic ``id`` column means the
        # INSERT is idempotent across replays of the same ledger stream.
        await conn.execute(
            projection_external_catalog.insert(),
            list(projections.external_catalog),
        )

    if projections.external_lineage:
        await conn.execute(
            projection_external_lineage.insert(),
            list(projections.external_lineage),
        )

    if projections.external_policy:
        # Builder rows already carry ``company_id`` because the fold
        # reads it from the entry. Deterministic per-(source, fqn) row
        # id means INSERT is replay-idempotent after the tenant-scoped
        # delete above.
        await conn.execute(
            projection_external_policy.insert(),
            list(projections.external_policy),
        )

    if projections.external_metric:
        # Same shape as external_policy: builder rows carry company_id,
        # deterministic row id keyed on (source, name) makes INSERT
        # replay-idempotent.
        await conn.execute(
            projection_external_metric.insert(),
            list(projections.external_metric),
        )

    if projections.agents:
        # Builder rows carry their own company_id taken from the entry's
        # tenant scope at fold time. Deterministic row id (= agent_id)
        # makes the insert replay-idempotent after the tenant-scoped
        # delete above.
        await conn.execute(
            projection_agents.insert(),
            list(projections.agents),
        )

    if projections.agent_grants:
        # Row id deterministic over (company, agent, grant_kind,
        # grant_target) — revoke-after-active reuses the same id, so
        # INSERT works cleanly after the tenant-scoped wipe.
        await conn.execute(
            projection_agent_grants.insert(),
            list(projections.agent_grants),
        )

    if projections.agent_queries:
        # Wave 3 Task 3 — agent_query PEVR cycles. Rows carry their own
        # ``company_id`` (string form) and a row id == audit_trail_id
        # that's replay-stable across the four phases.
        await conn.execute(
            projection_agent_queries.insert(),
            list(projections.agent_queries),
        )

    if projections.credentials:
        # Same pattern as agent_queries — rows carry company_id and a
        # deterministic per-cycle row id derived from the propose entry.
        await conn.execute(
            projection_credentials.insert(),
            list(projections.credentials),
        )

    if projections.query_outcomes:
        # Wave 3 Task 4 — §4.5 compounding-loop outcomes. Rows carry
        # ``company_id`` (string form) and a row id derived from the
        # execute entry_id (replay-stable). The ``embedding`` column
        # is intentionally absent from the mirror — embeddings are
        # written at write time by the inference-router path, not by
        # the fold, and the fold-side persist must stay dialect-
        # portable (Postgres pgvector vs SQLite JSON).
        await conn.execute(
            projection_query_outcomes.insert(),
            list(projections.query_outcomes),
        )

    if projections.query_templates:
        # Wave 3 Task 4 — promoted query templates. Rows carry
        # ``company_id`` (string form) and a row id derived from the
        # promotion's propose entry_id. ``hit_count`` defaults to 0
        # at fold time; the query-cache path increments it at read
        # time outside the projection fold.
        await conn.execute(
            projection_query_templates.insert(),
            list(projections.query_templates),
        )

    if projections.lineage_edges:
        # L3 Sub-wave A — folded view of lineage edges. Rows carry
        # ``company_id`` (string form) + ``edge_id`` (the composite
        # PK per v021). Tenant-scoped delete above cleared prior
        # rows; the deterministic ``edge_id`` (= upstream hash of the
        # endpoints) means INSERT is replay-idempotent across folds
        # of the same ledger stream.
        await conn.execute(
            projection_lineage_edges.insert(),
            list(projections.lineage_edges),
        )

    if projections.quality_checks:
        # L7 Sub-wave A — folded view of quality checks. Rows carry
        # ``company_id`` (string form) + ``check_id`` (the composite
        # PK per v022). Same shape as lineage_edges above; the
        # deterministic ``check_id`` (= upstream hash of the table /
        # column / kind / config) makes INSERT replay-idempotent.
        await conn.execute(
            projection_quality_checks.insert(),
            list(projections.quality_checks),
        )

    if projections.schema_impacts:
        # L4 Sub-wave A — folded view of schema-evolution impacts.
        # Rows carry ``company_id`` (string form) + ``impact_id`` (the
        # composite PK per v023). Same shape as lineage_edges /
        # quality_checks above; the deterministic ``impact_id`` (=
        # upstream hash of the source / src column / change kind /
        # target endpoints) makes INSERT replay-idempotent.
        await conn.execute(
            projection_schema_impacts.insert(),
            list(projections.schema_impacts),
        )

    if projections.semantic_types:
        # L5 Sub-wave A — folded view of sample-data fingerprinting
        # semantic-type proposals. Rows carry ``company_id`` (string
        # form) + ``type_id`` (the composite PK per v024). Same shape
        # as lineage_edges / quality_checks / schema_impacts above; the
        # deterministic ``type_id`` (= upstream hash of the
        # table_id / column / semantic_type) makes INSERT replay-
        # idempotent.
        await conn.execute(
            projection_semantic_types.insert(),
            list(projections.semantic_types),
        )

    if projections.column_classifications:
        # L6 Sub-wave A — folded view of column-level governance
        # classification proposals. Rows carry ``company_id`` (string
        # form) + ``classification_id`` (the composite PK per v025).
        # Same shape as semantic_types above; the deterministic
        # ``classification_id`` (= upstream hash of the table_id /
        # column / classification_level / strategy) makes INSERT
        # replay-idempotent.
        await conn.execute(
            projection_column_classifications.insert(),
            list(projections.column_classifications),
        )

    if projections.entity_stitches:
        # L8 Sub-wave A — folded view of cross-source entity-stitch
        # proposals. Rows carry ``company_id`` (string form) +
        # ``stitch_id`` (the composite PK per v026). Same shape as
        # column_classifications above; the deterministic
        # ``stitch_id`` (= upstream hash of the canonicalised
        # ``(src_source_id_a, src_table_a, src_column_a,
        # src_source_id_b, src_table_b, src_column_b)`` sextuple)
        # makes INSERT replay-idempotent.
        await conn.execute(
            projection_entity_stitches.insert(),
            list(projections.entity_stitches),
        )

    if projections.source_candidates:
        # L1 Sub-wave A — folded view of source-candidate triage
        # proposals. Rows carry ``company_id`` (string form) +
        # ``candidate_id`` (the composite PK per v027). Same shape
        # as entity_stitches above; the deterministic
        # ``candidate_id`` (= upstream hash of
        # ``(proposed_kind, proposed_identifier, strategy)`` via
        # ``make_candidate_id``) makes INSERT replay-idempotent.
        await conn.execute(
            projection_source_candidates.insert(),
            list(projections.source_candidates),
        )

    if projections.catalog_drifts:
        # L2 Sub-wave A — folded view of catalog-drift detection
        # proposals. Rows carry ``company_id`` (string form) +
        # ``drift_id`` (the composite PK per v028). Same shape as
        # source_candidates above; the deterministic ``drift_id``
        # (= upstream hash of ``(source_id, table_id, column,
        # drift_kind, before, after)`` via ``make_drift_id``) makes
        # INSERT replay-idempotent. L2 is the FINAL planned axis in
        # this generation per spec §11.
        await conn.execute(
            projection_catalog_drifts.insert(),
            list(projections.catalog_drifts),
        )

    if projections.catalog_tables:
        # Catalog-mirror Wave 2 Sub-wave A — folded per-table
        # column-metadata substrate. Rows carry ``company_id`` (string
        # form) + ``source_id`` + ``table_id`` + ``snapshot_hash``
        # (the v029 composite PK). Multiple snapshots of the same
        # (source, table) coexist as distinct rows because the
        # snapshot_hash leg of the PK keeps them isolated — that's
        # the property L2 TableSet + L8 SchemaShape need for
        # baseline-vs-current diff computation. INSERT is replay-
        # idempotent after the tenant-scoped delete above.
        await conn.execute(
            projection_catalog_tables.insert(),
            list(projections.catalog_tables),
        )
