"""L6→L4 cross-axis adapter — LedgerConfirmedClassificationReader.

The L6→L4 cross-axis chain (5th cross-axis chain shipped 2026-06-10)
adds a producer-side Reader Protocol on L6's column_classification
subpackage:
:class:`wormbase_agent_gateway.column_classification.ConfirmedClassificationReader`.
The Protocol describes the read pattern L4's
:class:`GovernanceClassificationImpactStrategy` needs to elevate
schema-evolution impact severity based on L6's confirmed governance
classifications (regulated / pii / confidential / etc.).

This module ships the production impl that
``agent_gateway_construction.compose_schema_impact_reactivity_if_enabled``
threads into the strategy via the composite factory (when the env
sub-knob ``WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED`` is truthy). A
single shared instance is constructed once per boot wire so the
strategy and any future cross-axis consumers see the same read
surface.

Implementation approach: ledger-walk + projection-fold replay. Walks
the tenant-scoped ledger for ``column_classification_proposed`` /
``column_classification_confirmed`` / ``column_classification_rejected``
execute entries and reconstructs the projection_column_classifications
row state in-memory. Mirrors the rest of the lake-side readers
(LedgerCatalogReader, LedgerDbtManifestReader, LedgerDbtTestReader,
LedgerLineageEdgeReader, LedgerConfirmedSemanticTypeReader) which all
walk the ledger via ``ledger.fetch(company_id)`` rather than reading
Postgres projection tables directly.

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

When the ledger materialises the projection_column_classifications
table via SQL (Postgres), a future optimization can swap this impl for
a direct SQL reader behind the same Protocol surface — no caller
changes.

Filter contract per Protocol:

* state="confirmed" only — only L6-confirmed classifications elevate
  L4 impact severity; proposed-but-not-confirmed classifications are
  too noisy (a human operator hasn't yet vouched for the
  classification level).
* Source-column match: ``classification WHERE column = <src_column>
  AND table_id LIKE "<source_id>.%"``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(
    "wormbase_core.column_classification_governance_reader",
)

__all__ = [
    "LedgerConfirmedClassificationReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in
    :class:`wormbase_core.schema_impact_lineage_reader._LedgerFetcher`
    and
    :class:`wormbase_core.column_classification_semantic_reader._LedgerFetcher` —
    a fetch-by-company_id async call returning ledger row dicts.
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


def _entry_ts(entry: dict[str, Any]) -> datetime:
    """Best-effort extraction of an entry's timestamp.

    Order of attempts:
      1. ``entry["ts"]`` — canonical InMem ledger field, may be
         datetime or ISO string.
      2. ``entry["payload"]["ts"]`` — some payload shapes carry their
         own ts.
      3. Fallback to epoch (1970-01-01 UTC).
    """
    raw = entry.get("ts")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    payload = entry.get("payload")
    if isinstance(payload, dict):
        raw2 = payload.get("ts")
        if isinstance(raw2, datetime):
            return raw2
        if isinstance(raw2, str):
            try:
                return datetime.fromisoformat(raw2)
            except ValueError:
                pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _extract_source_id(table_id: str) -> str:
    """Extract ``source_id`` from canonical ``"<source_id>.<schema>.<table>"``.

    Returns the empty string for malformed table_ids; callers treat
    the empty-source case as a no-match.
    """
    if not table_id:
        return ""
    parts = table_id.split(".", 1)
    if not parts or not parts[0]:
        return ""
    return parts[0]


@dataclass
class LedgerConfirmedClassificationReader:
    """Reads L6's confirmed column classifications via ledger walk + fold replay.

    Implements the
    :class:`wormbase_agent_gateway.column_classification.ConfirmedClassificationReader`
    Protocol — the **5th cross-axis read** in the lake stack and the
    **first producer-side L6-owned Reader Protocol** (L6's
    :class:`ConfirmedSemanticTypeReader` is consumer-side on the L5
    domain). L4's
    :class:`wormbase_agent_gateway.schema_impact.strategies.GovernanceClassificationImpactStrategy`
    injects this reader to elevate impact severity based on operator-
    confirmed governance classifications.

    Fold semantics applied at read time:

    * ``column_classification_proposed`` → seed a classification record
      (state="proposed", tracking proposal payload + ts).
    * ``column_classification_confirmed`` → flip state="confirmed" on
      the matching classification_id; capture
      ``confirmed_by_person_id`` + ``confirmed_at`` from the
      confirmation entry.
    * ``column_classification_rejected`` → flip state="rejected" on the
      matching classification_id (last-write-wins on conflicting state
      changes per the L6 projection-fold semantics; re-confirmation
      after rejection emits a new entry, so walking ledger-order gives
      the same final state).

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared and each strategy
    invocation passes its own company_id.

    Replay-stability: ledger fetch is oldest-first, so iterating
    entries in order gives the same final state across runs. Two
    callers invoking with identical (company_id, source_id,
    src_column) get byte-identical
    :class:`ConfirmedClassificationRecord` tuples — sorted by
    ``classification_id`` for deterministic ordering.
    """

    ledger: _LedgerFetcher

    async def list_confirmed_classifications_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id: UUID,
    ) -> list[Any]:  # list[ConfirmedClassificationRecord]; Any defers import
        """Return L6-confirmed classifications for ``(source_id, src_column)``.

        Filter contract:

        * state="confirmed" — only L6-confirmed classifications feed
          L4 governance elevation.
        * source_id match: ``table_id`` starts with
          ``"<source_id>."``.
        * src_column matches exactly (column-grain — L6 classifications
          are per-column).

        Returns ``[]`` when no confirmed classifications match —
        callers treat this as a no-op (the strategy proposes no
        governance-elevated impacts).

        Performance note: this walks the full tenant ledger per call.
        For typical lake sizes (10s-100s of confirmed classifications)
        the cost is negligible. A future optimization can index by
        (company_id, source_id, column) once the
        projection_column_classifications table is queryable.
        """
        # Lazy import to avoid importing the agent-gateway package at
        # module import time (mirrors the
        # column_classification_semantic_reader pattern).
        from wormbase_agent_gateway.column_classification import (
            ConfirmedClassificationRecord,
        )

        if not source_id or not src_column:
            return []

        entries = await self.ledger.fetch(company_id)

        # First pass: gather proposal payloads keyed by classification_id.
        # Multiple proposals for the same classification_id collapse to
        # the latest row (last-write-wins).
        cls_payloads: dict[str, dict[str, Any]] = {}
        # Second pass: track final state via ledger order.
        cls_states: dict[str, str] = {}
        # Capture confirmation metadata when state flips to confirmed
        # (needed for the Record fields confirmed_at +
        # confirmed_by_person_id).
        cls_confirmed_meta: dict[str, dict[str, Any]] = {}

        source_prefix = f"{source_id}."

        for entry in entries:
            if _is_emit_tool(entry, "emit_column_classification_proposed"):
                args = _execute_args(entry)
                classification_id = str(args.get("classification_id") or "")
                if not classification_id:
                    continue
                entry_table = str(args.get("table_id") or "")
                if not entry_table.startswith(source_prefix):
                    continue
                entry_column = str(args.get("column") or "")
                if entry_column != src_column:
                    continue
                cls_payloads[classification_id] = args
                cls_states.setdefault(classification_id, "proposed")
            elif _is_emit_tool(entry, "emit_column_classification_confirmed"):
                args = _execute_args(entry)
                classification_id = str(args.get("classification_id") or "")
                if not classification_id or classification_id not in cls_payloads:
                    continue
                cls_states[classification_id] = "confirmed"
                cls_confirmed_meta[classification_id] = {
                    "confirmed_at": _entry_ts(entry),
                    "confirmed_by_person_id": str(
                        args.get("confirmed_by_person_id") or "",
                    ),
                }
            elif _is_emit_tool(entry, "emit_column_classification_rejected"):
                args = _execute_args(entry)
                classification_id = str(args.get("classification_id") or "")
                if not classification_id or classification_id not in cls_payloads:
                    continue
                cls_states[classification_id] = "rejected"
                # Drop confirmation meta if a confirmed flipped to rejected.
                cls_confirmed_meta.pop(classification_id, None)

        # Materialise into ConfirmedClassificationRecord tuples for every
        # classification whose final state is "confirmed". Deterministic
        # ordering by classification_id for replay stability.
        records: list[Any] = []
        for classification_id in sorted(cls_payloads):
            if cls_states.get(classification_id) != "confirmed":
                continue
            args = cls_payloads[classification_id]
            meta = cls_confirmed_meta.get(classification_id) or {}
            level = args.get("classification_level")
            if not isinstance(level, str) or not level:
                continue
            table_id = str(args.get("table_id") or "")
            extracted_source = _extract_source_id(table_id)
            if not extracted_source:
                logger.warning(
                    "skipping classification %s: malformed table_id %r",
                    classification_id, table_id,
                )
                continue
            confirmed_at = meta.get("confirmed_at")
            if not isinstance(confirmed_at, datetime):
                confirmed_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
            confirmed_by = meta.get("confirmed_by_person_id") or ""
            records.append(
                ConfirmedClassificationRecord(
                    classification_id=classification_id,
                    source_id=extracted_source,
                    table_id=table_id,
                    column=src_column,
                    classification_level=level,  # type: ignore[arg-type]
                    confirmed_at=confirmed_at,
                    confirmed_by_person_id=confirmed_by,
                ),
            )
        return records
