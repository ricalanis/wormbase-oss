"""L1 Sub-wave C — concrete Reader impls for source-candidate triage.

Sub-wave B introduced three lightweight Reader Protocols on the
``source_candidates`` subpackage in ``wormbase-agent-gateway``:

  * :class:`ConnectedSourceReader` — consumed by
    :class:`ComplementaritySourceStrategy` for portfolio-gap heuristics.
  * :class:`KpiNodeReader` — consumed by
    :class:`KpiGapAcquisitionStrategy` for KPI-without-source detection.
  * :class:`SilverConversationReader` — consumed by
    :class:`ChannelMentionAcquisitionStrategy` for regex-based
    source-mention scanning.

These Protocols are **NOT** cross-axis chains in the L4→L3 / L6→L5 /
L8→L5 sense (cross-axis chain count stays at 3). They read **first-class
platform projections** (``projection_sources``, ``projection_kpi_nodes``,
``projection_conversations``) — the producers are substrate, not
Compounding loops. See
``packages/wormbase-agent-gateway/.../source_candidates/protocol.py`` for
the doctrine clarification.

This module ships the production impls that
``agent_gateway_construction.build_source_candidate_service_from_env``
threads into the three strategies via the composite factory. A single
shared instance per reader is constructed once per boot wire so the
strategies and any future cross-axis consumers see the same read surface.

Implementation approach: ledger-walk + projection-fold replay. Each
reader walks the tenant-scoped ledger via ``ledger.fetch(company_id)``
and reconstructs the projection-row state in-memory. This mirrors the
rest of the lake-side readers (LedgerCatalogReader,
LedgerLineageEdgeReader, LedgerConfirmedSemanticTypeReader,
LedgerDomainDefaultReader) which all walk the ledger rather than
reading Postgres projection tables directly.

The rationale for ledger-walk over SQL projection-read:

* Works against InMemoryLedger (tests) and DB-backed Ledger (prod)
  with the same code path. Avoids a SQL-only impl that breaks the
  in-memory-ledger test pattern used across worm-core.
* Replay-stable by construction — the ledger IS the source of truth;
  the projection is a materialized view. Walking the ledger yields the
  same result as querying the projection (modulo replay drift, which
  the projection runner protects against).
* Tenant scope rides on ``company_id`` per call — same surface as the
  rest of the lake-side readers.

When the ledger materialises the platform projection tables via SQL
(Postgres), a future optimization can swap any of these impls for a
direct SQL reader behind the same Protocol surface — no caller
changes.

Per Sub-wave B handoff concern #2: the silver-conversations projection
is named ``projection_conversations`` (one row per (company_id,
channel_id, message_id)) — the underlying ledger entry kind is
``chat_received`` (tool ``emit_chat_received``). The reader folds those
entries directly to avoid coupling to the projection table name.

Per Sub-wave B handoff concern #3: classification skip-set policy
(``pii`` / ``regulated`` rows) lives in the strategy, NOT in the
reader. The reader returns the field; the strategy decides the policy.

Per Sub-wave B handoff concern #8: the same ``candidate_id`` across
repeat ticks is absorbed by the v027 projection fold (CHECK on
``(company_id, candidate_id)`` composite PK) — the readers are
idempotent because they read deterministically.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.source_candidate_readers")

__all__ = [
    "LedgerConnectedSourceReader",
    "LedgerKpiNodeReader",
    "LedgerSilverConversationReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in
    :class:`wormbase_core.column_classification_semantic_reader._LedgerFetcher`
    — a fetch-by-company_id async call returning ledger row dicts.
    """

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


def _execute_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``args`` dict from an execute entry's payload."""
    if entry.get("kind") != "execute":
        return {}
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return {}
    return args


def _is_emit_tool(entry: dict[str, Any], tool: str) -> bool:
    """True iff this is an execute entry whose payload.tool matches ``tool``."""
    if entry.get("kind") != "execute":
        return False
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return False
    return payload.get("tool") == tool


# ---------------------------------------------------------------------------
# 1. LedgerConnectedSourceReader — folds the source-pipeline lifecycle.
# ---------------------------------------------------------------------------


