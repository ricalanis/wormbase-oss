"""Tests for `synthesize_decision` (C.1: lifted decision-record synthesis).

Covers:
- chat without decision-language returns ``None``
- positive return for each ``_DECISION_PATTERNS`` regex
- ``decision_text`` strips to the matching clause (not the full chat blob)
- ``decided_by_persons`` derived from sender + explicit ``@mention`` tokens
- ``evidence_message_ids`` includes the source ``message_id``
- ``confidence`` is in ``[0.0, 1.0]``
- heuristic-only confidence (low) when ``llm=None``
- elevated confidence when a stub ``LLMClient`` affirms
- round-trips via ``DecisionRecordedPayload.model_validate(...)`` from
  ``wormbase_ledger.entries`` (the lifted module's payload class is the same
  one the worm-core extractor wrote)
- equivalence property test against the legacy ``ProcessExtractor._extract_decisions``
  on a 5-row fixture (the regression signal that the lift is faithful — the
  legacy code stays in place during C.1; G.2 will delete it)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger.entries import DecisionRecordedPayload
from wormbase_process_extractor.decisions import (
    DecisionPayload,
    LLMClient,
    synthesize_decision,
)
from wormbase_process_extractor.predicates import _DECISION_PATTERNS


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC).isoformat()


def _args(
    *,
    text: str,
    sender: UUID | None = None,
    channel_id: str = "C-finance",
    message_id: str = "M-100",
    ts: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "sender_person": str(sender or uuid4()),
        "channel_id": channel_id,
        "message_id": message_id,
        "ts": ts or _ts(),
    }


# ---------------------------------------------------------------------------
# Negative case
# ---------------------------------------------------------------------------


async def test_no_decision_language_returns_none() -> None:
    payload = await synthesize_decision(_args(text="good morning everyone"))
    assert payload is None


async def test_empty_text_returns_none() -> None:
    payload = await synthesize_decision(_args(text=""))
    assert payload is None


async def test_missing_text_returns_none() -> None:
    args = _args(text="we decided to ship")
    args.pop("text")
    payload = await synthesize_decision(args)
    assert payload is None


# ---------------------------------------------------------------------------
# Positive cases — one per regex
# ---------------------------------------------------------------------------


_PATTERN_CASES = [
    "we decided to migrate to Snowflake",         # pattern 1
    "let's go with the redesign",                 # pattern 2
    "approved by legal yesterday",                # pattern 3
    "ship it",                                    # pattern 4
    "we agreed on a 30-day pilot",                # pattern 1
    "let's push the release to Friday",           # pattern 2
    "approval granted on the budget",             # pattern 3
    "LGTM",                                       # pattern 4
]


@pytest.mark.parametrize("text", _PATTERN_CASES)
async def test_pattern_match_returns_payload(text: str) -> None:
    payload = await synthesize_decision(_args(text=text))
    assert payload is not None
    assert isinstance(payload, DecisionPayload)
    # At least one regex must be the one that fired.
    assert any(p.search(text) for p in _DECISION_PATTERNS)


async def test_all_patterns_have_at_least_one_positive_case() -> None:
    """Smoke test: every regex in ``_DECISION_PATTERNS`` has a positive case
    in this file. Defends against silently dropping a pattern at lift time."""
    matched_patterns: set[int] = set()
    for text in _PATTERN_CASES:
        for i, p in enumerate(_DECISION_PATTERNS):
            if p.search(text):
                matched_patterns.add(i)
    assert matched_patterns == set(range(len(_DECISION_PATTERNS)))


# ---------------------------------------------------------------------------
# Field-extraction contract
# ---------------------------------------------------------------------------


async def test_decision_text_is_matching_clause_not_full_chat() -> None:
    """``decision_text`` must be the matching clause window, not the entire
    blob. The legacy heuristic path writes the full text; the lifted single-
    entry shape narrows to the matching clause for downstream search hits."""
    full = (
        "Lots of context here describing the meeting and tangents — "
        "we decided to migrate to Snowflake — and then more discussion."
    )
    payload = await synthesize_decision(_args(text=full))
    assert payload is not None
    assert "we decided to migrate to snowflake" in payload.decision_text.lower()
    assert len(payload.decision_text) < len(full)


async def test_decided_by_persons_includes_sender() -> None:
    sender = uuid4()
    payload = await synthesize_decision(
        _args(text="we decided to ship", sender=sender)
    )
    assert payload is not None
    assert sender in payload.decided_by_persons


async def test_decided_by_persons_includes_at_mentions_when_uuid_shaped() -> None:
    """Explicit @mention tokens in the chat that resolve to a UUID-shaped
    handle are added as additional deciders. Non-UUID handles (regular
    @bob) are silently skipped — Person resolution is the Reactivity's job,
    not the synthesis's."""
    sender = uuid4()
    other = uuid4()
    text = f"we approved the budget — @{other} confirmed"
    payload = await synthesize_decision(
        _args(text=text, sender=sender)
    )
    assert payload is not None
    assert sender in payload.decided_by_persons
    assert other in payload.decided_by_persons


