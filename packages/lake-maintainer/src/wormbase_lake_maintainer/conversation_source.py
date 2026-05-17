"""ConversationSource — Maintainer-facing wrapper over projection_conversations.

Per spike §8 C4: conversation gets its own introspection methods, NOT
discover/profile/sample. The Connector Protocol's tabular shape is
degenerate for chat — we expose channel enumeration, recent windowing,
and per-classification summaries instead. The Reactivities in Block F
read from these methods to detect drift / staleness / lineage.

Per spike §8 C5 corollary: ingest happens upstream via
``channel_adapter.emit_chat_received`` writes; this Source is read-only
over ``projection_conversations``. There is no acquisition surface.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import desc, distinct, select
from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.schema import projection_conversations

from wormbase_lake_maintainer.types import (
    Classification,
    ClassificationUpdate,
    DriftReport,
    LineageReport,
    StalenessReport,
)


@dataclass
class ConversationSource:
    """MaintainableSource for one tenant's conversation lake.

    A single ConversationSource per tenant covers every channel — the
    introspection methods filter by company_id. Per-channel scoping
    is handled inside the Reactivities when a channel-specific signal
    is needed.
    """

    id: UUID
    company_id: UUID
    classification: Classification
    domain: UUID | None
    owner: UUID | None
    engine: AsyncEngine

    # Maintenance state — same shape as AcquirableSourceImpl
    last_seen: datetime | None = None
    staleness_sla_hours: float = 24.0
    baseline_topic_keys: frozenset[str] = field(default_factory=frozenset)

    family: Literal["conversation"] = "conversation"
    # Conversation is always WormBase-curated (no upstream catalog).
    source_mode: Literal["wormbase_owned", "upstream_mirror"] = "wormbase_owned"

    # ------------------------------------------------------------------
    # Introspection (per spike C4)
    # ------------------------------------------------------------------

    async def enumerate_channels(self) -> list[str]:
        """Return the distinct channel_ids with at least one ingested message."""
        stmt = (
            select(distinct(projection_conversations.c.channel_id))
            .where(projection_conversations.c.company_id == self.company_id)
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result]

    async def recent_window(self, n: int) -> list[dict[str, Any]]:
        """Return the most recent ``n`` messages across all channels, newest first."""
        stmt = (
            select(
                projection_conversations.c.channel_id,
                projection_conversations.c.message_id,
                projection_conversations.c.sender_person,
                projection_conversations.c.ts,
                projection_conversations.c.text,
                projection_conversations.c.classification,
                projection_conversations.c.domain_id,
                projection_conversations.c.platform,
            )
            .where(projection_conversations.c.company_id == self.company_id)
            .order_by(desc(projection_conversations.c.ts))
            .limit(n)
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return [dict(r._mapping) for r in result]

    async def topic_summary(self) -> dict[str, int]:
        """Return a per-classification message count.

        v1 uses classification as the topic proxy. A follow-up wave will
        wire the topic extractor (existing in worm-core) and replace the
        per-classification counts with per-topic counts.
        """
        stmt = (
            select(projection_conversations.c.classification)
            .where(projection_conversations.c.company_id == self.company_id)
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return dict(Counter(r[0] for r in result))

    # ------------------------------------------------------------------
    # MaintainableSource impl
    # ------------------------------------------------------------------

    async def detect_drift(self) -> DriftReport:
        """Topic-cluster drift: compare current topic keys against baseline."""
        summary = await self.topic_summary()
        current_keys = frozenset(summary.keys())
        if not self.baseline_topic_keys:
            return DriftReport(
                drifted=False, reason="no baseline yet",
                baseline_hash=None, current_hash=None,
            )
        new_keys = current_keys - self.baseline_topic_keys
        if not new_keys:
            return DriftReport(drifted=False, reason="topic clusters stable")
        return DriftReport(
            drifted=True,
            reason=f"new topic clusters: {sorted(new_keys)}",
        )

    async def refresh_classification(self) -> ClassificationUpdate:
        """v1: report current classification unchanged."""
        return ClassificationUpdate(
            updated=False,
            classification=self.classification,
            previous_classification=self.classification,
            reason="per-message classification is set at write time (v1)",
        )

    async def staleness_signal(self) -> StalenessReport:
        """Last message ingested vs. now."""
        stmt = (
            select(projection_conversations.c.ts)
            .where(projection_conversations.c.company_id == self.company_id)
            .order_by(desc(projection_conversations.c.ts))
            .limit(1)
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            row = result.first()
        last_ts = row[0] if row else None
        if last_ts is None:
            return StalenessReport(
                stale=True, last_seen=None,
                sla_hours=self.staleness_sla_hours,
            )
        # SQLite/aiosqlite returns naive datetimes; ts is stored as UTC.
        # Postgres driver returns aware datetimes already. Normalize.
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)
        age = datetime.now(UTC) - last_ts
        return StalenessReport(
            stale=age > timedelta(hours=self.staleness_sla_hours),
            last_seen=last_ts,
            sla_hours=self.staleness_sla_hours,
        )

    async def lineage_health(self) -> LineageReport:
        """v1: conversation lineage check is no broken edges."""
        return LineageReport(healthy=True, broken_edges=[])


__all__ = ["ConversationSource"]