@dataclass
class LedgerConnectedSourceReader:
    """Reads connected sources via ledger walk + fold replay.

    Implements the
    :class:`wormbase_agent_gateway.source_candidates.ConnectedSourceReader`
    Protocol — consumed by L1's
    :class:`ComplementaritySourceStrategy` for portfolio-gap heuristics.

    Fold semantics applied at read time:

    * ``source_proposed`` → seed a source record keyed by ``source_id``;
      track ``kind`` (from ``source_kind``), ``domain`` (from
      ``suggested_domain``), ``classification`` (from
      ``suggested_classification``).
    * ``source_confirmed`` → flip state to ``confirmed``; update
      ``domain_id`` and ``classification`` to admin-confirmed values.
    * ``source_connected`` → flip state to ``connected``.
    * ``source_profiled`` → flip state to ``profiled``.

    Filter contract per Sub-wave B Protocol: returns sources whose final
    state is ``connected`` or ``profiled`` (i.e. actually wired up;
    proposed-but-not-yet-connected sources are too noisy and would
    distort portfolio heuristics).

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared and each strategy
    invocation passes its own company_id.

    Replay-stability: ledger fetch is oldest-first, so iterating
    entries in order gives the same final state across runs. Two
    callers invoking with identical ``company_id`` get byte-identical
    :class:`ConnectedSourceRecord` tuples — sorted by ``source_id`` for
    deterministic ordering.
    """

    ledger: _LedgerFetcher

    async def list_connected_sources(
        self, *, company_id: UUID,
    ) -> list[Any]:  # list[ConnectedSourceRecord]; Any defers import
        """Return all connected/profiled sources for ``company_id``."""
        from wormbase_agent_gateway.source_candidates import (
            ConnectedSourceRecord,
        )

        entries = await self.ledger.fetch(company_id)

        # Track per-source-id state + the latest classification/domain
        # we've observed (later entries win, mirroring the projection
        # fold semantics).
        source_data: dict[str, dict[str, Any]] = {}
        source_states: dict[str, str] = {}

        for entry in entries:
            if _is_emit_tool(entry, "emit_source_proposed"):
                args = _execute_args(entry)
                source_id = str(args.get("source_id") or "")
                if not source_id:
                    continue
                source_data[source_id] = {
                    "kind": str(args.get("source_kind") or ""),
                    "domain_id": (
                        str(args.get("suggested_domain"))
                        if args.get("suggested_domain") is not None
                        else None
                    ),
                    "classification": (
                        str(args.get("suggested_classification"))
                        if args.get("suggested_classification") is not None
                        else None
                    ),
                }
                source_states[source_id] = "proposed"
            elif _is_emit_tool(entry, "emit_source_confirmed"):
                args = _execute_args(entry)
                source_id = str(args.get("source_id") or "")
                if not source_id or source_id not in source_data:
                    continue
                # Admin-confirmed values supersede the proposal hints.
                if args.get("domain_id") is not None:
                    source_data[source_id]["domain_id"] = str(
                        args.get("domain_id"),
                    )
                if args.get("classification") is not None:
                    source_data[source_id]["classification"] = str(
                        args.get("classification"),
                    )
                source_states[source_id] = "confirmed"
            elif _is_emit_tool(entry, "emit_source_connected"):
                args = _execute_args(entry)
                source_id = str(args.get("source_id") or "")
                if not source_id or source_id not in source_data:
                    continue
                source_states[source_id] = "connected"
            elif _is_emit_tool(entry, "emit_source_profiled"):
                args = _execute_args(entry)
                source_id = str(args.get("source_id") or "")
                if not source_id or source_id not in source_data:
                    continue
                source_states[source_id] = "profiled"

        # Materialise into ConnectedSourceRecord tuples for every source
        # whose final state is connected or profiled. Deterministic
        # ordering by source_id for replay stability.
        records: list[Any] = []
        for source_id in sorted(source_data):
            state = source_states.get(source_id)
            if state not in {"connected", "profiled"}:
                continue
            data = source_data[source_id]
            kind = data.get("kind") or ""
            if not kind:
                # A source with no kind shouldn't reach the strategy.
                continue
            records.append(
                ConnectedSourceRecord(
                    source_id=source_id,
                    kind=kind,
                    domain_id=data.get("domain_id"),
                    classification=data.get("classification"),
                ),
            )
        return records


