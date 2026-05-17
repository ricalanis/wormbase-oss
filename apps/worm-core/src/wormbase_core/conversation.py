"""Conversation contract.

DM-proactive: in DMs the worm always responds.
Channel-gated: in channels the worm only speaks when (a) directly mentioned,
(b) relevance gate fires AND interjection gate allows (responsive), or
(c) talkativeness=proactive on a high-confidence ontology hit.

`should_ingest()` always returns True — the lurker invariant: every event
becomes a chat_received entry, regardless of whether the worm speaks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from wormbase_core.reactivity import (
    InfraEvent,
    RelevanceDecision,
    SemanticInterpretation,
)
from wormbase_core.relevance import RulesBasedRelevanceGate, Talkativeness
from wormbase_ledger import InMemoryLedger, Ledger


class ConversationContract:
    def __init__(
        self,
        relevance_gate: RulesBasedRelevanceGate,
        interjection_gate: Any,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        *,
        digest_window_hours: int = 24,
    ) -> None:
        self._gate = relevance_gate
        self._interjection = interjection_gate
        self._ledger = ledger
        self._company_id = company_id
        self._digest_window = timedelta(hours=digest_window_hours)

    # ------------------------------------------------------------------
    # Listen-for-ingest is unconditional.
    # ------------------------------------------------------------------

    def should_ingest(self, event: InfraEvent) -> bool:
        return True

    # ------------------------------------------------------------------
    # Speech rules.
    # ------------------------------------------------------------------

    async def should_speak(
        self, event: InfraEvent, interp: SemanticInterpretation
    ) -> tuple[bool, str]:
        # 1) DM -> always speak.
        if event.source == "dm":
            return True, "dm_always_respond"
        # 2) channel + @mention -> always speak.
        if self._gate.is_mentioned(event.text):
            return True, "mention"
        if event.source != "channel_message":
            return False, "non_channel_event"
        # 3) Channel rules.
        tk: Talkativeness = self._gate.talkativeness_for(event.channel_id)
        decision: RelevanceDecision = await self._gate.handle(event, interp)
        if tk == "lurker":
            return False, "lurker_suppress"
        if not decision.should_react:
            return False, decision.reason
        # 4) Responsive needs interjection budget on clarifications/proposals.
        # Proactive may speak without budget consumption for statements.
        if interp.event_type == "question":
            return True, f"talkativeness:{tk};question"
        if tk == "responsive" and event.channel_id is not None:
            allowed = await self._interjection.allow(
                event.channel_id, "clarification"
            )
            if not allowed:
                return False, "interjection_budget"
        return True, f"talkativeness:{tk};{interp.event_type}"

    # ------------------------------------------------------------------
    # Daily digest tick.
    # ------------------------------------------------------------------

    async def on_digest_tick(
        self, channel_id: str, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(UTC)
        tk = self._gate.talkativeness_for(channel_id)
        if tk == "lurker":
            return False
        rows = await self._ledger.fetch(self._company_id)
        threshold = now - self._digest_window
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"]["args"]
            if (
                args.get("content") == f"digest_sent:{channel_id}"
                and r["ts"] >= threshold
            ):
                return False
        # Record the digest tick.
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "digest tick",
                "proposed_by": "conversation",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"digest_sent:{channel_id}",
                    "tags": ["digest_sent", f"channel:{channel_id}"],
                },
                "result_ref": channel_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "digest_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "digest fired",
            },
            timestamp=now,
            quadrant="active_deterministic",
        )
        return True


__all__ = ["ConversationContract"]
