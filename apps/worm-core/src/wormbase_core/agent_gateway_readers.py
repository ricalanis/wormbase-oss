"""Production readers for the wormbase-agent-gateway gold-artifact Protocols.

Wave 3.2 Hole #3 added MCP tools for ``decisions.*``, ``processes.*``, and
``data_products.*`` to the agent-gateway, each accepting an injected reader
Protocol (``DecisionReader``, ``ProcessMapReader``, ``DataProductReader``).
The integration tests there pass in-memory stubs.

This module is the production wire-up: raw-ledger implementations that
satisfy those Protocols. They live in worm-core because worm-core owns
the ``Ledger`` instance and the eventual gateway construction site —
mirroring how ``write_actions.py``, ``data_product_actions.py``, and
``mcp_server.py`` already live here.

Architecture:

- Each reader holds a reference to the canonical ``Ledger`` (Postgres-backed)
  or ``InMemoryLedger``. Both expose ``fetch(company_id) -> list[entry-dict]``
  with the same row shape, so a single implementation works for both.
- Queries scan ledger entries with ``kind == "execute"`` whose payload
  carries the canonical emit tool. Latest-status-per-resource is enforced
  by traversing newest-first and de-duping on the resource id — the same
  semantics the dashboard's ``decision-chain.ts`` / ``getProcessMaps``
  accessors implement with ``SELECT DISTINCT ON``.
- No separate ``projection_*`` table is required for v1.1. Gold artifacts
  are read infrequently relative to chat messages; a dedicated projection
  would add maintenance load. If hot-path latency becomes a concern we
  promote to a projection in a follow-up; the Protocol shape doesn't
  change.

v1.3 adds :class:`LedgerAgentGrantReader` — the production grant_lookup
the four governance gates compose against. Pre-v1.3 the construction
site shipped ``_empty_grant_lookup`` which denied every MCP call by
returning an empty sequence. The reader walks ``emit_agent_grant``
execute entries, dedupes on the canonical (agent_id, grant_kind,
grant_target) triple keeping the most-recent status (active or
revoked), and filters to status='active' for the AgentAccessGate /
CostGate consumers.

See ``docs/superpowers/plans/2026-05-13-semantic-layer-v1.1-production-hardening.md``
Tasks 5 and 6 for the full design context and
``docs/superpowers/notes/2026-05-14-semantic-layer-v1.2-shipped.md``
follow-up #1 for the v1.3 grant-reader scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence
from uuid import UUID

from wormbase_agent_gateway.identity import AgentGrant
from wormbase_inference import AgentID


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a ``Ledger``-like object.

    ``wormbase_ledger.Ledger`` (Postgres) and ``InMemoryLedger`` both
    satisfy this; we type against the protocol so neither concrete
    binding leaks into the reader implementations.
    """

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# DecisionReader — backs the decisions.* MCP tools (Hole #3, v1.1 Task 5)
# ---------------------------------------------------------------------------