# ---------------------------------------------------------------------------
# 2. LedgerKpiNodeReader — folds kpi_proposed entries + filters unbacked.
# ---------------------------------------------------------------------------


@dataclass
class LedgerKpiNodeReader:
    """Reads KPI nodes without a backing source via ledger walk + fold replay.

    Implements the
    :class:`wormbase_agent_gateway.source_candidates.KpiNodeReader`
    Protocol — consumed by L1's
    :class:`KpiGapAcquisitionStrategy` for KPI-gap detection.

    Fold semantics applied at read time:

    * ``kpi_proposed`` (tool ``emit_kpi_proposed``) → seed a KPI node
      record keyed by ``kpi_id``; track ``label`` (the human-readable
      KPI name) and ``source_ids`` (the list of source UUIDs backing
      the KPI; empty list ⇒ unbacked).

    Filter contract per Sub-wave B Protocol: returns ONLY nodes where
    ``source_ids`` is empty — i.e. the strategy only sees the gap
    candidates, not the full KPI tree. This is the "unbacked KPI"
    notion spec §4.3 KpiGap strategy targets.

    For Wave 1 the heuristic for "without source" is simply
    ``source_ids == []`` on the most recent ``kpi_proposed`` entry for
    each ``kpi_id``. A future wave can integrate confirmation /
    promotion entries if/when those land.

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared.

    Replay-stability: ledger fetch is oldest-first; the same ledger
    state yields the same result.
    """

    ledger: _LedgerFetcher

    async def list_kpi_nodes_without_source(
        self, *, company_id: UUID,
    ) -> list[Any]:  # list[KpiNodeRecord]; Any defers import
        """Return KPI nodes with no backing source (i.e. unbacked KPIs)."""
        from wormbase_agent_gateway.source_candidates import KpiNodeRecord

        entries = await self.ledger.fetch(company_id)

        # Track latest payload per kpi_id (later proposals supersede
        # earlier ones in case of re-proposal with new source bindings).
        kpi_payloads: dict[str, dict[str, Any]] = {}

        for entry in entries:
            if not _is_emit_tool(entry, "emit_kpi_proposed"):
                continue
            args = _execute_args(entry)
            kpi_id = str(args.get("kpi_id") or "")
            if not kpi_id:
                continue
            kpi_payloads[kpi_id] = args

        # Materialise into KpiNodeRecord tuples for every KPI with
        # source_ids == [] (the "unbacked" filter). Deterministic
        # ordering by kpi_id for replay stability.
        records: list[Any] = []
        for kpi_id in sorted(kpi_payloads):
            args = kpi_payloads[kpi_id]
            source_ids = args.get("source_ids") or []
            if not isinstance(source_ids, list):
                continue
            if len(source_ids) > 0:
                # KPI is backed by ≥1 source — not a gap candidate.
                continue
            label = args.get("label")
            if not isinstance(label, str) or not label:
                continue
            # KPI tree's KpiProposedPayload doesn't carry a domain_id
            # field directly; owner_position is the closest signal, but
            # it's a position string, not a domain UUID. Wave 1 leaves
            # domain_id_hint=None for KPI-gap candidates without a
            # confirmed domain link; future waves can fold
            # owner_position → domain via the position projection.
            records.append(
                KpiNodeRecord(
                    kpi_node_id=kpi_id,
                    name=label,
                    domain_id=None,
                ),
            )
        return records


# ---------------------------------------------------------------------------
# 3. LedgerSilverConversationReader — folds chat_received entries
#    capped at the most-recent N (default 1000) within since_seconds.
# ---------------------------------------------------------------------------


_MAX_CONVERSATIONS_CAP = 1000


