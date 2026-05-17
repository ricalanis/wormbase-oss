"""Tests for `MatchesDecisionPattern` (W5a predicate for process-worm).

Covers:
- one positive case per regex in `_DECISION_PATTERNS`
- negative cases: empty string, ``None``, non-string, signal-free text
- composability with ``EntryKind("chat_received")`` via the W5a algebra
- public re-export from ``wormbase_process_extractor`` (not from
  ``.predicates``) so downstream callers depend on the package surface
"""

from __future__ import annotations

from typing import Any

import pytest

# Public surface assertion: import from the package, not the submodule.
from wormbase_process_extractor import MatchesDecisionPattern
from wormbase_reactivities.predicates import EntryKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chat_entry(text: Any) -> dict[str, Any]:
    """Build an ``execute`` envelope wrapping a ``chat_received`` tool call."""
    return {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"text": text},
        },
    }


# Stand-in for ``ReactivityContext`` — the predicate ignores the context, so
# any object will do. ``None`` is sufficient and avoids test-only fixtures.
_CTX: Any = None


# ---------------------------------------------------------------------------
# Positive cases — one per regex in ``_DECISION_PATTERNS``
# ---------------------------------------------------------------------------


# Pattern 1: \bwe (decided|agreed|approved|went with|chose|are going to)\b
_PATTERN_1_CASES = [
    "we decided to ship the new pricing tier",
    "We agreed on a 30-day pilot.",
    "we approved the budget yesterday",
    "we went with vendor B in the end",
    "we chose Postgres over Snowflake for this slice",
    "we are going to migrate next quarter",
]

# Pattern 2: \blet'?s (go with|do|use|approve|push|move to)\b
_PATTERN_2_CASES = [
    "let's go with the second option",
    "Lets go with the redesign",  # apostrophe-optional branch
    "let's do the rollout in phases",
    "let's use the new pipeline",
    "let's approve this and move on",
    "let's push the release to Friday",
    "let's move to the new dashboard",
]

# Pattern 3: \b(decision|approved|approval granted|sign(ed)? off)\b
_PATTERN_3_CASES = [
    "the decision is final",
    "approved by legal",
    "approval granted on the budget",
    "sign off on the migration plan",
    "she signed off on the launch",
]

# Pattern 4: \b(green ?light|ship it|lgtm|ok by me)\b
_PATTERN_4_CASES = [
    "greenlight from product",
    "green light from product",
    "ship it",
    "LGTM",
    "ok by me, go ahead",
]

_ALL_POSITIVE_CASES = (
    _PATTERN_1_CASES + _PATTERN_2_CASES + _PATTERN_3_CASES + _PATTERN_4_CASES
)


@pytest.mark.parametrize("text", _ALL_POSITIVE_CASES)
async def test_matches_decision_pattern_positive(text: str) -> None:
    pred = MatchesDecisionPattern()
    entry = _chat_entry(text)
    assert await pred.match(entry, _CTX) is True


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        123,
        ["we decided to ship"],  # list, not str
        {"text": "approved"},  # dict, not str
        "I had coffee this morning",
        "let me know what you think",
        "ok, talk later",  # 'ok' alone, no 'ok by me'
        "we are happy with the team",  # 'we are' but not the verb list
    ],
)
async def test_matches_decision_pattern_negative(text: Any) -> None:
    pred = MatchesDecisionPattern()
    entry = _chat_entry(text)
    assert await pred.match(entry, _CTX) is False


async def test_matches_decision_pattern_missing_args_field() -> None:
    """No ``text`` key in args — predicate returns False, no KeyError."""
    pred = MatchesDecisionPattern()
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"sender_person": "alice"},
        },
    }
    assert await pred.match(entry, _CTX) is False


async def test_matches_decision_pattern_non_execute_envelope() -> None:
    """Inherited ``_ArgsPredicate`` guard — non-execute envelopes return False."""
    pred = MatchesDecisionPattern()
    entry = {
        "kind": "propose",
        "payload": {"args": {"text": "we decided to ship"}},
    }
    assert await pred.match(entry, _CTX) is False


# ---------------------------------------------------------------------------
# Composability with the W5a algebra
# ---------------------------------------------------------------------------


async def test_composable_with_entrykind_via_and() -> None:
    """``EntryKind("chat_received") & MatchesDecisionPattern()`` is the
    canonical composition. Accepts a chat_received entry whose text matches;
    rejects one whose text doesn't."""
    pred = EntryKind("chat_received") & MatchesDecisionPattern()

    matching_entry = _chat_entry("we decided to migrate to Snowflake")
    non_matching_entry = _chat_entry("good morning everyone")

    assert await pred.match(matching_entry, _CTX) is True
    assert await pred.match(non_matching_entry, _CTX) is False


async def test_composable_rejects_wrong_kind_even_with_matching_text() -> None:
    """And-composition with ``EntryKind`` short-circuits on kind mismatch
    even when the text would match — the kind gate is doing its job."""
    pred = EntryKind("chat_received") & MatchesDecisionPattern()

    # Same args text, but a different tool — not chat_received.
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_person_proposed",
            "args": {"text": "we decided to ship"},
        },
    }
    assert await pred.match(entry, _CTX) is False


# ---------------------------------------------------------------------------
# Public-surface re-export assertion
# ---------------------------------------------------------------------------


def test_matches_decision_pattern_is_public_export() -> None:
    """Imported above from ``wormbase_process_extractor`` (not from
    ``.predicates``). Assert the symbol is the same object as the one in
    the package ``__all__`` and that ``__all__`` lists it."""
    import wormbase_process_extractor as pkg

    assert "MatchesDecisionPattern" in pkg.__all__
    assert pkg.MatchesDecisionPattern is MatchesDecisionPattern
