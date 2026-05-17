"""Backward-compat shim: relevance gate moved to wormbase_governance.relevance.

Wave D consolidation lifted RulesBasedRelevanceGate into the governance
package alongside the four other gate impls (PII, Warmup, Interjection,
Knowledge). Existing import paths continue to work via this re-export
shim. New code should import from wormbase_governance.relevance directly.

Wave E will remove this shim as part of the worm-core slim-down.
"""
from wormbase_governance.relevance import (  # noqa: F401
    RulesBasedRelevanceGate,
    Talkativeness,
    _DATA_SOURCE_KEYWORDS,
)

__all__ = ["RulesBasedRelevanceGate", "Talkativeness", "_DATA_SOURCE_KEYWORDS"]
