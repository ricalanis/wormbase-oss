"""_LedgerBackedChatStore — concrete ChatStore impl over the ledger.

read_policy folds policy_applied entries with template
`policy:channel_talkativeness` into a ChatPolicy. Default (no fold yet)
is `responsive` + budget 3.

count_interjections_today mirrors InterjectionGate.allow's ledger fold
(packages/governance/src/wormbase_governance/gates.py:302-312) — counts
emit_memory_written entries with content `clarify_asked:{channel_id}` for
the current UTC day.

read_messages folds chat_received entries into ChatMessage rows. v1 reads
ledger entries directly; future swap can read projection_conversations
when the projection runner is current.

This impl uses ledger.fetch(company_id) — same path InMemoryLedger and
production Ledger both expose. SQL-backed reads (projection_channels) are
deferred to a future wave; the ledger fold is byte-correct in v1.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from wormbase_chat_presence.types import (
    ChatMessage,
    ChatPolicy,
)
from wormbase_ledger import InMemoryLedger, Ledger


_DEFAULT_POLICY = ChatPolicy(
    talkativeness="responsive",
    daily_interjection_budget=3,
)


@dataclass
class _LedgerBackedChatStore:
    """Ledger-backed ChatStore.

    Constructed once per process (typically in `wire_chat_for_install`),
    shared across the four Reactivities via DI through ReactivityContext.extras.
    """

    ledger: Ledger | InMemoryLedger

    async def read_messages(
        self,
        *,
        company_id: UUID,
        channel_id: str | None = None,
        since: datetime | None = None,
        n: int | None = None,
    ) -> AsyncIterator[ChatMessage]:
        """Yield ChatMessage rows from chat_received entries.

        v1 implementation: folds raw ledger entries. Optimisation
        (read projection_conversations) deferred — the fold is correct
        and the volume is bounded by the channel's history.
        """
        rows = await self.ledger.fetch(company_id)
        yielded = 0
        for r in rows:
            if r["kind"] != "execute":
                continue
            payload = r["payload"]
            tool = payload.get("tool")
            if tool not in (
                "emit_chat_received",
                "channel_adapter.emit_chat_received",
            ):
                continue
            args = payload.get("args") or {}
            entry_channel = str(args.get("channel_id") or "")
            if channel_id is not None and entry_channel != channel_id:
                continue
            ts = r["ts"]
            if since is not None and ts < since:
                continue
            yield ChatMessage(
                channel_id=entry_channel,
                message_id=str(args.get("message_id") or ""),
                sender_person=_safe_uuid(args.get("sender_person")),
                ts=ts,
                text=str(args.get("text") or ""),
                classification=args.get("classification") or "internal",
                domain_id=_safe_uuid(args.get("domain_id")),
                thread_root_message_id=args.get("thread_root_message_id"),
                platform=str(args.get("platform") or "slack"),
                ingested_at=ts,
            )
            yielded += 1
            if n is not None and yielded >= n:
                return

    async def read_policy(
        self,
        *,
        company_id: UUID,
        channel_id: str,
    ) -> ChatPolicy:
        """Fold policy_applied entries → current ChatPolicy for the channel.

        Default if no fold output: responsive + budget 3.
        Most-recent-write-wins on multiple policy_applied entries for the
        same channel (per emit-time ordering on the ledger).
        """
        rows = await self.ledger.fetch(company_id)
        policy_args: dict[str, Any] | None = None
        for r in rows:
            if r["kind"] != "execute":
                continue
            payload = r["payload"]
            if payload.get("tool") != "emit_policy_applied":
                continue
            args = payload.get("args") or {}
            if args.get("policy_name") != "policy:channel_talkativeness":
                continue
            applies_to = args.get("applies_to") or {}
            if applies_to.get("channel_id") != channel_id:
                continue
            policy_args = args  # last write wins

        if policy_args is None:
            return _DEFAULT_POLICY
        tk = policy_args.get("talkativeness", "responsive")
        if tk not in ("lurker", "responsive", "proactive"):
            tk = "responsive"
        budget = policy_args.get("daily_interjection_budget", 3)
        try:
            budget_int = int(budget)
        except (TypeError, ValueError):
            budget_int = 3
        return ChatPolicy(
            talkativeness=tk,  # type: ignore[arg-type]
            daily_interjection_budget=budget_int,
        )

    async def count_interjections_today(
        self,
        *,
        company_id: UUID,
        channel_id: str,
        now: datetime,
    ) -> int:
        """Count clarify_asked memory entries for the channel for today (UTC)."""
        window_start = now.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = await self.ledger.fetch(company_id)
        count = 0
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"].get("args") or {}
            if (
                args.get("content") == f"clarify_asked:{channel_id}"
                and r["ts"] >= window_start
            ):
                count += 1
        return count


def _safe_uuid(v: Any) -> UUID | None:
    if v is None:
        return None
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


__all__ = ["_LedgerBackedChatStore"]
