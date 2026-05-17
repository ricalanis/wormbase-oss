"""Tests for process-worm Reactivity classes.

F.1 originally shipped TopicSynthesisReactivity as an intentional
STUB. Phase 2 Task 2B (Wave H) promotes it to a real implementation —
the regression bullets in the stub harness are kept as regression
guards on the predicate / id contract, and new bullets cover the
fire path (heuristic + router-blessed), threshold gating, the
``topic_proposed`` PEVR cycle, and graceful no-op when the cluster
hasn't crossed the topic-promotion threshold.

F.3 adds the DecisionRecordReactivity tests — first chat-driven
Reactivity in process-worm. Covers predicate composition, condition
gating (DailyBudget + NotRecentlyFired), the PEVR fire path, the
heuristic-only / LLM-elevated confidence split, and the
no-decision-language no-op path.

See plan ``docs/superpowers/plans/2026-05-03-process-worm-extraction.md``
§F.1, §F.3 and spike §4 caveat 6 / §8 C5.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_process_extractor.reactivities import (
    DecisionRecordReactivity,
    SystemMapNodeReactivity,
    TopicSynthesisReactivity,
)
from wormbase_process_extractor.system_map import _reset_tenant_accumulator
from wormbase_reactivities import ReactivityRegistry
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
)


class _RaisingLedger:
    """Stub ledger whose ``write`` raises if called.

    Used to assert that a ``fire`` path performs no ledger writes
    when its predicate-or-precondition is supposed to short-circuit.
    """

    async def write(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "fire() must not write to the ledger on a no-op path"
        )


def _make_context(extras: dict[str, Any] | None = None) -> ReactivityContext:
    return ReactivityContext(
        ledger=_RaisingLedger(),
        company_id=uuid4(),
        registry=None,
        now=lambda: datetime.now(UTC),
        extras=extras or {},
    )


@pytest.mark.asyncio
async def test_topic_synthesis_id_and_predicate_locked() -> None:
    """Predicate / id contract preserved from the F.1 stub.

      1. ``id`` is exactly ``"topic_synthesis"``
      2. ``predicate`` is ``EntryKind("chat_received")`` with no extra clauses
      3. Structural Protocol membership (registers cleanly into W5a)

    Phase 2 Task 2B promotes the stub to a real implementation — but the
    id slot and predicate shape are forever (Rule 1 of the schema-evolution
    doctrine).
    """
    reactivity = TopicSynthesisReactivity()

    assert reactivity.id == "topic_synthesis"
    assert isinstance(reactivity.predicate, EntryKind)
    assert reactivity.predicate.kind == "chat_received"
    assert isinstance(reactivity, Reactivity)


@pytest.mark.asyncio
async def test_topic_synthesis_below_threshold_is_no_op() -> None:
    """A novel cluster (size 1) must not write to the ledger.

    The topic-promotion threshold gates emission; below it, fire() must
    return ``fired=False`` and produce zero ledger entries. The
    ``_RaisingLedger`` enforces the no-write side of the contract.
    """
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    reactivity = TopicSynthesisReactivity()
    ctx = ReactivityContext(
        ledger=_RaisingLedger(),
        company_id=company_id,
        registry=None,
        now=lambda: datetime.now(UTC),
        extras={},
    )
    entry: dict[str, Any] = {
        "kind": "chat_received",
        "payload": {
            "args": {
                "text": "q3 finance reporting cadence weekly",
                "message_id": "M-001",
                "ts": "2026-05-03T10:00:00+00:00",
            },
        },
    }

    # First message — cluster size 1, below the default threshold of 2.
    result = await reactivity.fire(entry, ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is False
    assert result.actions == []


def test_topic_synthesis_fire_signature_locked() -> None:
    """Regression guard against accidental rename / shadowing of ``fire``."""
    assert TopicSynthesisReactivity.fire.__qualname__.endswith("fire")


def test_recurring_question_p10_alias() -> None:
    """F.2: ``RecurringQuestionReactivity`` is an alias to P10's class.

    Per plan §F.2 and spike §8 C3: process-worm does not wrap or
    duplicate the existing P10 ``RecurringQuestionProcessMapperReactivity``
    living at ``packages/reactivities/.../process_mapper.py``. Instead the
    process-extractor module re-exports it under a shorter alias so that
    Block G.1's factory can register it alongside the three new
    Reactivities (process-mapper / decision-record / system-map).

    Acceptance:
      - ``RecurringQuestionReactivity`` resolves to the **same class
        object** as ``RecurringQuestionProcessMapperReactivity`` — no
        wrapper, no subclass, no rewrite.
      - Instantiation produces a value that ``isinstance``-checks against
        the underlying P10 class.
      - The alias is exported from ``wormbase_process_extractor`` so the
        factory can import it from the package surface.
    """
    from wormbase_reactivities.process_mapper import (
        RecurringQuestionProcessMapperReactivity,
    )

    # Import via the process-extractor module (the alias must be exported
    # from reactivities.py so factory.py can pick it up).
    from wormbase_process_extractor.reactivities import (
        RecurringQuestionReactivity,
    )

    # Same class object — not a subclass, not a wrapper.
    assert RecurringQuestionReactivity is RecurringQuestionProcessMapperReactivity

    # Instances are real P10 instances.
    instance = RecurringQuestionReactivity()
    assert isinstance(instance, RecurringQuestionProcessMapperReactivity)

    # Public package re-export (for factory consumption in G.1).
    from wormbase_process_extractor import (
        RecurringQuestionReactivity as PackageAlias,
    )
    assert PackageAlias is RecurringQuestionProcessMapperReactivity


# ---------------------------------------------------------------------------
# F.3 — DecisionRecordReactivity
# ---------------------------------------------------------------------------


_DECISION_TEXT = "We decided to ship the new pricing on Friday."
_NON_DECISION_TEXT = "Quick reminder: standup at 9am tomorrow."


def _decision_chat_entry(
    *,
    text: str = _DECISION_TEXT,
    message_id: str = "msg-001",
    channel_id: str = "C-1",
    domain_id: str | None = None,
    sender_person: str | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    """Build a chat_received execute entry mimicking the legacy shape.

    Mirrors what ``ProcessExtractor`` historically read out of the
    ledger: ``payload.tool == "emit_chat_received"`` and ``args``
    carries text/message_id/channel_id (plus optional ts, sender_person,
    domain_id).
    """
    args: dict[str, Any] = {
        "text": text,
        "message_id": message_id,
        "channel_id": channel_id,
        "ts": "2026-04-28T12:00:00+00:00",
    }
    if domain_id is not None:
        args["domain_id"] = domain_id
    if sender_person is not None:
        args["sender_person"] = sender_person
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {"tool": "emit_chat_received", "args": args},
    }


def _make_real_context(
    *,
    ledger: InMemoryLedger,
    company_id: UUID,
    state: dict[str, datetime],
    reactivity_id: str = DecisionRecordReactivity.id,
    extras: dict[str, Any] | None = None,
) -> tuple[ReactivityRegistry, ReactivityContext]:
    """Build a ReactivityContext backed by a real registry — needed to
    exercise DailyBudget / NotRecentlyFired gating.
    """
    def _now() -> datetime:
        return state["now"]

    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now,
    )
    base_extras: dict[str, Any] = {"reactivity_id": reactivity_id}
    if extras:
        base_extras.update(extras)
    return registry, ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=_now,
        extras=base_extras,
    )


# --- Predicate -------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_record_predicate_accepts_decision_chat() -> None:
    """Predicate fires on chat_received whose text carries decision-language."""
    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry()
    assert await react.predicate.match(entry, ctx) is True


@pytest.mark.asyncio
async def test_decision_record_predicate_rejects_non_decision_chat() -> None:
    """Predicate does NOT fire on a chat_received without decision-language."""
    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry(text=_NON_DECISION_TEXT)
    assert await react.predicate.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_decision_record_predicate_rejects_non_chat_kinds() -> None:
    """Predicate rejects non-chat_received entries even with decision text."""
    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    # decision-language but a different tool — must not match.
    entry = {
        "kind": "execute",
        "seq": 9,
        "payload": {
            "tool": "emit_data_product_proposed",
            "args": {"text": _DECISION_TEXT, "message_id": "x"},
        },
    }
    assert await react.predicate.match(entry, ctx) is False


# --- Condition (DailyBudget) ----------------------------------------------


@pytest.mark.asyncio
async def test_decision_record_condition_allows_first_n_then_blocks() -> None:
    """First per_tenant_budget fires allowed; the (N+1)-th blocks until next day."""
    react = DecisionRecordReactivity(per_tenant_budget=20)
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    registry, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry()

    # Pre-populate the per-tenant counter to exactly the cap.
    day = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id=DecisionRecordReactivity.id,
        axis="tenant",
        key=str(company_id),
        day=day,
        by=20,
    )

    # 21st fire blocked.
    assert await react.condition.allows(entry, ctx) is False

    # Roll the clock forward one day; counter (keyed on yesterday's
    # date) no longer matches today's window — allowed again.
    state["now"] = state["now"] + timedelta(days=1)
    assert await react.condition.allows(entry, ctx) is True


# --- Fire path -------------------------------------------------------------


async def _entries_for(
    ledger: InMemoryLedger, company_id: UUID,
) -> list[dict[str, Any]]:
    """Return every entry written to the in-memory ledger as dicts."""
    return list(await ledger.fetch(company_id))


@pytest.mark.asyncio
async def test_decision_record_fire_writes_pevr_cycle() -> None:
    """fire() writes propose / execute / verify / resolve in order; the
    execute payload round-trips through the ledger schema.
    """
    from wormbase_ledger.entries import DecisionRecordedPayload

    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry()
    result = await react.fire(entry, ctx)

    assert result.fired is True
    assert result.actions and result.actions[0].action_kind == "decision_recorded"
    assert result.budget_used == {"per_tenant": 1}

    rows = await _entries_for(ledger, company_id)
    kinds = [row.get("kind") for row in rows]
    # Exactly one PEVR cycle was written.
    assert kinds.count("propose") == 1
    assert kinds.count("execute") == 1
    assert kinds.count("verify") == 1
    assert kinds.count("resolve") == 1
    # And the four entries arrived in the canonical order.
    pevr_kinds = [k for k in kinds if k in {"propose", "execute", "verify", "resolve"}]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"]

    # The execute payload validates against the ledger's
    # DecisionRecordedPayload — the ledger owns the schema; this round-trip
    # is the contract.
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    args = execute_row["payload"]["args"]
    payload = DecisionRecordedPayload.model_validate(args)
    assert payload.confidence > 0.0
    assert payload.channel_id == "C-1"


@pytest.mark.asyncio
async def test_decision_record_fire_no_decision_returns_no_op() -> None:
    """If fire() runs on a chat without decision-language (predicate would
    block, but if invoked directly), it must return fired=False and write
    no ledger entries.
    """
    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry(text=_NON_DECISION_TEXT)
    result = await react.fire(entry, ctx)

    assert result.fired is False
    assert await _entries_for(ledger, company_id) == []


# --- Idempotency / novelty -------------------------------------------------


@pytest.mark.asyncio
async def test_decision_record_idempotency_via_not_recently_fired() -> None:
    """Two fires for the same message_id within ``novelty_hours`` are
    blocked on the second by NotRecentlyFired.

    The Reactivity returns ``novelty_key=f"decision:{message_id}"``
    after a successful fire; the registry records that against the
    ``DecisionRecordReactivity.id`` reactivity so a subsequent
    condition check on the same key denies.
    """
    react = DecisionRecordReactivity()
    company_id = uuid4()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    registry, ctx = _make_real_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _decision_chat_entry(message_id="msg-IDEM")

    # First fire succeeds and produces a per-message novelty key.
    first = await react.fire(entry, ctx)
    assert first.fired is True
    assert first.novelty_key == "decision:msg-IDEM"

    # Simulate the registry recording the fire on the per-message novelty
    # key (the dispatcher does this in production after a successful fire).
    await registry._record_fire(  # noqa: SLF001
        reactivity_id=DecisionRecordReactivity.id,
        source_seq=entry["seq"],
        novelty_key=first.novelty_key,
        fired_at=state["now"],
    )

    # Re-evaluate condition under the per-message novelty key (mirroring
    # the dispatcher's per-entry context.extras override). The Reactivity
    # surface uses NotRecentlyFired with the literal key "decision"; a
    # production dispatcher routes a per-message key via context.extras.
    ctx.extras["novelty_key"] = first.novelty_key
    allowed = await react.condition.allows(entry, ctx)
    assert allowed is False


# --- LLM-optional ----------------------------------------------------------


class _AffirmingLLM:
    """Stub LLMClient that escalates confidence for any decision text."""

    def __init__(self, confidence: float = 0.92) -> None:
        self.confidence = confidence
        self.calls = 0

    async def affirm_decision(
        self, *, text: str, evidence_message_ids: list[str],
    ) -> float:
        self.calls += 1
        return self.confidence


@pytest.mark.asyncio
async def test_decision_record_fire_llm_optional_paths() -> None:
    """LLM=None: heuristic-only confidence emitted (~0.55).
    LLM=stub-affirming: confidence escalates to the stub's value.
    """
    company_id = uuid4()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}

    # Pass 1: no LLM → heuristic-only confidence on the emitted entry.
    react_no_llm = DecisionRecordReactivity()
    ledger_no_llm = InMemoryLedger()
    _, ctx_no_llm = _make_real_context(
        ledger=ledger_no_llm, company_id=company_id, state=state,
    )
    res = await react_no_llm.fire(_decision_chat_entry(message_id="m-A"), ctx_no_llm)
    assert res.fired is True
    rows = await _entries_for(ledger_no_llm, company_id)
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    heuristic_confidence = execute_row["payload"]["args"]["confidence"]
    assert 0.0 < heuristic_confidence <= 0.6  # canonical low band

    # Pass 2: stub LLM affirms → confidence escalates.
    react_llm = DecisionRecordReactivity()
    ledger_llm = InMemoryLedger()
    affirming = _AffirmingLLM(confidence=0.92)
    _, ctx_llm = _make_real_context(
        ledger=ledger_llm,
        company_id=company_id,
        state=state,
        extras={"decision_llm_client": affirming},
    )
    res2 = await react_llm.fire(_decision_chat_entry(message_id="m-B"), ctx_llm)
    assert res2.fired is True
    assert affirming.calls == 1

    rows2 = await _entries_for(ledger_llm, company_id)
    execute_row2 = next(r for r in rows2 if r.get("kind") == "execute")
    elevated_confidence = execute_row2["payload"]["args"]["confidence"]
    assert elevated_confidence == pytest.approx(0.92)
    assert elevated_confidence > heuristic_confidence


# --- Lazy import guard -----------------------------------------------------


def test_decision_record_module_does_not_import_wormbase_llm() -> None:
    """``import wormbase_process_extractor.reactivities`` must NOT pull
    ``wormbase_llm`` into ``sys.modules``.

    Per F.3 acceptance — the lazy-LLM hook lives in fire() via
    ``context.extras``; the module's static import surface stays light.
    Mirrors the phenomenon_gaps.py:431 lazy pattern.
    """
    import subprocess
    import sys

    code = (
        "import sys; "
        "import wormbase_process_extractor.reactivities; "
        "print('wormbase_llm' in sys.modules)"
    )
    out = subprocess.check_output(
        [sys.executable, "-c", code], text=True,
    ).strip()
    assert out == "False"


# ---------------------------------------------------------------------------
# F.4 — SystemMapNodeReactivity
# ---------------------------------------------------------------------------
#
# Spike §4 caveat 5: the polling implementation flushed all dirty nodes per
# batch; this Reactivity flushes one node per fire in priority order. The
# canonical regression test for that behavioural drift is
# ``test_system_map_flush_one_per_fire_drift`` below.


def _system_map_chat_entry(
    *,
    text: str,
    sender_person: str,
    channel_id: str = "C-fin",
    message_id: str = "msg-sm-001",
    seq: int = 1,
) -> dict[str, Any]:
    """Build a chat_received execute entry for the system-map Reactivity.
    Mirrors the args shape consumed by ``update_from_chat_entry``: text,
    sender_person, channel_id.
    """
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "emit_chat_received",
            "args": {
                "text": text,
                "sender_person": sender_person,
                "channel_id": channel_id,
                "message_id": message_id,
                "ts": "2026-04-28T12:00:00+00:00",
            },
        },
    }


@pytest.mark.asyncio
async def test_system_map_first_chat_emits_one_node() -> None:
    """First chat dirties sender + channel; one fire emits one node."""
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    sender = "person-A"
    entry = _system_map_chat_entry(
        text="@bob ship the deploy", sender_person=sender, channel_id="C-eng",
    )
    result = await react.fire(entry, ctx)

    assert result.fired is True
    assert result.actions and result.actions[0].action_kind == "system_map_node"
    assert result.budget_used == {"per_tenant": 1}

    rows = await _entries_for(ledger, company_id)
    kinds = [r.get("kind") for r in rows]
    # One PEVR cycle.
    assert kinds.count("propose") == 1
    assert kinds.count("execute") == 1
    assert kinds.count("verify") == 1
    assert kinds.count("resolve") == 1

    # Validate the execute payload round-trips via the ledger schema.
    from wormbase_ledger.entries import SystemMapNodePayload
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    SystemMapNodePayload.model_validate(execute_row["payload"]["args"])


@pytest.mark.asyncio
async def test_system_map_drained_then_no_new_traffic_no_fire() -> None:
    """After the dirty set drains and no new chat traffic re-dirties any
    node, the next fire returns ``fired=False``.

    This is the spec's "second chat from the same actor … fire returns
    fired=False" semantic, expressed against the actual dirty-set mechanic:
    `update_from_chat_entry` re-dirties on every chat with a non-empty
    text + same actor, so the no-fire condition is reached only when
    fire() runs on an empty-text update (no new dirtying) AND the dirty
    set is already drained.
    """
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    sender = "person-A"
    # Fire 1: dirties sender + channel; emits whichever has higher priority.
    entry1 = _system_map_chat_entry(
        text="@bob ack me", sender_person=sender, channel_id="C-fin",
        message_id="msg-1", seq=1,
    )
    res1 = await react.fire(entry1, ctx)
    assert res1.fired is True

    # Fire 2: empty-text update, no new dirtying. The OTHER dirty node
    # (the one not flushed in fire 1) drains.
    entry_empty_a = _system_map_chat_entry(
        text="", sender_person="x", channel_id="x",
        message_id="msg-2", seq=2,
    )
    res2 = await react.fire(entry_empty_a, ctx)
    assert res2.fired is True
    assert res1.novelty_key != res2.novelty_key

    # Fire 3: another empty-text update — dirty set already drained,
    # nothing to flush. fired=False.
    entry_empty_b = _system_map_chat_entry(
        text="", sender_person="x", channel_id="x",
        message_id="msg-3", seq=3,
    )
    res3 = await react.fire(entry_empty_b, ctx)
    assert res3.fired is False

    # Direct accumulator inspection confirms.
    from wormbase_process_extractor.system_map import get_tenant_accumulator
    acc = get_tenant_accumulator(company_id)
    assert acc.dirty_nodes == set()


@pytest.mark.asyncio
async def test_system_map_cross_actor_mention_two_dirty_nodes() -> None:
    """A mentions B in a chat → A is dirty (the mention is an outbound edge
    from A). Two consecutive fires drain the dirty set in priority order.
    """
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    # A mentions B in C-ops (deploy keyword → eng domain hint).
    entry = _system_map_chat_entry(
        text="@bob can you help with the deploy",
        sender_person="person-A",
        channel_id="C-ops",
        seq=1,
    )
    # First fire: dirties A and C-ops; emits highest-priority.
    res1 = await react.fire(entry, ctx)
    assert res1.fired is True
    first_node_id = res1.novelty_key.split(":", 1)[1]

    # Second fire: empty chat, but the OTHER dirty node from fire 1 is
    # still pending. Pass an empty-text chat: update is a no-op, but the
    # pre-existing dirty node still flushes.
    entry_empty = _system_map_chat_entry(
        text="",
        sender_person="person-X",
        channel_id="C-X",
        seq=2,
    )
    res2 = await react.fire(entry_empty, ctx)
    assert res2.fired is True
    second_node_id = res2.novelty_key.split(":", 1)[1]
    assert first_node_id != second_node_id
    assert {first_node_id, second_node_id} == {"person-A", "C-ops"}


@pytest.mark.asyncio
async def test_system_map_channel_node_emitted() -> None:
    """The channel itself becomes a ``channel`` node on first traffic;
    fire emits one node per fire — the channel is one of the two emitted.
    """
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    entry = _system_map_chat_entry(
        text="closing the q3 invoice",
        sender_person="person-A",
        channel_id="C-finance",
        seq=1,
    )
    # First fire: emits one node.
    res1 = await react.fire(entry, ctx)
    assert res1.fired is True
    # Second fire (no-op update): emits the other dirty node.
    res2 = await react.fire(
        _system_map_chat_entry(
            text="", sender_person="x", channel_id="x", seq=2,
        ),
        ctx,
    )
    assert res2.fired is True

    # Inspect the two execute rows: one must be node_kind=channel.
    rows = await _entries_for(ledger, company_id)
    execute_args = [
        r["payload"]["args"]
        for r in rows
        if r.get("kind") == "execute"
    ]
    node_kinds = {a["node_kind"] for a in execute_args}
    assert "channel" in node_kinds
    # The channel node id must appear.
    channel_args = next(a for a in execute_args if a["node_kind"] == "channel")
    assert channel_args["node_id"] == "C-finance"


@pytest.mark.asyncio
async def test_system_map_multi_tenant_isolation() -> None:
    """Tenants T1 and T2 have independent accumulators; firing in T1 does
    not affect T2's flush behaviour.
    """
    t1 = uuid4()
    t2 = uuid4()
    _reset_tenant_accumulator(t1)
    _reset_tenant_accumulator(t2)

    react = SystemMapNodeReactivity()
    ledger_1 = InMemoryLedger()
    ledger_2 = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx_1 = _make_real_context(
        ledger=ledger_1,
        company_id=t1,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )
    _, ctx_2 = _make_real_context(
        ledger=ledger_2,
        company_id=t2,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    # Fire twice in T1 to drain its dirty set.
    entry_t1 = _system_map_chat_entry(
        text="@bob deploy", sender_person="person-T1", channel_id="C-t1",
        seq=1,
    )
    await react.fire(entry_t1, ctx_1)
    await react.fire(
        _system_map_chat_entry(
            text="", sender_person="x", channel_id="x", seq=2,
        ),
        ctx_1,
    )

    # T2 accumulator must still be untouched. A first-time fire in T2 must
    # succeed exactly like T1's first fire did.
    from wormbase_process_extractor.system_map import get_tenant_accumulator
    acc_t1 = get_tenant_accumulator(t1)
    acc_t2 = get_tenant_accumulator(t2)
    assert acc_t1 is not acc_t2
    assert len(acc_t2.person_to_channel) == 0
    assert len(acc_t2.dirty_nodes) == 0

    entry_t2 = _system_map_chat_entry(
        text="@alice ship it",
        sender_person="person-T2",
        channel_id="C-t2",
        seq=1,
    )
    res_t2 = await react.fire(entry_t2, ctx_2)
    assert res_t2.fired is True

    # T1's ledger has 2 PEVR cycles; T2's has 1.
    rows_t1 = await _entries_for(ledger_1, t1)
    rows_t2 = await _entries_for(ledger_2, t2)
    assert sum(1 for r in rows_t1 if r.get("kind") == "execute") == 2
    assert sum(1 for r in rows_t2 if r.get("kind") == "execute") == 1


@pytest.mark.asyncio
async def test_system_map_budget_exhaustion_blocks_third_fire() -> None:
    """With ``per_tenant_budget=2``, the third fire of the day for the same
    tenant returns ``fired=False`` (DailyBudget blocks); resets next day.
    """
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity(per_tenant_budget=2)
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    registry, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    # Pre-populate the per-tenant counter to exactly the cap (2).
    day = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id=SystemMapNodeReactivity.id,
        axis="tenant",
        key=str(company_id),
        day=day,
        by=2,
    )

    # 3rd fire blocked by condition.
    entry = _system_map_chat_entry(
        text="@bob deploy", sender_person="person-A", channel_id="C-eng",
        seq=1,
    )
    assert await react.condition.allows(entry, ctx) is False

    # Roll the clock forward one day; counter no longer matches today's
    # window — allowed again.
    state["now"] = state["now"] + timedelta(days=1)
    assert await react.condition.allows(entry, ctx) is True


@pytest.mark.asyncio
async def test_system_map_flush_one_per_fire_drift() -> None:
    """Behavioural-drift assertion (spike §4 caveat 5).

    The polling-loop implementation flushed all dirty nodes per batch
    (one PEVR cycle per node, all in a tight loop). The Reactivity model
    emits **one** node per fire. This test is the canonical regression
    test for that cadence drift: 5 chats producing 7 dirty nodes →
    7 sequential fires emit 7 distinct ``system_map_node`` entries
    (NOT one batch of 7 in one fire).

    Cited: docs/superpowers/plans/2026-05-03-process-worm-extraction.md
    §F.4 acceptance bullets.
    """
    company_id = uuid4()
    _reset_tenant_accumulator(company_id)

    react = SystemMapNodeReactivity()
    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    _, ctx = _make_real_context(
        ledger=ledger,
        company_id=company_id,
        state=state,
        reactivity_id=SystemMapNodeReactivity.id,
    )

    # 5 chats across 4 distinct senders and 3 distinct channels.
    # senders {S1,S2,S3,S4} + channels {C-eng,C-fin,C-ops} = 7 dirty nodes.
    chats = [
        ("@bob deploy now", "S1", "C-eng", "m1"),
        ("@alice close the q3", "S2", "C-fin", "m2"),
        ("on-call ack", "S3", "C-ops", "m3"),
        ("@carol invoice review", "S4", "C-fin", "m4"),
        ("rollback the build", "S1", "C-eng", "m5"),
    ]

    # First fire: includes one update — emits one node. Then 6 more fires
    # with empty-text updates drain the remaining dirty set.
    for i, (text, sender, channel, mid) in enumerate(chats):
        entry = _system_map_chat_entry(
            text=text, sender_person=sender, channel_id=channel,
            message_id=mid, seq=i + 1,
        )
        # Apply the update directly to the accumulator so all 5 chats
        # contribute before we start counting flushes.
        from wormbase_process_extractor.system_map import (
            get_tenant_accumulator,
            update_from_chat_entry,
        )
        acc = get_tenant_accumulator(company_id)
        update_from_chat_entry(entry["payload"]["args"], accumulator=acc)

    # Confirm there are exactly 7 dirty nodes.
    acc = get_tenant_accumulator(company_id)
    assert len(acc.dirty_nodes) == 7

    # Now fire 7 times with empty-text payloads (no further updates). Each
    # fire must emit ONE node — the cadence drift test.
    emitted: list[str] = []
    for i in range(7):
        entry = _system_map_chat_entry(
            text="", sender_person="x", channel_id="x",
            message_id=f"flush-{i}", seq=100 + i,
        )
        res = await react.fire(entry, ctx)
        assert res.fired is True, f"Fire {i+1} unexpectedly returned fired=False"
        emitted.append(res.novelty_key.split(":", 1)[1])

    # 7 fires → 7 distinct system_map_node entries.
    rows = await _entries_for(ledger, company_id)
    execute_count = sum(1 for r in rows if r.get("kind") == "execute")
    assert execute_count == 7
    # All 7 emitted node ids are distinct.
    assert len(set(emitted)) == 7
    # Specifically: 4 senders + 3 channels = 7.
    assert set(emitted) == {"S1", "S2", "S3", "S4", "C-eng", "C-fin", "C-ops"}

    # 8th fire returns fired=False (dirty set drained, no new updates).
    entry = _system_map_chat_entry(
        text="", sender_person="x", channel_id="x",
        message_id="flush-final", seq=200,
    )
    res = await react.fire(entry, ctx)
    assert res.fired is False


def test_system_map_reactivity_uses_only_w5a_primitives() -> None:
    """The Reactivity must use only existing W5a primitives — no new
    predicate/condition introduced (MatchesDecisionPattern is reused by
    F.3 only). Predicate is plain EntryKind; condition is DailyBudget &
    DomainEnabled.
    """
    from wormbase_reactivities.conditions import DailyBudget, DomainEnabled
    from wormbase_reactivities.predicates import EntryKind

    react = SystemMapNodeReactivity()
    # Predicate is exactly EntryKind("chat_received") — no & / | clauses.
    assert isinstance(react.predicate, EntryKind)
    assert react.predicate.kind == "chat_received"

    # Condition is a composite of DailyBudget & DomainEnabled. Walk the And
    # tree to confirm both are present and no other primitives sneaked in.
    seen_types: set[type] = set()

    def _walk(c: Any) -> None:
        # AndCondition exposes ``conditions``; primitives are leaves.
        if hasattr(c, "conditions"):
            for sub in c.conditions:
                _walk(sub)
        else:
            seen_types.add(type(c))

    _walk(react.condition)
    assert DailyBudget in seen_types
    assert DomainEnabled in seen_types
    # NotRecentlyFired must NOT be present (per spec).
    from wormbase_reactivities.conditions import NotRecentlyFired
    assert NotRecentlyFired not in seen_types


def test_system_map_reactivity_exported_from_package() -> None:
    """The Reactivity must be importable from the package surface."""
    from wormbase_process_extractor import SystemMapNodeReactivity as PkgAlias
    assert PkgAlias is SystemMapNodeReactivity


# ---------------------------------------------------------------------------
# Phase 2 Task 2B — TopicSynthesisReactivity real implementation
#
# Promotes the F.1 stub to a real implementation. Fire writes a
# ``topic_proposed`` PEVR cycle when a chat-text cluster crosses the
# topic-promotion threshold; uses the inference router (``call_type=
# "summarize"``, default Gemma) to label the cluster topic, with a
# heuristic fallback when the router is unwired or fails.
# ---------------------------------------------------------------------------


class _StubTopicLabeler:
    """Test stand-in for the topic-labeling adapter.

    Mirrors the canonical Protocol shape (``async def label_topic(*,
    cluster_signature, sample_messages, member_message_ids) -> tuple[str,
    float, str] | None``). The Reactivity injects a real adapter via
    ``ReactivityContext.extras[_TOPIC_LABELER_EXTRAS_KEY]`` in
    production.
    """

    def __init__(
        self,
        *,
        label: str | None = "Q3 finance reporting cadence",
        confidence: float = 0.82,
        served_by: str = "gemma",
        raise_on_call: bool = False,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.served_by = served_by
        self.raise_on_call = raise_on_call
        self.calls: list[dict[str, Any]] = []

    async def label_topic(
        self,
        *,
        cluster_signature: str,
        sample_messages: list[str],
        member_message_ids: list[str],
    ) -> tuple[str, float, str] | None:
        self.calls.append(
            {
                "cluster_signature": cluster_signature,
                "sample_messages": list(sample_messages),
                "member_message_ids": list(member_message_ids),
            }
        )
        if self.raise_on_call:
            raise RuntimeError("router blew up")
        if self.label is None:
            return None
        return (self.label, self.confidence, self.served_by)


def _topic_chat_entry(
    *,
    text: str = "q3 finance reporting cadence weekly",
    message_id: str = "M-T-001",
    channel_id: str = "C-T",
    ts: str = "2026-05-03T10:00:00+00:00",
    sender_person: str | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    """chat_received execute entry tailored for topic-synthesis tests."""
    args: dict[str, Any] = {
        "text": text,
        "message_id": message_id,
        "channel_id": channel_id,
        "ts": ts,
    }
    if sender_person is not None:
        args["sender_person"] = sender_person
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {"tool": "emit_chat_received", "args": args},
    }


def _make_topic_context(
    *,
    ledger: InMemoryLedger,
    company_id: UUID,
    state: dict[str, datetime],
    labeler: _StubTopicLabeler | None = None,
) -> tuple[ReactivityRegistry, ReactivityContext]:
    """ReactivityContext backed by a real registry — needed for budget
    accounting on the topic_synthesis Reactivity."""
    from wormbase_process_extractor.reactivities import (
        TopicSynthesisReactivity,
    )

    def _now() -> datetime:
        return state["now"]

    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now,
    )
    extras: dict[str, Any] = {"reactivity_id": TopicSynthesisReactivity.id}
    if labeler is not None:
        # Convention key — mirrors decisions.py's ``_LLM_EXTRAS_KEY``.
        extras["topic_labeler"] = labeler
    return registry, ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=_now,
        extras=extras,
    )


@pytest.mark.asyncio
async def test_topic_synthesis_fire_below_threshold_no_writes() -> None:
    """First chat in a novel cluster — no PEVR cycle written."""
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state,
    )
    entry = _topic_chat_entry(text="q3 finance reporting cadence")

    result = await react.fire(entry, ctx)
    assert result.fired is False
    rows = list(await ledger.fetch(company_id))
    assert rows == []


@pytest.mark.asyncio
async def test_topic_synthesis_fire_at_threshold_writes_pevr() -> None:
    """Two similar chats cross the threshold; fire writes the PEVR cycle."""
    from wormbase_ledger.entries import TopicProposedPayload
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    labeler = _StubTopicLabeler(
        label="Q3 finance reporting", confidence=0.82, served_by="gemma",
    )
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state, labeler=labeler,
    )

    # First fire — cluster_size=1, below threshold, no writes.
    first = _topic_chat_entry(
        text="q3 finance reporting cadence weekly", message_id="M-001",
    )
    res1 = await react.fire(first, ctx)
    assert res1.fired is False

    # Second fire — cluster_size=2, threshold crossed, full PEVR cycle.
    second = _topic_chat_entry(
        text="q3 finance reporting cadence",
        message_id="M-002",
        ts="2026-05-03T10:05:00+00:00",
    )
    res2 = await react.fire(second, ctx)

    assert res2.fired is True
    assert res2.actions
    assert res2.actions[0].action_kind == "topic_proposed"
    assert res2.budget_used == {"per_tenant": 1}

    rows = list(await ledger.fetch(company_id))
    kinds = [row.get("kind") for row in rows]
    assert kinds.count("propose") == 1
    assert kinds.count("execute") == 1
    assert kinds.count("verify") == 1
    assert kinds.count("resolve") == 1

    # Execute payload validates against the canonical TopicProposedPayload.
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    payload = TopicProposedPayload.model_validate(
        execute_row["payload"]["args"],
    )
    assert payload.label == "Q3 finance reporting"
    assert payload.cluster_size == 2
    assert payload.served_by == "gemma"
    assert payload.confidence == 0.82
    # Member message ids preserved in insertion order.
    assert payload.member_message_ids == ["M-001", "M-002"]


@pytest.mark.asyncio
async def test_topic_synthesis_heuristic_fallback_no_router() -> None:
    """No labeler in extras → heuristic label, served_by="heuristic"."""
    from wormbase_ledger.entries import TopicProposedPayload
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state, labeler=None,
    )

    # Cross threshold without a labeler.
    await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting cadence weekly", message_id="M-001",
        ),
        ctx,
    )
    res = await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting cadence",
            message_id="M-002",
            ts="2026-05-03T10:05:00+00:00",
        ),
        ctx,
    )

    assert res.fired is True
    rows = list(await ledger.fetch(company_id))
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    payload = TopicProposedPayload.model_validate(
        execute_row["payload"]["args"],
    )
    assert payload.served_by == "heuristic"
    # Heuristic confidence is the conservative floor (0.5).
    assert payload.confidence == 0.5
    # Heuristic label is derived from the cluster signature itself —
    # readable but unblessed.
    assert payload.label  # non-empty
    assert "q3 finance" in payload.label.lower()


@pytest.mark.asyncio
async def test_topic_synthesis_router_failure_falls_back() -> None:
    """If the labeler raises, fire still emits via the heuristic path."""
    from wormbase_ledger.entries import TopicProposedPayload
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    labeler = _StubTopicLabeler(raise_on_call=True)
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state, labeler=labeler,
    )
    await react.fire(
        _topic_chat_entry(text="q3 finance reporting", message_id="M-1"), ctx,
    )
    res = await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting",
            message_id="M-2",
            ts="2026-05-03T10:05:00+00:00",
        ),
        ctx,
    )
    assert res.fired is True

    rows = list(await ledger.fetch(company_id))
    execute_row = next(r for r in rows if r.get("kind") == "execute")
    payload = TopicProposedPayload.model_validate(
        execute_row["payload"]["args"],
    )
    # Router raised → adapter returned None → heuristic fallback.
    assert payload.served_by == "heuristic"


@pytest.mark.asyncio
async def test_topic_synthesis_re_emit_on_growing_cluster() -> None:
    """Each new distinct member of an already-emitted cluster re-emits.

    The projection layer keys on topic_id (uuid5 over the canonical
    signature), so re-emit is idempotent — but the cluster_size and
    last_seen_at fields advance.
    """
    from wormbase_ledger.entries import TopicProposedPayload
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    labeler = _StubTopicLabeler(
        label="Q3 finance reporting", confidence=0.82, served_by="gemma",
    )
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state, labeler=labeler,
    )

    # Three distinct chats in the same cluster — first writes nothing
    # (cluster_size=1), second emits (size=2), third re-emits (size=3).
    await react.fire(
        _topic_chat_entry(text="q3 finance reporting", message_id="M-1"), ctx,
    )
    res2 = await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting",
            message_id="M-2",
            ts="2026-05-03T10:05:00+00:00",
        ),
        ctx,
    )
    res3 = await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting cadence",
            message_id="M-3",
            ts="2026-05-03T10:10:00+00:00",
        ),
        ctx,
    )

    assert res2.fired is True
    assert res3.fired is True

    # Two emits → two execute rows, same target_kind, same topic_id.
    rows = list(await ledger.fetch(company_id))
    executes = [r for r in rows if r.get("kind") == "execute"]
    assert len(executes) == 2

    payload2 = TopicProposedPayload.model_validate(executes[0]["payload"]["args"])
    payload3 = TopicProposedPayload.model_validate(executes[1]["payload"]["args"])
    assert payload2.topic_id == payload3.topic_id
    assert payload2.cluster_size == 2
    assert payload3.cluster_size == 3


@pytest.mark.asyncio
async def test_topic_synthesis_idempotent_on_replay_of_same_message() -> None:
    """Re-firing the same chat (same message_id) is a no-op on the cluster.

    Required for deterministic build-from-ledger: a replay must
    converge to the same cluster_size as the live fold.
    """
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    company_id = uuid4()
    _reset_tenant_topic_store(company_id)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    _, ctx = _make_topic_context(
        ledger=ledger, company_id=company_id, state=state,
    )

    entry = _topic_chat_entry(text="q3 finance reporting", message_id="M-1")
    res1 = await react.fire(entry, ctx)
    res2 = await react.fire(entry, ctx)

    assert res1.fired is False
    assert res2.fired is False
    # Cluster still has one distinct member; no PEVR writes either time.
    rows = list(await ledger.fetch(company_id))
    assert rows == []


@pytest.mark.asyncio
async def test_topic_synthesis_per_tenant_isolation() -> None:
    """Cluster state in tenant A doesn't carry into tenant B's fire."""
    from wormbase_process_extractor.topics import _reset_tenant_topic_store

    react = TopicSynthesisReactivity()
    tenant_a = uuid4()
    tenant_b = uuid4()
    _reset_tenant_topic_store(tenant_a)
    _reset_tenant_topic_store(tenant_b)

    ledger = InMemoryLedger()
    state = {"now": datetime(2026, 5, 3, 10, 0, tzinfo=UTC)}
    _, ctx_a = _make_topic_context(
        ledger=ledger, company_id=tenant_a, state=state,
    )
    _, ctx_b = _make_topic_context(
        ledger=ledger, company_id=tenant_b, state=state,
    )

    # Tenant A: two messages cross threshold.
    await react.fire(
        _topic_chat_entry(text="q3 finance reporting", message_id="M-A1"),
        ctx_a,
    )
    res_a2 = await react.fire(
        _topic_chat_entry(
            text="q3 finance reporting",
            message_id="M-A2",
            ts="2026-05-03T10:05:00+00:00",
        ),
        ctx_a,
    )
    assert res_a2.fired is True

    # Tenant B: a single similar message — must NOT cross threshold,
    # because tenant B's cluster store starts empty.
    res_b1 = await react.fire(
        _topic_chat_entry(text="q3 finance reporting", message_id="M-B1"),
        ctx_b,
    )
    assert res_b1.fired is False


def test_topic_synthesis_reactivity_exported_from_package() -> None:
    """The Reactivity must be importable from the package surface."""
    from wormbase_process_extractor import TopicSynthesisReactivity as PkgAlias
    assert PkgAlias is TopicSynthesisReactivity
