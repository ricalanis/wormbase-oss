"""Masked-column refusal gate (P7 — Snowflake governance-passthrough).

When a query references a column whose Snowflake `COLUMN.TAG` was
mapped (at profile time) to a high-sensitivity classification
(``pii``, ``regulated``, or ``confidential``), this gate refuses and
writes a ``gate_fired`` ledger entry that carries:

* the gate name (``masked_column_refusal``)
* the policy name (``Masked Column Refusal``)
* the offending column(s)
* the Snowflake tag(s) that drove the refusal
* the ``source_id`` / ``resource_id`` so the dashboard can jump from
  ``/trace`` to ``/sources/<id>`` and surface the column-tag chain

This closes the warehouse-native governance interop loop: Snowflake
column tags propagate end-to-end into the WormBase ledger and any
downstream query that touches a masked column refuses with the
column-tag attributable as the refusal reason.

The gate is intentionally pure-policy:

  * Input: a ``MaskedColumnQuery`` describing the columns the query
    would read and the column-tag map produced at profile time.
  * Output: ``MaskedColumnRefusalResult`` with ``allow``, ``reason``,
    ``offending_columns``, ``tag_chain``.
  * Side-effect: on refusal, one append-only ``gate_fired`` ledger
    entry, hash-chained, replayable.

This module lives under ``wormbase_governance.policies`` so it is
discoverable next to ``PolicyLoader`` / ``CompanyWarmup`` — the
governance bootstrap that registers it as a policy template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger

# Policy / gate identifiers — surfaced verbatim in the ledger payload
# so /trace can render "policy: Masked Column Refusal" and the audit
# log can grep on a stable string.
GATE_NAME = "masked_column_refusal"
POLICY_NAME = "Masked Column Refusal"

# Classifications that, when attached to a referenced column via
# Snowflake column tag passthrough, cause this gate to refuse the
# query. ``confidential`` is included because a confidential column
# in a query response is the canonical "masked at the warehouse,
# unmask only on a documented exception" case Snowflake customers
# already model with COLUMN.TAG today.
REFUSAL_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"pii", "regulated", "confidential"}
)


@dataclass(frozen=True)
class MaskedColumnQuery:
    """Pure description of the query the gate is asked to evaluate.

    ``referenced_columns`` is the set of column names the query
    would read — caller is responsible for extracting them (e.g. a
    SELECT-list parser, a planner pass, or, in the demo path, a
    structured query payload).

    ``column_tags`` is the column-tag map produced at profile time
    by :class:`SnowflakeSurfaceDriver` — keyed by column name, value is
    the WormBase classification the Snowflake tag mapped to.

    ``source_id`` and ``resource_id`` thread the trace-back so the
    dashboard can jump from ``/trace`` to ``/sources/<id>`` to show
    which column-tag drove the refusal.
    """

    query_text: str
    referenced_columns: list[str]
    column_tags: dict[str, str]
    source_id: UUID | None = None
    resource_id: str | None = None
    requester: str | None = None  # actor identifier for the audit trail


@dataclass(frozen=True)
class MaskedColumnRefusalResult:
    """Decision returned by :meth:`MaskedColumnRefusalGate.check`."""

    allow: bool
    reason: str
    offending_columns: list[str] = field(default_factory=list)
    tag_chain: list[dict[str, str]] = field(default_factory=list)
    policy_name: str = POLICY_NAME
    gate: str = GATE_NAME


class MaskedColumnRefusalGate:
    """Refuses queries that touch a masked / classified Snowflake column.

    Construction:

        gate = MaskedColumnRefusalGate(ledger, company_id)
        decision = await gate.check(query)
        if not decision.allow:
            ...  # surface refusal + jump-to-source link

    The gate writes a single ``gate_fired`` ledger entry per refusal,
    matching the four-step write primitive used by every other gate
    in this package (see :mod:`wormbase_governance.gates`).
    """

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        refusal_classifications: frozenset[str] = REFUSAL_CLASSIFICATIONS,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._refusal_classifications = refusal_classifications

    async def check(
        self, query: MaskedColumnQuery
    ) -> MaskedColumnRefusalResult:
        offending: list[str] = []
        tag_chain: list[dict[str, str]] = []
        for col in query.referenced_columns:
            classification = query.column_tags.get(col)
            if not classification:
                continue
            if classification in self._refusal_classifications:
                offending.append(col)
                tag_chain.append(
                    {"column": col, "classification": classification}
                )
        if not offending:
            return MaskedColumnRefusalResult(
                allow=True,
                reason="no_masked_columns_referenced",
            )
        await self._record_refusal(query, offending, tag_chain)
        first_col = offending[0]
        first_class = query.column_tags[first_col]
        reason = (
            f"refused: column {first_col!r} carries classification "
            f"{first_class!r}"
        )
        return MaskedColumnRefusalResult(
            allow=False,
            reason=reason,
            offending_columns=offending,
            tag_chain=tag_chain,
        )

    async def _record_refusal(
        self,
        query: MaskedColumnQuery,
        offending: list[str],
        tag_chain: list[dict[str, str]],
    ) -> None:
        # The subject_ref is the most-specific identifier we have so
        # /trace can resolve back to /sources/<id>.
        subject_ref = (
            query.resource_id
            or (str(query.source_id) if query.source_id else "unknown")
        )
        # Human-readable reason in payload (matches GateFiredPayload schema)
        # plus structured detail under additional keys for the dashboard.
        reason = (
            f"masked_column_refusal: {len(offending)} column(s) "
            f"refused via Snowflake COLUMN.TAG passthrough"
        )
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "gate_fired",
                "ref_id": str(uuid4()),
                "reason": "masked_column_refused",
                "proposed_by": GATE_NAME,
            },
            execute_fn=lambda: {
                "tool": "emit_gate_fired",
                "args": {
                    "gate": GATE_NAME,
                    "outcome": "blocked",
                    "subject_ref": subject_ref,
                    "reason": reason,
                    "policy_name": POLICY_NAME,
                    "offending_columns": offending,
                    "tag_chain": tag_chain,
                    "source_id": (
                        str(query.source_id) if query.source_id else None
                    ),
                    "resource_id": query.resource_id,
                    "query_text": query.query_text,
                    "requester": query.requester,
                },
                "result_ref": GATE_NAME,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "masked_column_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    "masked-column refusal recorded with column-tag chain"
                ),
            },
            timestamp=datetime.now(UTC),
            quadrant="active_deterministic",
        )


def masked_column_refusal_gate(
    *args: Any, **kwargs: Any
) -> MaskedColumnRefusalGate:
    """Factory — referenced by `policy_templates.yaml::gate_impl`."""
    return MaskedColumnRefusalGate(*args, **kwargs)


__all__ = [
    "GATE_NAME",
    "POLICY_NAME",
    "REFUSAL_CLASSIFICATIONS",
    "MaskedColumnQuery",
    "MaskedColumnRefusalGate",
    "MaskedColumnRefusalResult",
    "masked_column_refusal_gate",
]
