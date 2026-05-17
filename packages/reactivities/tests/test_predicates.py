"""Predicate composability + edge cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from wormbase_reactivities import (
    And,
    EntryKind,
    HasDomain,
    HasOwner,
    HasTopic,
    Or,
    ReactivityContext,
    ReactivityRegistry,
    ResolvedKept,
    SpeakerNotOwner,
)


def _ctx(ledger, company_id: UUID) -> ReactivityContext:
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC),
    )
    return ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=registry._now,  # noqa: SLF001
        extras={"reactivity_id": "test"},
    )


def _execute(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "execute",
        "seq": 1,
        "payload": {"tool": tool, "args": args},
    }


# ---------------------------------------------------------------------------
# EntryKind
# ---------------------------------------------------------------------------


async def test_entry_kind_matches_envelope_kind(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = EntryKind("execute")
    entry = {"kind": "execute", "payload": {"tool": "x", "args": {}}}
    assert await p.match(entry, ctx) is True


async def test_entry_kind_matches_dotted_tool(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = EntryKind("chat_received")
    entry = _execute("channel_adapter.emit_chat_received", {})
    assert await p.match(entry, ctx) is True


async def test_entry_kind_matches_emit_prefixed_tool(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = EntryKind("person_proposed")
    entry = _execute("emit_person_proposed", {})
    assert await p.match(entry, ctx) is True


async def test_entry_kind_no_match_other_tool(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = EntryKind("chat_received")
    entry = _execute("emit_person_proposed", {})
    assert await p.match(entry, ctx) is False


async def test_entry_kind_skips_non_execute_for_tool_match(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = EntryKind("chat_received")
    entry = {"kind": "propose", "payload": {"tool": "chat_received", "args": {}}}
    # Tool match only checked on execute envelopes.
    assert await p.match(entry, ctx) is False


# ---------------------------------------------------------------------------
# HasTopic / HasDomain / HasOwner / SpeakerNotOwner
# ---------------------------------------------------------------------------


async def test_has_topic_matches_topic_arg(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = HasTopic()
    entry = _execute("emit_x", {"topic": "churn"})
    assert await p.match(entry, ctx) is True


async def test_has_topic_skips_when_absent(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = HasTopic()
    entry = _execute("emit_x", {"text": "no topic here"})
    assert await p.match(entry, ctx) is False


async def test_has_domain_matches_domain_id(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = HasDomain()
    entry = _execute("emit_x", {"domain_id": "uuid-123"})
    assert await p.match(entry, ctx) is True


async def test_has_owner_matches_owner_person_id(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = HasOwner()
    entry = _execute("emit_x", {"owner_person_id": "p-1"})
    assert await p.match(entry, ctx) is True


async def test_speaker_not_owner_matches_when_distinct(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = SpeakerNotOwner()
    entry = _execute(
        "emit_x", {"sender_person": "p-1", "owner_person_id": "p-2"},
    )
    assert await p.match(entry, ctx) is True


async def test_speaker_not_owner_skips_self_statement(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = SpeakerNotOwner()
    entry = _execute(
        "emit_x", {"sender_person": "p-1", "owner_person_id": "p-1"},
    )
    assert await p.match(entry, ctx) is False


async def test_speaker_not_owner_skips_when_either_missing(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = SpeakerNotOwner()
    entry = _execute("emit_x", {"sender_person": "p-1"})
    assert await p.match(entry, ctx) is False


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


async def test_and_short_circuits_on_first_false(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    # Use mismatched kinds in tandem — the AND fails on the first.
    composed = EntryKind("chat_received") & HasTopic()
    entry = _execute("emit_person_proposed", {"topic": "churn"})
    assert await composed.match(entry, ctx) is False


async def test_and_returns_true_when_all_match(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    composed = (
        EntryKind("chat_received") & HasTopic() & SpeakerNotOwner()
    )
    entry = _execute(
        "channel_adapter.emit_chat_received",
        {
            "topic": "churn",
            "sender_person": "p-1",
            "owner_person_id": "p-2",
        },
    )
    assert await composed.match(entry, ctx) is True


async def test_or_short_circuits_on_first_true(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    composed = EntryKind("chat_received") | EntryKind("file_received")
    entry = _execute("channel_adapter.emit_file_received", {})
    assert await composed.match(entry, ctx) is True


async def test_or_returns_false_when_none_match(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    composed = EntryKind("foo") | EntryKind("bar")
    entry = _execute("emit_baz", {})
    assert await composed.match(entry, ctx) is False


async def test_not_inverts(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    composed = ~EntryKind("chat_received")
    chat = _execute("channel_adapter.emit_chat_received", {})
    other = _execute("emit_person_proposed", {})
    assert await composed.match(chat, ctx) is False
    assert await composed.match(other, ctx) is True


async def test_empty_and_is_vacuously_true(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = And()
    entry = _execute("anything", {})
    assert await p.match(entry, ctx) is True


async def test_empty_or_is_vacuously_false(ledger, company_id: UUID) -> None:
    ctx = _ctx(ledger, company_id)
    p = Or()
    entry = _execute("anything", {})
    assert await p.match(entry, ctx) is False


async def test_complex_composition_preserves_associativity(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    # (chat | file) & topic & ~speaker_is_owner
    composed = (
        (EntryKind("chat_received") | EntryKind("file_received"))
        & HasTopic()
        & SpeakerNotOwner()
    )
    entry = _execute(
        "channel_adapter.emit_file_received",
        {
            "topic": "churn",
            "sender_person": "p-1",
            "owner_person_id": "p-2",
        },
    )
    assert await composed.match(entry, ctx) is True


async def test_payload_with_no_args_returns_false_for_args_predicates(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = HasTopic()
    entry = {"kind": "execute", "payload": {"tool": "x"}}  # no args
    assert await p.match(entry, ctx) is False


# ---------------------------------------------------------------------------
# ResolvedKept
# ---------------------------------------------------------------------------


async def test_resolved_kept_matches_kept_outcome(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = ResolvedKept()
    entry = _execute("emit_experiment_resolved", {"outcome": "keep"})
    assert await p.match(entry, ctx) is True


async def test_resolved_kept_skips_discard_outcome(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = ResolvedKept()
    entry = _execute("emit_experiment_resolved", {"outcome": "discard"})
    assert await p.match(entry, ctx) is False


async def test_resolved_kept_skips_other_kinds(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = ResolvedKept()
    # experiment_run with outcome=keep — kind gate fails.
    entry = _execute("emit_experiment_run", {"outcome": "keep"})
    assert await p.match(entry, ctx) is False


async def test_resolved_kept_skips_when_outcome_missing(
    ledger, company_id: UUID,
) -> None:
    ctx = _ctx(ledger, company_id)
    p = ResolvedKept()
    entry = _execute("emit_experiment_resolved", {"experiment_id": "e-1"})
    assert await p.match(entry, ctx) is False
