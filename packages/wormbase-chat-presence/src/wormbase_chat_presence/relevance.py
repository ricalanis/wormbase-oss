"""Backward-compat shim: relevance gate moved to wormbase_governance.relevance.

Wave D consolidation. Chat-presence's local copy was a byte-for-byte
duplicate of the worm-core copy; both now re-export from the canonical
governance home. New chat-presence code should consume the gate via
ReactivityContext.extras (the dispatcher injection pattern documented
in chat_flows/_shared.py) rather than direct import.
"""
from wormbase_governance.relevance import (  # noqa: F401
    RulesBasedRelevanceGate,
    Talkativeness,
    _DATA_SOURCE_KEYWORDS,
)

__all__ = ["RulesBasedRelevanceGate", "Talkativeness", "_DATA_SOURCE_KEYWORDS"]
