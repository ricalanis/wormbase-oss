"""W5a predicates owned by the process-worm package.

Houses the concrete ``MatchesDecisionPattern`` predicate that fires on
chat messages whose text carries decision-language signal. The predicate
is composable with the W5a algebra exposed by ``wormbase_reactivities`` —
typical use:

    EntryKind("chat_received") & MatchesDecisionPattern()

This is the only new W5a primitive introduced in Wave C₂; subsequent
process-worm Reactivities (decision extraction, process-step extraction,
etc.) compose existing primitives over the ledger projection rather than
adding more.

The ``_DECISION_PATTERNS`` tuple is lifted byte-identical from
``apps/worm-core/src/wormbase_core/process_extractor.py:76-81`` so
behavior matches the legacy heuristic exactly. Keep the regexes in sync
if either side changes — they remain the single source of truth for
decision-language detection during the Wave C₂ extraction.
"""

from __future__ import annotations

import re
from typing import Any

from wormbase_reactivities.predicates import _ArgsPredicate
from wormbase_reactivities.protocol import ReactivityContext

# Lifted verbatim from
# apps/worm-core/src/wormbase_core/process_extractor.py:76-81. Do NOT edit
# in isolation — verify with diff against the source if the legacy
# heuristic changes during the extraction window.
_DECISION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwe (decided|agreed|approved|went with|chose|are going to)\b", re.IGNORECASE),
    re.compile(r"\blet'?s (go with|do|use|approve|push|move to)\b", re.IGNORECASE),
    re.compile(r"\b(decision|approved|approval granted|sign(ed)? off)\b", re.IGNORECASE),
    re.compile(r"\b(green ?light|ship it|lgtm|ok by me)\b", re.IGNORECASE),
)


class MatchesDecisionPattern(_ArgsPredicate):
    """Match ``chat_received`` execute entries whose ``args["text"]`` carries
    decision-language signal (regexes lifted from
    ``apps/worm-core/.../process_extractor.py:76-81``).

    Returns False on missing/empty/non-string ``text`` so the predicate is
    safe to compose with ``EntryKind("chat_received")`` without an extra
    text-presence guard. Subclasses ``_ArgsPredicate`` (re-used from
    ``wormbase_reactivities.predicates``) so the standard non-execute /
    args-extraction guard inherits unchanged — no new Protocol surface.
    """

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        text = args.get("text")
        if not isinstance(text, str) or not text:
            return False
        return any(p.search(text) for p in _DECISION_PATTERNS)


__all__ = ["MatchesDecisionPattern"]