async def test_decided_by_persons_skips_non_uuid_mentions() -> None:
    sender = uuid4()
    payload = await synthesize_decision(
        _args(text="we approved the budget — @bob confirmed", sender=sender)
    )
    assert payload is not None
    assert payload.decided_by_persons == [sender]


async def test_evidence_message_ids_contains_source_message_id() -> None:
    payload = await synthesize_decision(
        _args(text="ship it", message_id="M-42")
    )
    assert payload is not None
    assert "M-42" in payload.evidence_message_ids


async def test_confidence_is_in_unit_interval() -> None:
    payload = await synthesize_decision(_args(text="ship it"))
    assert payload is not None
    assert 0.0 <= payload.confidence <= 1.0


# ---------------------------------------------------------------------------
# LLM-confidence escalation
# ---------------------------------------------------------------------------


async def test_heuristic_only_confidence_when_llm_none() -> None:
    payload = await synthesize_decision(_args(text="ship it"), llm=None)
    assert payload is not None
    # Heuristic-only is "low confidence" — same band as the legacy path
    # (0.55 in process_extractor.py:551). Bound permissively to avoid
    # locking the literal in two places.
    assert payload.confidence <= 0.6


class _AffirmingLLM:
    """Stub LLM that asserts the proposed decision is real and returns
    elevated confidence. Implements the ``LLMClient`` Protocol surface
    used by ``synthesize_decision``."""

    def __init__(self) -> None:
        self.called_with: list[str] = []

    async def affirm_decision(
        self,
        *,
        text: str,
        evidence_message_ids: list[str],
    ) -> float | None:
        self.called_with.append(text)
        return 0.92


class _DenyingLLM:
    """Stub LLM that rejects the heuristic match (returns None)."""

    async def affirm_decision(
        self,
        *,
        text: str,
        evidence_message_ids: list[str],
    ) -> float | None:
        return None


async def test_llm_affirmation_elevates_confidence() -> None:
    llm = _AffirmingLLM()
    payload = await synthesize_decision(_args(text="ship it"), llm=llm)
    assert payload is not None
    assert payload.confidence >= 0.8
    # Wire-check: the LLM was actually called with the matched clause.
    assert llm.called_with
    assert "ship it" in llm.called_with[0].lower()


async def test_llm_denial_keeps_heuristic_confidence() -> None:
    """If the LLM denies, the heuristic match still produces a payload
    (the predicate fired) but confidence stays at heuristic level — the
    Reactivity owns the threshold check (per plan)."""
    payload = await synthesize_decision(_args(text="ship it"), llm=_DenyingLLM())
    assert payload is not None
    assert payload.confidence <= 0.6


async def test_llm_protocol_class_is_exported() -> None:
    """``LLMClient`` Protocol is part of the package surface so callers
    can type-annotate their stubs without reaching into private modules."""
    assert LLMClient is not None  # imported at module top


