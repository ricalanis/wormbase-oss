"""wormbase-channel-adapter — OpenClaw session JSONL → ledger entries.

Tail mode (production / docker-compose):
    python -m wormbase_channel_adapter run \\
        --sessions-path /openclaw-state/agents/main/sessions \\
        --state-path /var/lib/wormbase-channel-adapter/state.json

The service watches the OpenClaw session JSONL files for new lines, parses
each event, classifies it as ``chat_received`` (Slack inbound) or
``chat_sent`` (assistant outbound text reply), and appends a 4-step
propose/execute/verify/resolve sequence to the ledger via the public
:class:`wormbase_ledger.Ledger` API. Tool calls, tool results, and other
session-control events are ignored.

State (file → byte offset) is persisted to a small JSON file so a restart
does not re-emit ledger entries for the same line.
"""

from __future__ import annotations

__version__ = "0.1.0"

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    ChatSentEvent,
    ParsedEvent,
    parse_session_line,
)
from wormbase_channel_adapter.state import OffsetState
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter

__all__ = [
    "ChatReceivedEvent",
    "ChatSentEvent",
    "LedgerWriter",
    "OffsetState",
    "ParsedEvent",
    "__version__",
    "parse_session_line",
    "tenant_to_company_uuid",
]
