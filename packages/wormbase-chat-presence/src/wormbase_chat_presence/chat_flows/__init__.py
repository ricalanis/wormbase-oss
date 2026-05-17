"""Chat-driven source-building flows (lifted from worm-core's flows.py in Wave B).

Four flows in v1:
  - DropAndProfileFlow         — channel file_drop event
  - CredentialInDmFlow         — DM with credential URI
  - MentionedInConversationFlow — data-keyword in chat (semantic + relevance)
  - KpiGapTriggeredFlow        — KPI tree scan + worm posts to channel

Per D4 + chat-worm spike §4.2, the dashboard-form and lake-discovery flows
are NOT lifted — they are not chat-driven and stay in worm-core.
"""
from __future__ import annotations

from wormbase_chat_presence.chat_flows.credential_in_dm import (
    CredentialInDmFlow,
    credential_in_dm_with_offer_link,
    link_credential_to_proactive_offer,
)
from wormbase_chat_presence.chat_flows.drop_and_profile import DropAndProfileFlow
from wormbase_chat_presence.chat_flows.kpi_gap_triggered import KpiGap, KpiGapTriggeredFlow
from wormbase_chat_presence.chat_flows.mentioned_in_conversation import (
    MentionedInConversationFlow,
    ProactiveMentionResult,
    propose_remote_archetype,
    recognized_remote_archetypes,
)

__all__ = [
    "CredentialInDmFlow",
    "DropAndProfileFlow",
    "KpiGap",
    "KpiGapTriggeredFlow",
    "MentionedInConversationFlow",
    "ProactiveMentionResult",
    "credential_in_dm_with_offer_link",
    "link_credential_to_proactive_offer",
    "propose_remote_archetype",
    "recognized_remote_archetypes",
]