# ---------------------------------------------------------------------------
# Round-trip with the canonical DecisionRecordedPayload
# ---------------------------------------------------------------------------


async def test_decision_payload_round_trips_via_ledger_payload() -> None:
    """The lifted ``DecisionPayload`` round-trips through
    ``DecisionRecordedPayload.model_validate`` so the Reactivity (F.3) can
    pass the dict straight to the ledger-write helper without re-shaping."""
    sender = uuid4()
    payload = await synthesize_decision(
        _args(text="we approved the budget", sender=sender)
    )
    assert payload is not None

    as_dict = payload.model_dump(mode="json")
    revalidated = DecisionRecordedPayload.model_validate(as_dict)

    assert revalidated.decision_text == payload.decision_text
    assert revalidated.channel_id == payload.channel_id
    assert revalidated.confidence == payload.confidence
    assert revalidated.evidence_message_ids == payload.evidence_message_ids
    assert revalidated.decided_by_persons == payload.decided_by_persons
    assert revalidated.decision_at == payload.decision_at


# ---------------------------------------------------------------------------
# Equivalence vs legacy ``ProcessExtractor._extract_decisions``
# ---------------------------------------------------------------------------


_FIXTURE_ROWS: list[dict[str, Any]] = [
    {
        "text": "we decided to migrate to Snowflake",
        "sender_person": "11111111-1111-1111-1111-111111111111",
        "channel_id": "C-finance",
        "message_id": "M-1",
        "ts": datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC).isoformat(),
    },
    {
        "text": "let's go with vendor B",
        "sender_person": "22222222-2222-2222-2222-222222222222",
        "channel_id": "C-eng",
        "message_id": "M-2",
        "ts": datetime(2026, 5, 3, 12, 1, 0, tzinfo=UTC).isoformat(),
    },
    {
        "text": "approval granted on the budget",
        "sender_person": "33333333-3333-3333-3333-333333333333",
        "channel_id": "C-finance",
        "message_id": "M-3",
        "ts": datetime(2026, 5, 3, 12, 2, 0, tzinfo=UTC).isoformat(),
    },
    {
        "text": "ship it",
        "sender_person": "44444444-4444-4444-4444-444444444444",
        "channel_id": "C-eng",
        "message_id": "M-4",
        "ts": datetime(2026, 5, 3, 12, 3, 0, tzinfo=UTC).isoformat(),
    },
    {
        "text": "good morning everyone",  # negative — no decision
        "sender_person": "55555555-5555-5555-5555-555555555555",
        "channel_id": "C-general",
        "message_id": "M-5",
        "ts": datetime(2026, 5, 3, 12, 4, 0, tzinfo=UTC).isoformat(),
    },
]


async def test_lifted_extract_decisions_drops_negative_rows() -> None:
    """Drive ``synthesize_decision`` over a 5-row fixture (4 positives + 1
    negative) and assert the negative is dropped while the 4 positives lift.

    Replaces the prior legacy-equivalence test (Wave C₂ G.2 — the legacy
    ``ProcessExtractor`` body was deleted; the fixture coverage is preserved
    on the lifted path alone)."""
    lifted_payloads: list[DecisionPayload] = []
    for row in _FIXTURE_ROWS:
        p = await synthesize_decision(row)
        if p is not None:
            lifted_payloads.append(p)

    assert len(lifted_payloads) == 4  # 4 positives, 1 negative dropped


async def test_decision_at_is_tz_aware() -> None:
    payload = await synthesize_decision(_args(text="ship it"))
    assert payload is not None
    assert payload.decision_at.tzinfo is not None


async def test_synthesize_decision_is_public_export() -> None:
    """``synthesize_decision`` is exported from the package surface so the
    Reactivity (Block F.3) imports it from ``wormbase_process_extractor``
    rather than reaching into the submodule."""
    import wormbase_process_extractor as pkg

    assert "synthesize_decision" in pkg.__all__
    assert pkg.synthesize_decision is synthesize_decision
