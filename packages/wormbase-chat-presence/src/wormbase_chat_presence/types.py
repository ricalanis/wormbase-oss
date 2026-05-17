# > AUTHORED 2026-05-03: load-bearing chat-worm value types per Block B2.
# > ChatPolicy + ConversationContext are frozen dataclasses; ChatMessage
# > is the read-side projection_conversations row; MessageRef re-exports
# > from wormbase_channel_adapters.types for caller convenience.
"""Value types for chat-presence.

ChatPolicy — per-channel posture; resolved from policy_applied entries
  via ChatStore.read_policy. Default (no policy_applied yet):
  talkativeness="responsive", daily_interjection_budget=3.

ConversationContext — built per-event by the dispatcher. Carries the
  channel/domain/classification triad + the resolved ChatPolicy. Passed to
  RelevanceGate and the four Reactivities.

ChatMessage — read-side projection shape; one-row representation of a
  projection_conversations row, minus the company_id (already keyed).

MessageRef — re-exported from wormbase_channel_adapters.types so callers
  don't need to import two packages for a return type.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from wormbase_channel_adapters.types import MessageRef as _MessageRef
from wormbase_ledger.entries import Classification

# Re-export for convenience.
MessageRef = _MessageRef

Talkativeness = Literal["lurker", "responsive", "proactive"]
SpeechAct = Literal["answer", "proposal", "clarification"]


@dataclass(frozen=True)
class Install:
    """Wire-side install record (the dataclass downstream of OAuth).

    Mirrors the projection_installs row shape (CLAUDE.md §4) for the fields
    lifecycle factories actually read. The full ledger-projected row carries
    more (oauth_grant, installed_at, status, scopes); those are projection-
    only and stay in the projection schema.

    Replaces the SimpleNamespace(id=..., platform=...) duck-typing previously
    threaded through the wire_*_for_install factories (O-A2, 2026-05-04).
    """

    id: UUID
    platform: str
    installer_person_id: UUID | None = None
    bot_user_id: str | None = None


@dataclass(frozen=True)
class ChatPolicy:
    """Per-channel posture; resolved from policy_applied entries.

    Default (no policy_applied yet): talkativeness="responsive",
    daily_interjection_budget=3.

    Frozen as of the read; the dashboard mutates by writing a new
    policy_applied entry, not by mutating this object.
    """

    talkativeness: Talkativeness
    daily_interjection_budget: int


@dataclass(frozen=True)
class ConversationContext:
    """The chat triad's normalized event-context surface.

    Built from the InfraEvent + ChatPolicy lookup; passed to RelevanceGate
    and the four Reactivities.

    `channel_id`: optional because cron / webhook events have no channel.
    `domain_id`: optional because not every channel maps to a domain.
    `is_dm`: True for direct messages (always-respond per CLAUDE.md §1).
    `classification`: the channel's effective classification (folded from
    most recent policy_applied for the channel; defaults to "internal").
    `policy`: the resolved ChatPolicy at event-receive time.
    """

    company_id: UUID
    channel_id: str | None
    domain_id: UUID | None
    is_dm: bool
    classification: Classification
    policy: ChatPolicy


@dataclass(frozen=True)
class ChatMessage:
    """Read-side row from projection_conversations.

    sender_person is the resolved Person UUID (None when the source
    platform_user_id has no resolved Person — auto-discovery hasn't fired
    yet, or fired but admin hasn't confirmed).
    """

    channel_id: str
    message_id: str
    sender_person: UUID | None
    ts: datetime
    text: str
    classification: Classification
    domain_id: UUID | None
    thread_root_message_id: str | None
    platform: str
    ingested_at: datetime


__all__ = [
    "ChatMessage",
    "ChatPolicy",
    "ConversationContext",
    "Install",
    "MessageRef",
    "SpeechAct",
    "Talkativeness",
]