@dataclass
class LedgerDecisionReader:
    """Raw-ledger reader for ``decisions.list`` / ``decisions.get`` /
    ``decisions.search``.

    Walks ``execute`` ledger entries whose payload carries
    ``tool == "emit_decision_recorded"``. Mirrors the
    ``apps/dashboard/lib/decision-chain.ts`` shape::

        SELECT entry_id, seq, ts, payload
          FROM ledger
         WHERE company_id = :cid
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_decision_recorded'
         ORDER BY ts DESC

    Decisions are append-only — there is no "supersede this decision"
    entry kind in v1.1 — so we do not de-dupe on ``decision_id`` the way
    ``LedgerProcessMapReader`` collapses on ``process_id``. Each emit is a
    distinct decision and each one keeps its own row.

    Rows returned are dicts shaped to the ``DecisionRecordedPayload``
    schema plus two enrichment fields that the response coercer
    (``tools_decisions._coerce_decision_row``) tolerates:

    - ``entry_hash``: hex-encoded entry hash for receipt-style display
    - ``domain_id``: when the payload carries one (some
      ``emit_decision_recorded`` calls thread ``domain_id`` alongside the
      ``channel_id`` for downstream domain filtering)
    """

    ledger: _LedgerFetcher

    async def list_decisions(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self._collect_decisions(company_id=company_id)
        if domain_id is not None:
            rows = [r for r in rows if r.get("domain_id") == domain_id]
        return rows[: max(0, int(limit))]

    async def get_decision(
        self,
        *,
        company_id: UUID,
        decision_id: str,
    ) -> dict[str, Any] | None:
        rows = await self._collect_decisions(company_id=company_id)
        for r in rows:
            if str(r.get("decision_id")) == str(decision_id):
                return r
        return None

    async def search_decisions(
        self,
        *,
        company_id: UUID,
        nl_question: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """v1: case-insensitive substring on ``decision_text``.

        v1.1+ swaps in pgvector cosine similarity over embedded decision
        summaries (the ``DecisionReader`` Protocol is the natural seam —
        callers don't change). The substring path is also a useful
        fallback when the embeddings index is offline or stale.
        """
        rows = await self._collect_decisions(company_id=company_id)
        q = (nl_question or "").lower()
        if not q:
            return []
        matched = [
            r for r in rows
            if q in str(r.get("decision_text") or "").lower()
        ]
        return matched[: max(0, int(limit))]

    async def _collect_decisions(
        self, *, company_id: UUID,
    ) -> list[dict[str, Any]]:
        """Newest-first list of decision-row dicts for the tenant.

        One pass over the company's ledger. Each ``execute`` entry with
        ``payload.tool == "emit_decision_recorded"`` becomes a row.

        Unlike process maps, decisions are not de-duped — each emit is
        a distinct artifact and the ``decisions.*`` tools are expected
        to surface them all (the dashboard's /decisions tab uses the
        same semantics).
        """
        entries = await self.ledger.fetch(company_id)
        # Ledger.fetch returns entries ordered oldest-first (seq ASC).
        # Reverse so the natural iteration order is newest-first, matching
        # the dashboard's ``ORDER BY ts DESC`` semantics.
        out: list[dict[str, Any]] = []
        for entry in reversed(entries):
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            if payload.get("tool") != "emit_decision_recorded":
                continue
            args = payload.get("args") or {}
            if not args.get("decision_id"):
                continue
            out.append(_shape_decision_row(entry=entry, args=args))
        return out


def _shape_decision_row(
    *, entry: dict[str, Any], args: dict[str, Any],
) -> dict[str, Any]:
    """Coerce a raw ledger execute entry into the MCP-response row shape.

    The response coercer in ``tools_decisions._coerce_decision_row``
    accepts both the bare ``DecisionRecordedPayload`` shape and a
    projection-shaped wrapper with ``entry_hash``. We emit the wrapper
    form so the dashboard's receipt surface and the MCP response carry
    the same provenance fields.
    """
    raw_hash = entry.get("hash")
    if isinstance(raw_hash, (bytes, bytearray)):
        entry_hash = raw_hash.hex()
    elif raw_hash is not None:
        entry_hash = str(raw_hash)
    else:
        entry_hash = None

    decision_at = args.get("decision_at")
    if hasattr(decision_at, "isoformat"):
        decision_at = decision_at.isoformat()
    elif decision_at is not None:
        decision_at = str(decision_at)

    persons_raw = args.get("decided_by_persons") or []
    evidence_raw = args.get("evidence_message_ids") or []

    conf = args.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = None

    return {
        "decision_id": str(args.get("decision_id", "")),
        "decision_text": args.get("decision_text", ""),
        "decision_at": decision_at,
        "channel_id": args.get("channel_id"),
        "decided_by_persons": [str(p) for p in persons_raw],
        "evidence_message_ids": [str(m) for m in evidence_raw],
        "confidence": conf,
        "domain_id": args.get("domain_id"),
        "entry_hash": entry_hash,
    }


# Backwards-compatible alias matching the brief's ``PostgresDecisionReader``
# vocabulary. The implementation is backend-agnostic — both the Postgres
# ``Ledger`` and ``InMemoryLedger`` satisfy ``_LedgerFetcher`` — so the
# ``Ledger``-prefixed name is the canonical class. The ``Postgres`` alias
# kept for the v1.1 plan's naming and for production wiring sites that
# want the storage-flavored hint.
PostgresDecisionReader = LedgerDecisionReader


# ---------------------------------------------------------------------------
# ProcessMapReader — backs the processes.* MCP tools (Hole #3, v1.1 Task 6)
# ---------------------------------------------------------------------------


@dataclass
class LedgerProcessMapReader:
    """Raw-ledger reader for ``processes.list`` / ``processes.get``.

    Walks ``execute`` ledger entries whose payload carries
    ``tool == "emit_process_map_proposed"``. Latest-status-per-process_id
    is enforced by traversing newest-first and de-duping on
    ``payload.args.process_id`` (matches ``getProcessMaps`` in
    ``apps/dashboard/lib/ledger-client.ts``, which uses
    ``SELECT DISTINCT ON (payload->'args'->>'process_id') ... ORDER BY ... seq DESC``).

    Rows returned are dicts shaped to the
    ``ProcessMapProposedPayload`` schema, plus two enrichment fields the
    response coercer in ``tools_processes._coerce_process_map_row``
    tolerates:

    - ``proposed_at``: ISO-8601 string of the execute entry's ``ts``
    - ``entry_hash``: hex-encoded entry hash for receipt-style display
    - ``domain_id``: when the payload carries one (some
      ``emit_process_map_proposed`` calls pass ``domain_id`` alongside
      the legacy ``domain`` string)
    """

    ledger: _LedgerFetcher

    async def list_process_maps(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self._collect_process_maps(company_id=company_id)
        if domain_id is not None:
            rows = [r for r in rows if r.get("domain_id") == domain_id]
        return rows[: max(0, int(limit))]

    async def get_process_map(
        self,
        *,
        company_id: UUID,
        process_map_id: str,
    ) -> dict[str, Any] | None:
        rows = await self._collect_process_maps(company_id=company_id)
        for r in rows:
            if str(r.get("process_id")) == str(process_map_id):
                return r
        return None

    async def _collect_process_maps(
        self, *, company_id: UUID,
    ) -> list[dict[str, Any]]:
        """Newest-first, deduped-by-process_id list of process-map dicts.

        One pass over the company's ledger. Each ``execute`` entry with
        ``payload.tool == "emit_process_map_proposed"`` becomes a row.
        Same-process_id collisions resolve to the most-recent entry.
        """
        entries = await self.ledger.fetch(company_id)
        # Ledger.fetch returns entries ordered oldest-first (seq ASC).
        # Reverse so the first occurrence we see for each process_id is
        # the most recent one, matching the dashboard's DISTINCT-ON
        # ORDER BY seq DESC semantics.
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for entry in reversed(entries):
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            if payload.get("tool") != "emit_process_map_proposed":
                continue
            args = payload.get("args") or {}
            pid_raw = args.get("process_id")
            if pid_raw is None:
                continue
            pid = str(pid_raw)
            if pid in seen:
                continue
            seen.add(pid)
            out.append(_shape_process_map_row(entry=entry, args=args))
        return out


def _shape_process_map_row(
    *, entry: dict[str, Any], args: dict[str, Any],
) -> dict[str, Any]:
    """Coerce a raw ledger execute entry into the MCP-response row shape.

    The response coercer in ``tools_processes._coerce_process_map_row``
    accepts both the bare ``ProcessMapProposedPayload`` shape and a
    projection-shaped wrapper with ``entry_hash`` / ``proposed_at``.
    We emit the wrapper form so the dashboard's receipt surface and
    the MCP response carry the same provenance fields.
    """
    ts = entry.get("ts")
    proposed_at = ts.isoformat() if hasattr(ts, "isoformat") else (
        str(ts) if ts is not None else None
    )
    raw_hash = entry.get("hash")
    if isinstance(raw_hash, (bytes, bytearray)):
        entry_hash = raw_hash.hex()
    elif raw_hash is not None:
        entry_hash = str(raw_hash)
    else:
        entry_hash = None

    steps = args.get("steps") or []
    if not isinstance(steps, list):
        steps = []

    return {
        "process_id": str(args.get("process_id", "")),
        "process_name": args.get("process_name", ""),
        "domain": args.get("domain"),
        "domain_id": args.get("domain_id"),
        "steps": list(steps),
        "confidence": args.get("confidence"),
        "proposed_at": proposed_at,
        "entry_hash": entry_hash,
    }


# ---------------------------------------------------------------------------
# DataProductReader — backs the data_products.* MCP tools
# (Hole #3, v1.2 Task 2 Item #3)
# ---------------------------------------------------------------------------


@dataclass
class LedgerDataProductReader:
    """Raw-ledger reader for ``data_products.list`` / ``data_products.get``.

    Walks ``execute`` ledger entries whose payload carries one of:

      * ``emit_data_product_proposed`` — creates a "proposed" row
      * ``emit_data_product_generated`` — updates status to "generated"
      * ``emit_data_product_archived`` — updates status to "archived"

    Data products are stateful (proposed → generated → archived) so this
    reader DOES de-dupe by ``data_product_id``: each id ends up with a
    single row that reflects the latest known state across the three
    lifecycle entry kinds. Matches the projection-builder semantics in
    ``packages/ledger/src/wormbase_ledger/projections/builder.py`` lines
    827-896 — both fold the same emit-tool sequence into the same final
    row shape.

    Rows returned are dicts shaped to the projection_data_products
    table (which the MCP response coercer
    ``tools_data_products._coerce_data_product_row`` already consumes),
    enriched with ``entry_hash`` from the most recent lifecycle entry
    for receipt-style display.
    """

    ledger: _LedgerFetcher

    async def list_data_products(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self._collect_data_products(company_id=company_id)
        if domain_id is not None:
            rows = [r for r in rows if str(r.get("domain_id") or "") == domain_id]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return rows[: max(0, int(limit))]

    async def get_data_product(
        self,
        *,
        company_id: UUID,
        data_product_id: str,
    ) -> dict[str, Any] | None:
        rows = await self._collect_data_products(company_id=company_id)
        for r in rows:
            if str(r.get("data_product_id")) == str(data_product_id):
                return r
        return None

    async def _collect_data_products(
        self, *, company_id: UUID,
    ) -> list[dict[str, Any]]:
        """Newest-first list of data-product rows, folded by data_product_id.

        One pass over the company's ledger. ``proposed`` creates the
        row; ``generated`` and ``archived`` mutate the row's status +
        latest-known-state fields. Iteration order is oldest-first
        (ledger.fetch returns seq-ASC) so later entries naturally
        overwrite earlier ones — the final row state reflects the most
        recent lifecycle entry. After the fold, sort by latest entry
        seq DESC so the response is newest-first.
        """
        entries = await self.ledger.fetch(company_id)
        state: dict[str, dict[str, Any]] = {}

        for entry in entries:
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            dpid_raw = args.get("data_product_id")
            if dpid_raw is None:
                continue
            dpid = str(dpid_raw)

            if tool == "emit_data_product_proposed":
                state[dpid] = _shape_data_product_proposed(
                    entry=entry, args=args,
                )
            elif tool == "emit_data_product_generated":
                if dpid in state:
                    _apply_data_product_generated(
                        row=state[dpid], entry=entry, args=args,
                    )
            elif tool == "emit_data_product_archived":
                if dpid in state:
                    _apply_data_product_archived(
                        row=state[dpid], entry=entry,
                    )

        # Sort newest-first by the latest-known seq for each row.
        out = list(state.values())
        out.sort(key=lambda r: int(r.get("_latest_seq", 0)), reverse=True)
        # Strip the helper field before returning so the row shape
        # matches the MCP coercer's expectations exactly.
        for r in out:
            r.pop("_latest_seq", None)
        return out


def _shape_data_product_proposed(
    *, entry: dict[str, Any], args: dict[str, Any],
) -> dict[str, Any]:
    """Build the initial row from an emit_data_product_proposed entry."""
    raw_hash = entry.get("hash")
    if isinstance(raw_hash, (bytes, bytearray)):
        entry_hash = raw_hash.hex()
    elif raw_hash is not None:
        entry_hash = str(raw_hash)
    else:
        entry_hash = None

    return {
        "data_product_id": str(args.get("data_product_id", "")),
        "name": args.get("name", ""),
        "kind": args.get("kind", ""),
        "status": "proposed",
        "requested_by_person_id": (
            str(args["requested_by_person_id"])
            if args.get("requested_by_person_id") else None
        ),
        "domain_id": (
            str(args["domain_id"]) if args.get("domain_id") else None
        ),
        "generated_at": None,
        "content_hash": None,
        "contents_uri": None,
        "entry_hash": entry_hash,
        "_latest_seq": int(entry.get("seq", 0) or 0),
    }


def _apply_data_product_generated(
    *, row: dict[str, Any], entry: dict[str, Any], args: dict[str, Any],
) -> None:
    """Mutate ``row`` in-place from an emit_data_product_generated entry."""
    ts = entry.get("ts")
    generated_at = ts.isoformat() if hasattr(ts, "isoformat") else (
        str(ts) if ts is not None else None
    )
    raw_hash = entry.get("hash")
    if isinstance(raw_hash, (bytes, bytearray)):
        entry_hash = raw_hash.hex()
    elif raw_hash is not None:
        entry_hash = str(raw_hash)
    else:
        entry_hash = row.get("entry_hash")
    row["status"] = "generated"
    row["generated_at"] = generated_at
    row["content_hash"] = args.get("content_hash")
    row["contents_uri"] = args.get("contents_uri")
    row["entry_hash"] = entry_hash
    seq = int(entry.get("seq", 0) or 0)
    if seq > int(row.get("_latest_seq", 0)):
        row["_latest_seq"] = seq


def _apply_data_product_archived(
    *, row: dict[str, Any], entry: dict[str, Any],
) -> None:
    """Mutate ``row`` in-place from an emit_data_product_archived entry."""
    raw_hash = entry.get("hash")
    if isinstance(raw_hash, (bytes, bytearray)):
        entry_hash = raw_hash.hex()
    elif raw_hash is not None:
        entry_hash = str(raw_hash)
    else:
        entry_hash = row.get("entry_hash")
    row["status"] = "archived"
    row["entry_hash"] = entry_hash
    seq = int(entry.get("seq", 0) or 0)
    if seq > int(row.get("_latest_seq", 0)):
        row["_latest_seq"] = seq


# ---------------------------------------------------------------------------
# AgentGrantReader — backs AgentAccessGate.grant_lookup + CostGate.grant_lookup
# (v1.3 follow-up #1)
# ---------------------------------------------------------------------------


@dataclass
class LedgerAgentGrantReader:
    """Raw-ledger reader producing the active :class:`AgentGrant` sequence
    expected by ``AgentAccessGate.grant_lookup`` and ``CostGate.grant_lookup``.

    Walks ``execute`` ledger entries whose payload carries
    ``tool == "emit_agent_grant"``. Per doctrine Addendum 3 a grant is a
    SINGLE entry kind with a ``status`` field — assign and revoke land on
    different ledger rows but share the canonical ``(agent_id, grant_kind,
    grant_target)`` triple. The projection-builder folds on that triple
    keeping the most-recent state; this reader does the same fold over
    raw entries so it stays usable in InMemoryLedger tests where no
    projection table is built.

    Fold semantics::

        newest-first scan
        for each execute entry with tool == "emit_agent_grant":
            triple = (agent_id, grant_kind, grant_target)
            if triple seen → skip (newer state wins)
            else → record current row
        filter rows where status == "active"
        scope to the supplied AgentID

    The returned ``AgentGrant`` instances carry the same shape the
    in-test grant_lookup builds (see
    ``test_agent_gateway_construction_v1_2.py``) so the gate chain
    consumes them uniformly. ``id`` is the raw entry-id string of the
    most-recent state-change (assign or revoke); the gate chain reads
    only ``grant_kind`` / ``grant_target`` / ``status`` /
    ``budget_remaining_usd`` so the value of ``id`` does not affect
    governance decisions.

    The reader filters to ``status='active'`` BEFORE returning so
    ``AgentAccessGate.grant_lookup`` can iterate the result with no
    additional filtering (the gate's contract is "any active grant in
    the accepted kinds wins"). Revoked grants are dropped at the
    reader boundary.
    """

    ledger: _LedgerFetcher

    async def __call__(self, agent_id: AgentID) -> Sequence[AgentGrant]:
        """Sequence-returning callable form for direct use as ``grant_lookup``.

        Construction sites can pass ``LedgerAgentGrantReader(ledger=...)``
        wherever a ``Callable[[AgentID], Awaitable[Sequence[AgentGrant]]]``
        is expected (e.g. ``GatewayDeps.grant_lookup``).
        """
        return await self.list_active_grants(
            company_id=None, agent_id=agent_id,
        )

    async def list_active_grants(
        self,
        *,
        company_id: UUID | None,
        agent_id: AgentID,
    ) -> list[AgentGrant]:
        """Return the active grants for ``agent_id`` (scoped to the reader's
        bound tenant when ``company_id`` is None).

        ``company_id`` is exposed for test convenience — production
        construction passes ``None`` and relies on the reader being
        constructed per-tenant via ``compose_production_agent_gateway_deps``.
        """
        # Reader is constructed per-tenant by the production composition
        # site, so a None ``company_id`` here resolves to the tenant the
        # ledger client is bound to. _LedgerFetcher.fetch requires a UUID;
        # if construction did not bind one the gates must fail closed —
        # the caller's None branch is guarded by the reader factory in
        # ``agent_gateway_construction.py``.
        if company_id is None:
            raise RuntimeError(
                "LedgerAgentGrantReader.list_active_grants requires a "
                "company_id; production callers wrap the reader in a "
                "tenant-bound closure inside "
                "compose_production_agent_gateway_deps.",
            )

        entries = await self.ledger.fetch(company_id)
        # Walk newest-first. First occurrence of each triple wins —
        # that's the most-recent state (assign or revoke).
        seen_triples: set[tuple[str, str, str]] = set()
        out: list[AgentGrant] = []
        target_agent = str(agent_id.value)

        for entry in reversed(entries):
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            if payload.get("tool") != "emit_agent_grant":
                continue
            args = payload.get("args") or {}
            row_agent = str(args.get("agent_id") or "")
            if row_agent != target_agent:
                continue
            grant_kind = args.get("grant_kind")
            grant_target = args.get("grant_target")
            if grant_kind is None or grant_target is None:
                continue
            triple = (row_agent, str(grant_kind), str(grant_target))
            if triple in seen_triples:
                continue
            seen_triples.add(triple)

            status = args.get("status")
            if status != "active":
                # Drop revoked rows at the reader boundary.
                continue
            shaped = _shape_agent_grant(entry=entry, args=args)
            if shaped is not None:
                out.append(shaped)

        return out


def _shape_agent_grant(
    *, entry: dict[str, Any], args: dict[str, Any],
) -> AgentGrant | None:
    """Coerce a raw ``emit_agent_grant`` execute entry into an
    :class:`AgentGrant` value object.

    Returns None when required fields are missing — production rows always
    carry them; defensive against partial/legacy entries.
    """
    grant_kind = args.get("grant_kind")
    grant_target = args.get("grant_target")
    agent_id = args.get("agent_id")
    granted_by = args.get("granted_by")
    if not all([grant_kind, grant_target, agent_id, granted_by]):
        return None
    if grant_kind not in (
        "domain.read", "resource.read", "resource.maintainer", "model.access",
    ):
        return None

    granted_at = entry.get("ts")
    if not isinstance(granted_at, datetime):
        # InMemoryLedger + Postgres both populate entry.ts; defensive
        # against partial test stubs.
        granted_at = datetime.now(tz=None)

    budget_raw = args.get("budget_remaining_usd")
    budget: Decimal | None = None
    if budget_raw is not None:
        try:
            budget = Decimal(str(budget_raw))
        except (InvalidOperation, ValueError):
            budget = None

    raw_id = entry.get("entry_id")
    grant_id = str(raw_id) if raw_id is not None else ""

    return AgentGrant(
        id=grant_id,
        agent_id=str(agent_id),
        grant_kind=grant_kind,  # type: ignore[arg-type]
        grant_target=str(grant_target),
        status="active",
        granted_by=str(granted_by),
        granted_at=granted_at,
        budget_remaining_usd=budget,
    )


# ---------------------------------------------------------------------------
# LedgerSubscriptionReader — backs SubscriptionDispatcher.active_subscriptions
# (v2.A Task 3)
# ---------------------------------------------------------------------------


@dataclass
class LedgerSubscriptionReader:
    """Raw-ledger scan for active agent subscriptions.

    Walks ``execute`` ledger entries whose payload carries
    ``tool == "emit_agent_subscription_created"`` and computes the active
    set by subtracting subscriptions for which a subsequent
    ``emit_agent_subscription_revoked`` entry exists.

    Returns serialized dicts with the following shape::

        {
            "subscription_id": str,
            "agent_id": str,
            "filter": dict,          # serialized AgentEventFilter
            "transport": "mcp_stream" | "webhook",
            "webhook_url": str | None,
            "webhook_secret_ref": str | None,
            "created_seq": int,      # seq of the create entry
        }

    The SubscriptionDispatcher consumes these dicts and runs each
    subscription's compiled filter against the triggering ledger entry.

    Per the v2.A plan §Risk Register: raw-ledger scan is acceptable at
    v2.A scale; promote to a ``projection_agent_subscriptions_active``
    projection table when the per-tenant active count exceeds ~100
    (doctrine reference: schema-evolution doctrine §Projection-promotion).
    The Protocol shape does not change at promotion time.
    """

    ledger: _LedgerFetcher

    async def active_subscriptions(
        self, company_id: UUID,
    ) -> list[dict[str, Any]]:
        """Return the active subscription set for ``company_id``.

        One pass over the tenant ledger. The active set = created MINUS
        revoked, computed by collecting both lifecycle entry kinds and
        filtering created-rows whose subscription_id appears in the
        revoked set.

        Iteration order: newest-create-first. Stable per ledger.fetch
        ordering (seq ASC), reversed.
        """
        entries = await self.ledger.fetch(company_id)
        revoked: set[str] = set()
        created_by_id: dict[str, dict[str, Any]] = {}

        for entry in entries:
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            tool = payload.get("tool")
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            sub_id_raw = args.get("subscription_id")
            if not sub_id_raw:
                continue
            sub_id = str(sub_id_raw)

            if tool == "emit_agent_subscription_created":
                created_by_id[sub_id] = {
                    "subscription_id": sub_id,
                    "agent_id": str(args.get("agent_id") or ""),
                    "filter": dict(args.get("filter") or {}),
                    "transport": str(args.get("transport") or ""),
                    "webhook_url": args.get("webhook_url"),
                    "webhook_secret_ref": args.get("webhook_secret_ref"),
                    "description": args.get("description"),
                    "created_seq": int(entry.get("seq", 0) or 0),
                }
            elif tool == "emit_agent_subscription_revoked":
                revoked.add(sub_id)

        # Active = created \ revoked. Newest-create-first.
        out: list[dict[str, Any]] = [
            row for sid, row in created_by_id.items() if sid not in revoked
        ]
        out.sort(key=lambda r: int(r.get("created_seq", 0)), reverse=True)
        return out


__all__ = [
    "LedgerAgentGrantReader",
    "LedgerDataProductReader",
    "LedgerDecisionReader",
    "LedgerProcessMapReader",
    "LedgerSubscriptionReader",
    "PostgresDecisionReader",
]