@dataclass
class LedgerSilverConversationReader:
    """Reads recent silver-conversation rows via ledger walk.

    Implements the
    :class:`wormbase_agent_gateway.source_candidates.SilverConversationReader`
    Protocol — consumed by L1's
    :class:`ChannelMentionAcquisitionStrategy` for regex-based
    source-mention scanning.

    The canonical silver-conversations table in the WormBase ledger
    schema is ``projection_conversations`` (one row per (company_id,
    channel_id, message_id)), folded from ``chat_received`` PEVR
    cycles. To avoid coupling to the projection-table name (which
    diverges from the spec's forward-looking
    ``projection_silver_conversations`` per Sub-wave B handoff
    concern #1), this reader folds ``chat_received`` entries directly.

    Filter contract per Sub-wave B Protocol:

    * Window: returns rows whose entry timestamp is within
      ``since_seconds`` of "now" (default 86400 = 24h).
    * Cap: at most :data:`_MAX_CONVERSATIONS_CAP` (1000) rows, capped
      to the MOST RECENT entries — the strategy regex-scans the
      returned list, and an unbounded scan would dominate the
      Compounding tick's wall-clock.
    * Classification: returned verbatim — the strategy decides whether
      to skip ``pii`` / ``regulated`` rows (per Sub-wave B handoff
      concern #3, classification policy lives in the strategy, NOT in
      the reader).

    Tenant scope rides on ``company_id`` per call.

    Replay-stability: ledger fetch is oldest-first; sorting by entry
    timestamp + capping at the most recent N yields the same result
    across runs for a fixed ledger snapshot. Note: when this reader is
    invoked at different wall-clocks the ``since_seconds`` window shifts,
    so the returned set may evolve over time — that's the intended
    behaviour for a "recent conversations" view.
    """

    ledger: _LedgerFetcher

    async def list_recent_conversations(
        self,
        *,
        company_id: UUID,
        since_seconds: int = 86400,
    ) -> list[Any]:  # list[SilverConversationRecord]; Any defers import
        """Return the most-recent silver-conversation rows for ``company_id``.

        Capped at 1000 rows. ``since_seconds`` defaults to 24h.
        """
        from wormbase_agent_gateway.source_candidates import (
            SilverConversationRecord,
        )

        entries = await self.ledger.fetch(company_id)

        # Resolve "now" once per call — use wall-clock for the window
        # since chat_received entries carry tz-aware timestamps. We use
        # the ledger entry's ``ts`` field (the ledger-ingest timestamp)
        # for the window comparison.
        now_unix = time.time()
        window_floor_unix = now_unix - max(0, since_seconds)

        # Collect candidate rows.
        rows: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            if not _is_emit_tool(entry, "emit_chat_received"):
                continue
            ts_unix = _entry_ts_to_unix(entry.get("ts"))
            if ts_unix is None:
                continue
            if ts_unix < window_floor_unix:
                continue
            args = _execute_args(entry)
            if not args:
                continue
            rows.append((ts_unix, args))

        # Sort newest-first; cap at MAX_CONVERSATIONS_CAP.
        rows.sort(key=lambda pair: pair[0], reverse=True)
        rows = rows[:_MAX_CONVERSATIONS_CAP]

        records: list[Any] = []
        for _ts, args in rows:
            message_id = args.get("message_id")
            channel_id = args.get("channel_id")
            text = args.get("text")
            if not isinstance(message_id, str) or not message_id:
                continue
            if not isinstance(channel_id, str) or not channel_id:
                continue
            if not isinstance(text, str):
                continue
            classification = args.get("classification")
            if classification is not None and not isinstance(
                classification, str,
            ):
                classification = str(classification)
            # ChatReceivedPayload has no domain_id field; conversation
            # rows aren't directly domain-tagged in the ledger today.
            # The strategy threads None when no domain signal is
            # available (spec §4.3 ChannelMention behaviour).
            records.append(
                SilverConversationRecord(
                    message_id=message_id,
                    channel_id=channel_id,
                    text=text,
                    domain_id=None,
                    classification=classification,
                ),
            )
        return records


def _entry_ts_to_unix(value: Any) -> float | None:
    """Coerce a ledger entry ``ts`` value to a unix timestamp.

    Accepts ISO-8601 strings (``"2026-05-16T12:00:00+00:00"``) and
    :class:`datetime` instances. Returns ``None`` when the value is
    missing or unparseable — the reader silently skips such rows
    rather than crashing on schema drift.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            return value.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        try:
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
    return None
