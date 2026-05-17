"""KpiGapTriggeredFlow — KPI tree gap → worm posts to channel.

Lifted from flows.py:510-602, plus ``_is_uuid`` (line 610) and
``_classify_table_name`` (line 656). Behavior unchanged.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from wormbase_chat_presence.chat_flows._shared import (
    _ChatSenderProto,
    _InterjectionGateProto,
)
from wormbase_core.source_builder import SourceBuilder, SourceProposal
from wormbase_core.types import CorrelationId
from wormbase_ledger import InMemoryLedger, Ledger


# Local copy of the PII filename hints regex (also used by drop_and_profile
# and the lake-discovery helper). Kept in this module to avoid coupling
# kpi_gap_triggered to the drop_and_profile module's internals.
_PII_FILENAME_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(ssn|sin|tax_id|customers?|users?|pii|email|phone|dob|"
    r"cardholder|kyc)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


def _classify_table_name(name: str) -> tuple[str, "Literal['public', 'internal', 'confidential', 'pii', 'regulated']"]:
    """Return (suggested_domain, suggested_classification) for a table.

    Heuristic: PII filename hints elevate classification; revenue/billing
    table names map to the finance domain.
    """
    domain = "general"
    if any(k in name.lower() for k in ("revenue", "invoice", "payment", "subscription", "billing")):
        domain = "finance"
    elif any(k in name.lower() for k in ("user", "customer", "person")):
        domain = "customer"
    elif any(k in name.lower() for k in ("event", "session", "log")):
        domain = "product"
    classification: Literal[
        "public", "internal", "confidential", "pii", "regulated"
    ] = "internal"
    if _PII_FILENAME_HINTS.search(name):
        classification = "pii"
    return domain, classification


class KpiGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kpi_id: str
    domain_id: UUID | None = None
    owner_channel_id: str | None = None


class KpiGapTriggeredFlow:
    """Worm scans the KPI tree, requests a source for any KPI without one."""

    def __init__(
        self,
        builder: SourceBuilder,
        ledger: Ledger | InMemoryLedger,
        interjection_gate: _InterjectionGateProto,
        chat_sender: _ChatSenderProto | None = None,
        *,
        cooldown_days: int = 7,
    ) -> None:
        self._builder = builder
        self._ledger = ledger
        self._gate = interjection_gate
        self._chat = chat_sender
        self._cooldown = timedelta(days=cooldown_days)

    async def propose_for_gap(
        self,
        company_id: UUID,
        gap: KpiGap,
        now: datetime | None = None,
    ) -> CorrelationId | None:
        now = now or datetime.now(UTC)
        # Skip if we already have an open proposal for this kpi.
        if await self._has_recent_proposal(company_id, gap.kpi_id, now):
            return None
        if gap.owner_channel_id is None or not await self._gate.allow(
            gap.owner_channel_id, "clarification"
        ):
            return None
        proposal = SourceProposal(
            proposed_uri=f"unknown://kpi/{gap.kpi_id}",
            proposed_type="file",
            proposed_domain="general",
            proposed_classification="internal",
            added_via_flow="kpi_gap_triggered",
            added_in_response_to=f"kpi:{gap.kpi_id}",
            company_id=company_id,
        )
        cid = await self._builder.propose(proposal)
        if self._chat is not None and gap.owner_channel_id:
            await self._chat.send(
                gap.owner_channel_id,
                f"I need access to a source for `{gap.kpi_id}` — can someone point me at it?",
                speech_act="proposal",
            )
        return cid

    async def _has_recent_proposal(
        self, company_id: UUID, kpi_id: str, now: datetime
    ) -> bool:
        rows = await self._ledger.fetch(company_id)
        threshold = now - self._cooldown
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"]["args"]
            if (
                args.get("added_in_response_to") == f"kpi:{kpi_id}"
                and r["ts"] >= threshold
            ):
                return True
        return False

    async def scan_for_gaps(self, company_id: UUID) -> list[str]:
        """Walk the kpi_nodes projection and return ids without a source."""
        rows = await self._ledger.fetch(company_id)
        gaps: list[str] = []
        seen: set[str] = set()
        for r in rows:
            if r["kind"] != "execute":
                continue
            payload = r["payload"]
            if payload.get("tool") != "emit_kpi_node":
                continue
            args = payload.get("args", {})
            kid = args.get("id")
            if kid is None or kid in seen:
                continue
            seen.add(kid)
            if args.get("source_resource_id") in (None, "", "null"):
                gaps.append(kid)
        return gaps


__all__ = ["KpiGap", "KpiGapTriggeredFlow"]
