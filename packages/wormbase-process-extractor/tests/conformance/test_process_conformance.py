"""End-to-end conformance: chat_received → process-worm Reactivities → ledger.

Tasks **I.1** and **I.2** of the process-worm extraction plan
(``docs/superpowers/plans/2026-05-03-process-worm-extraction.md``,
lines 1473-1593).

The first composition tests for the W5a → process-worm wire. Drives the
full chain purely through the ledger:

  1. Seed a ``chat_received`` entry — message text + sender + channel
     match the production channel-adapter envelope shape byte-for-byte.
  2. Dispatch that entry through ``registry.dispatch(entry)`` (the W5a
     dispatch API — same call ``ReactivityRunner.run_once`` makes).
  3. The matching Reactivity fires and emits a canonical PEVR cycle
     (propose → execute → verify → resolve) ending in a domain-specific
     execute payload (``emit_decision_recorded``,
     ``emit_system_map_node``, or ``emit_data_product_proposed``).

The tests contain zero direct calls to Reactivity-internal helpers
(``synthesize_decision``, ``flush_one_node``, ``_emit_pevr``,
``_get_tenant_history``). They only seed the ledger fixture and dispatch
through the registry — same code path as production
``ReactivityRunner``.

Reference patterns:

  * ``packages/wormbase-research-loop/tests/integration/test_gap_to_cycle.py``
    — Wave C₁'s analogue: chat_received → research-loop trigger → PEVR.
  * ``packages/wormbase-identity-tracker/tests/conformance/test_identity_resolver_conformance.py``
    — narrower conformance pattern (Protocol satisfaction); these tests
    exercise the wire end-to-end.
  * ``packages/wormbase-process-extractor/tests/test_reactivities.py``
    — unit-level analogues; conformance asserts the same shape but
    end-to-end through ``registry.dispatch``.
  * ``tests/integration/test_process_map_e2e.py`` — the broader P10 e2e
    test (P10 in isolation, no factory wiring). Block I.2 §1066-1072
    asserts P10 still works through the new factory wiring; this
    conformance suite is the load-bearing regression test for that.

Stepping model: the happy-path and negative tests drive
``registry.dispatch`` directly on the seeded chat entry, mirroring
what ``ReactivityRunner.run_once`` does for one new row. The cascade
exercised here is one step deep (chat → {decision_recorded,
system_map_node, data_product_proposed}), so direct dispatch is the
simpler and stricter assertion path. The idempotency test, by contrast,
uses ``ReactivityRunner`` end-to-end because the production "same chat
seen twice" idempotency boundary IS the runner's seq cursor —
exercising it through dispatch would test fiction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_process_extractor import wire_process_for_install
from wormbase_reactivities.registry import ReactivityRegistry


# Stable identifiers so the run is hash-stable across replays.
COMPANY = UUID("00000000-0000-0000-0000-00000000ca0e")
ALICE = UUID("00000000-0000-0000-0000-0000000000a1")
BOB = UUID("00000000-0000-0000-0000-0000000000b0")
CAROL = UUID("00000000-0000-0000-0000-0000000000c0")
NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Per-test isolation of module-level state
# ---------------------------------------------------------------------------
#
# Two process-worm Reactivities keep state in module-level dicts keyed by
# ``company_id``: SystemMapNodeReactivity (``_TENANT_ACCUMULATORS`` in
# ``system_map.py``) and the P10 alias RecurringQuestionReactivity
# (``_TENANT_HISTORIES`` in ``process_mapper.py``). Conformance tests share
# the same ``COMPANY`` UUID, so we reset both before AND after each test
# to ensure isolation even when a test crashes mid-run. The pattern mirrors
# ``packages/reactivities/tests/test_process_mapper_reactivity.py``'s
# ``_isolate_history`` fixture.


@pytest.fixture(autouse=True)
def _isolate_module_state() -> Any:
    """Reset module-level per-tenant state for every conformance test."""
    from wormbase_process_extractor.system_map import (
        _reset_tenant_accumulator,
    )
    from wormbase_reactivities.process_mapper import _reset_history

    _reset_tenant_accumulator(COMPANY)
    _reset_history(COMPANY)
    yield
    _reset_tenant_accumulator(COMPANY)
    _reset_history(COMPANY)


# ---------------------------------------------------------------------------
# Helpers — ledger seed only; no direct calls to process-worm internals.
# ---------------------------------------------------------------------------


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    text: str,
    message_id: str = "msg-001",
    channel_id: str = "C-eng",
    sender_person: UUID = ALICE,
) -> dict[str, Any]:
    """Seed one ``chat_received`` PEVR cycle and return the execute row.

    Mirrors what ``channel_adapter`` writes when a wire event lands —
    the ledger entries are byte-identical to production output. The
    returned dict is the ``execute`` row we feed into
    ``registry.dispatch`` to exercise the W5a → process-worm composition.
    """
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test inbound message",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "channel_id": channel_id,
                "message_id": message_id,
                "text": text,
                "sender_person": str(sender_person),
                "ts": NOW.isoformat(),
            },
            "result_ref": message_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=NOW,
        quadrant="active_probabilistic",
    )
    rows = await ledger.fetch(company_id)
    return next(r for r in reversed(rows) if r.get("kind") == "execute")


def _execute_rows(
    rows: list[dict[str, Any]], tool: str,
) -> list[dict[str, Any]]:
    """Filter execute envelopes whose payload.tool matches exactly."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == tool:
            out.append(r)
    return out


def _decision_record_pevr_quad(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the propose/execute/verify/resolve quad for the
    ``decision_recorded`` cycle, sorted by seq.

    Multiple Reactivities fire on the seed ``chat_received``
    (DecisionRecord and SystemMapNode in particular), so the ledger
    is interleaved post-fire. Identify the decision_recorded PEVR
    by:

      1. Find the ``execute`` row whose ``payload.tool ==
         "emit_decision_recorded"``.
      2. Walk back: its ``propose_entry_id`` points at the propose row.
      3. Walk forward: find the ``verify`` row whose
         ``execute_entry_id`` matches the execute's ``entry_id``.
      4. Walk forward: find the ``resolve`` row whose
         ``verify_entry_id`` matches the verify's ``entry_id``.

    This is the canonical "follow the *_entry_id chain" pattern the
    PEVR cycle exposes — robust against interleaving from any number
    of co-firing Reactivities.
    """
    execute_row = next(
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_decision_recorded"
    )
    propose_entry_id = execute_row["payload"]["propose_entry_id"]
    propose_row = next(
        r for r in rows
        if r.get("kind") == "propose"
        and str(r.get("entry_id")) == propose_entry_id
    )
    verify_row = next(
        r for r in rows
        if r.get("kind") == "verify"
        and (r.get("payload") or {}).get("execute_entry_id") == str(
            execute_row.get("entry_id"),
        )
    )
    resolve_row = next(
        r for r in rows
        if r.get("kind") == "resolve"
        and (r.get("payload") or {}).get("verify_entry_id") == str(
            verify_row.get("entry_id"),
        )
    )
    return sorted(
        [propose_row, execute_row, verify_row, resolve_row],
        key=lambda r: int(r.get("seq", 0)),
    )


# ---------------------------------------------------------------------------
# The conformance test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_record_e2e() -> None:
    """chat_received with decision-language → decision_recorded PEVR cycle.

    Composition assertion: process-worm sees the chat_received entry
    only through ``registry.dispatch`` — no direct call into
    ``DecisionRecordReactivity.fire`` from the test or the wire.
    """
    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731 -- intentional one-liner

    # Fresh ReactivityRegistry. The factory wires the four process-worm
    # Reactivities (TopicSynthesis stub, RecurringQuestion alias,
    # DecisionRecord, SystemMapNode); only DecisionRecord is exercised
    # here because MatchesDecisionPattern is the discriminator.
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    ids = wire_process_for_install(registry=registry, llm_client=None)
    assert "decision_record" in ids, (
        f"wire_process_for_install must register decision_record; "
        f"got ids={ids!r}"
    )

    # 1. Seed a chat_received with decision-language signal. The text
    # matches ``_DECISION_PATTERNS`` regex #1 ("we decided to ...").
    decision_text = "We decided to go with Snowflake for the Q3 lake."
    seed_row = await _seed_chat_received(
        ledger,
        COMPANY,
        text=decision_text,
        message_id="msg-decision-001",
        channel_id="C-data-eng",
    )
    seed_seq = int(seed_row["seq"])

    # 2. Dispatch the seed chat_received row through W5a. Only
    # DecisionRecordReactivity should fire on this entry —
    # MatchesDecisionPattern is a discriminator the other three
    # process-worm Reactivities don't carry. SystemMapNodeReactivity
    # ALSO fires on chat_received (its predicate is bare
    # EntryKind("chat_received")), so we expect both ids in fired_ids.
    fired = await registry.dispatch(seed_row)
    assert "decision_record" in fired, (
        f"expected DecisionRecordReactivity to fire on the seeded "
        f"chat_received with decision-language; got fired_ids={fired!r}"
    )

    # 3. The ledger has a new ``decision_recorded`` execute entry.
    rows = await ledger.fetch(COMPANY)
    decision_rows = _execute_rows(rows, "emit_decision_recorded")
    assert len(decision_rows) == 1, (
        f"expected exactly one emit_decision_recorded execute entry "
        f"after dispatch; got {len(decision_rows)}"
    )
    decision_args = decision_rows[0]["payload"]["args"]

    # 4. The execute payload validates against the ledger schema —
    # the contract between process-worm's DecisionPayload and the
    # ledger's DecisionRecordedPayload.
    from wormbase_ledger.entries import DecisionRecordedPayload
    decision_payload = DecisionRecordedPayload.model_validate(decision_args)

    # 5. Field-level assertions on the emitted payload.
    #   * decision_text is non-empty and contains the decision-language
    #     clause (the regex match plus padding).
    assert decision_payload.decision_text, (
        "decision_text must be non-empty"
    )
    assert "decided" in decision_payload.decision_text.lower(), (
        f"decision_text should carry the decision-language clause; "
        f"got {decision_payload.decision_text!r}"
    )

    #   * channel_id matches the source chat's channel_id.
    assert decision_payload.channel_id == "C-data-eng", (
        f"channel_id mismatch; expected 'C-data-eng', got "
        f"{decision_payload.channel_id!r}"
    )

    #   * decided_by_persons includes the chat sender.
    assert ALICE in decision_payload.decided_by_persons, (
        f"decided_by_persons must include the chat sender ({ALICE}); "
        f"got {decision_payload.decided_by_persons!r}"
    )

    #   * evidence_message_ids includes the source chat's message_id.
    assert "msg-decision-001" in decision_payload.evidence_message_ids, (
        f"evidence_message_ids must include the source message_id; "
        f"got {decision_payload.evidence_message_ids!r}"
    )

    # 6. The PEVR cycle is well-formed: propose, execute, verify, resolve
    # entries are all present, chained by the *_entry_id refs the ledger
    # writer threads through, and seq-ordered as P < E < V < R. We isolate
    # the decision_record PEVR by following the *_entry_id chain rather
    # than by seq window — multiple Reactivities co-fire on chat_received
    # (SystemMapNode in particular) so seq-windowing would mix cycles.
    quad = _decision_record_pevr_quad(rows)
    pevr_kinds = [r.get("kind") for r in quad]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"], (
        f"expected canonical PEVR seq-order "
        f"propose/execute/verify/resolve for the decision_recorded "
        f"cycle; got {pevr_kinds!r} (seed_seq={seed_seq})"
    )

    # ref_id chaining: the propose's ref_id is the decision_id (string);
    # each subsequent entry threads the prior entry_id via
    # propose_entry_id / execute_entry_id / verify_entry_id (the
    # InMemoryLedger writer wires this up — see ledger_api.py:161-172).
    propose_row, execute_row, verify_row, resolve_row = quad
    assert propose_row["payload"]["target_kind"] == "decision_recorded"
    propose_ref_id = propose_row["payload"]["ref_id"]
    # The execute's result_ref equals the propose's ref_id (the
    # decision_id) — the canonical "what was just persisted" pointer.
    assert execute_row["payload"]["result_ref"] == propose_ref_id, (
        f"execute.result_ref must match propose.ref_id "
        f"({propose_ref_id!r}); got {execute_row['payload']['result_ref']!r}"
    )
    # The four entries are linked by the ledger writer's *_entry_id chain:
    # execute → propose, verify → execute, resolve → verify.
    assert execute_row["payload"]["propose_entry_id"] == str(
        propose_row["entry_id"],
    )
    assert verify_row["payload"]["execute_entry_id"] == str(
        execute_row["entry_id"],
    )
    assert resolve_row["payload"]["verify_entry_id"] == str(
        verify_row["entry_id"],
    )


@pytest.mark.asyncio
async def test_decision_record_e2e_negative_no_decision_text() -> None:
    """chat_received with non-decision text fires nothing.

    The MatchesDecisionPattern predicate guards the fire path; without
    a regex hit no decision_recorded entry lands.
    """
    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    wire_process_for_install(registry=registry, llm_client=None)

    seed_row = await _seed_chat_received(
        ledger,
        COMPANY,
        text="What's for lunch?",
        message_id="msg-no-decision",
    )
    fired = await registry.dispatch(seed_row)

    # decision_record must not appear. (system_map_node may fire — bare
    # EntryKind("chat_received") predicate, no decision-language guard;
    # that's a separate Reactivity scope and is not the assertion here.)
    assert "decision_record" not in fired, (
        f"DecisionRecordReactivity must NOT fire on non-decision text; "
        f"got fired_ids={fired!r}"
    )
    rows = await ledger.fetch(COMPANY)
    decision_rows = _execute_rows(rows, "emit_decision_recorded")
    assert decision_rows == [], (
        f"expected zero emit_decision_recorded entries on non-decision "
        f"text; got {len(decision_rows)} ({decision_rows!r})"
    )


@pytest.mark.asyncio
async def test_decision_record_e2e_idempotency_via_runner_cursor() -> None:
    """A second runner pass over an unchanged ledger does not re-fire.

    The production idempotency boundary for "same chat entry seen
    twice" is the runner's cursor (``ReactivityRunner._last_seq``,
    ``runner.py:175-194``): once a chat row is dispatched, the runner
    advances past it and won't re-dispatch on the next ``run_once``
    unless the ledger grows.

    NotRecentlyFired is the Reactivity-internal novelty gate (e.g.
    suppress repeated decision-record emits on different chats with
    overlapping novelty keys); the SAME-entry-twice case is bounded
    by the cursor first. This test asserts the cursor contract
    end-to-end: drive one chat → one decision_recorded; run again →
    zero new entries.
    """
    from wormbase_reactivities.runner import ReactivityRunner

    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    wire_process_for_install(registry=registry, llm_client=None)

    runner = ReactivityRunner(
        ledger=ledger,
        registry=registry,
        company_id=COMPANY,
        poll_interval_s=0.0,
    )

    await _seed_chat_received(
        ledger,
        COMPANY,
        text="We decided to migrate to Snowflake next quarter.",
        message_id="msg-idem-001",
    )

    # First runner pass: dispatches the seeded chat_received; the
    # decision_record Reactivity fires and emits one PEVR cycle.
    fire_total_first = await runner.run_once()
    assert fire_total_first >= 1, (
        f"first run_once must dispatch the seeded chat_received and "
        f"fire at least one Reactivity (decision_record); got "
        f"fire_total={fire_total_first}"
    )

    rows_after_first = await ledger.fetch(COMPANY)
    decision_rows_first = _execute_rows(
        rows_after_first, "emit_decision_recorded",
    )
    assert len(decision_rows_first) == 1, (
        f"expected exactly one emit_decision_recorded after first "
        f"runner pass; got {len(decision_rows_first)}"
    )
    seq_after_first = max(
        int(r.get("seq", 0)) for r in rows_after_first
    )

    # Second runner pass on an unchanged seed: the cursor already moved
    # past the chat_received row, so registry.dispatch is not called for
    # it again. The Reactivities that DO fire mid-cycle (e.g.
    # emit_reactivity_fired bookkeeping) advance the cursor naturally
    # but are themselves re-dispatched — and their predicates don't
    # match emit_reactivity_fired execute envelopes, so no new
    # decision_recorded entry lands.
    fire_total_second = await runner.run_once()
    rows_after_second = await ledger.fetch(COMPANY)
    decision_rows_second = _execute_rows(
        rows_after_second, "emit_decision_recorded",
    )
    assert len(decision_rows_second) == 1, (
        f"expected the decision_recorded count to stay at 1 after a "
        f"second runner pass on the unchanged seed; got "
        f"{len(decision_rows_second)} (fire_total={fire_total_second})"
    )

    # Sanity: the runner's cursor must have advanced past the original
    # seed seq, so the seed isn't sitting in the "new entries" window.
    assert runner.last_seq >= seq_after_first, (
        f"runner cursor must have advanced past the post-first-pass "
        f"max seq; got last_seq={runner.last_seq} "
        f"seq_after_first={seq_after_first}"
    )


# ---------------------------------------------------------------------------
# I.2 — SystemMap + RecurringQuestion: cross-domain mention + repeated question
# ---------------------------------------------------------------------------
#
# Companion to I.1 above. I.1 covers DecisionRecord; this section covers
# the other two chat-driven Reactivities: SystemMapNode (cross-actor
# mention pattern + canonical behavioural-drift assertion vs the polling
# loop) and the P10 alias RecurringQuestionReactivity (triplet recurrence
# → process_map data product). TopicSynthesisReactivity is intentionally
# out of scope — F.1 ships it as a Phase-2 stub (always fired=False).
#
# The W5b composition test (process-worm's RecurringQuestionReactivity
# co-existing with phenomenon_gaps' ProcessReferenceWithoutProcessReactivity)
# is intentionally deferred to ``tests/integration/`` — see
# ``test_w5b_composition_deferred`` below for the rationale and pointer.


# Helpers for I.2: thread-aware chat fixtures (P10 needs InThread) and
# system-map-aware chat fixtures (mention parsing + sender + channel).


async def _seed_threaded_chat(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    text: str,
    message_id: str,
    asker: UUID,
    askee: UUID,
    topic: str,
    channel_id: str = "C-revenue",
    ts_epoch: float = 1777334000.000001,
    thread_ts_epoch: float = 1777334000.000000,
) -> dict[str, Any]:
    """Seed a threaded ``chat_received`` carrying a topic + thread parent.

    Mirrors the args shape ``RecurringQuestionProcessMapperReactivity``
    consumes (see ``packages/reactivities/tests/test_process_mapper_reactivity.py``):

      * ``thread_ts != ts`` to satisfy ``InThread()``
      * ``topic`` to satisfy ``HasTopic()``
      * ``thread_parent_person`` so P10's ``_extract_askee`` resolves
      * ``sender_person`` so P10's ``_extract_asker`` resolves

    Same write path as ``_seed_chat_received`` (above) — uses
    ``ledger.write`` with a real PEVR cycle so the resulting execute row
    is what production channel-adapter would emit.
    """
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test threaded inbound message",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "channel_id": channel_id,
                "message_id": message_id,
                "ts": str(ts_epoch),
                "thread_ts": str(thread_ts_epoch),
                "sender_person": str(asker),
                "thread_parent_person": str(askee),
                "topic": topic,
                "text": text,
            },
            "result_ref": message_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=NOW,
        quadrant="active_probabilistic",
    )
    rows = await ledger.fetch(company_id)
    return next(r for r in reversed(rows) if r.get("kind") == "execute")


def _system_map_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter execute envelopes for the system_map_node tool."""
    return _execute_rows(rows, "emit_system_map_node")


def _process_map_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter execute envelopes for emit_data_product_proposed of
    kind ``process_map`` — P10's only emission."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_data_product_proposed":
            continue
        args = payload.get("args") or {}
        if args.get("kind") == "process_map":
            out.append(r)
    return out


def _system_map_pevr_quad_for(
    rows: list[dict[str, Any]],
    *,
    execute_seq: int,
) -> list[dict[str, Any]]:
    """Like ``_decision_record_pevr_quad`` but for one specific
    system_map_node execute (chosen by seq, since multiple emit per
    test in the drain case)."""
    execute_row = next(
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_system_map_node"
        and int(r.get("seq", 0)) == execute_seq
    )
    propose_entry_id = execute_row["payload"]["propose_entry_id"]
    propose_row = next(
        r for r in rows
        if r.get("kind") == "propose"
        and str(r.get("entry_id")) == propose_entry_id
    )
    verify_row = next(
        r for r in rows
        if r.get("kind") == "verify"
        and (r.get("payload") or {}).get("execute_entry_id") == str(
            execute_row.get("entry_id"),
        )
    )
    resolve_row = next(
        r for r in rows
        if r.get("kind") == "resolve"
        and (r.get("payload") or {}).get("verify_entry_id") == str(
            verify_row.get("entry_id"),
        )
    )
    return sorted(
        [propose_row, execute_row, verify_row, resolve_row],
        key=lambda r: int(r.get("seq", 0)),
    )


# ---------------------------------------------------------------------------
# SystemMap — cross-actor mention fires the Reactivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_map_e2e_cross_actor_mention_fires() -> None:
    """chat_received with cross-actor mention → system_map_node entry.

    Plan I.2 §1531-1540: when actor A mentions actor B in #ops,
    ``SystemMapNodeReactivity`` fires and emits one ``system_map_node``
    entry whose ``node_kind`` is one of {person, channel} and whose
    ``edges`` list is non-empty.

    The accumulator dirties both A (mention sender) and the channel; the
    Reactivity flushes one node per fire — whichever has higher cumulative
    edge weight, ties broken by node-id sort. This test asserts the
    emission shape, not which of the two nodes drains first (that is
    covered by the unit tests in ``test_reactivities.py``).
    """
    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    ids = wire_process_for_install(registry=registry, llm_client=None)
    assert "system_map_node" in ids, (
        f"wire_process_for_install must register system_map_node; "
        f"got ids={ids!r}"
    )

    # Alice mentions Bob in the #ops channel — the deploy keyword pulls
    # the channel→topic edge into the eng domain hint.
    seed_row = await _seed_chat_received(
        ledger,
        COMPANY,
        text="@bob can you ack the deploy when you're free?",
        message_id="msg-mention-001",
        channel_id="C-ops",
        sender_person=ALICE,
    )

    fired = await registry.dispatch(seed_row)
    assert "system_map_node" in fired, (
        f"expected SystemMapNodeReactivity to fire on cross-actor "
        f"mention; got fired_ids={fired!r}"
    )

    rows = await ledger.fetch(COMPANY)
    sm_rows = _system_map_rows(rows)
    assert len(sm_rows) == 1, (
        f"expected exactly one emit_system_map_node entry after "
        f"dispatching one mention chat; got {len(sm_rows)}"
    )

    # Schema validation — round-trip via the canonical Pydantic model so
    # the contract between SystemMapNodePayload's writer and the ledger
    # schema is asserted end-to-end.
    from wormbase_ledger.entries import SystemMapNodePayload
    sm_args = sm_rows[0]["payload"]["args"]
    sm_payload = SystemMapNodePayload.model_validate(sm_args)

    assert sm_payload.node_kind in {"person", "channel"}, (
        f"node_kind must be one of {{person, channel}} for a chat-driven "
        f"emission; got {sm_payload.node_kind!r}"
    )
    assert sm_payload.node_id, (
        f"node_id must resolve to a non-empty string; got "
        f"{sm_payload.node_id!r}"
    )
    # Either the sender (Alice's UUID-string) or the channel id —
    # depending on which won the priority tiebreak. Both are valid.
    expected_node_ids = {str(ALICE), "C-ops"}
    assert sm_payload.node_id in expected_node_ids, (
        f"node_id must be one of {expected_node_ids}; got "
        f"{sm_payload.node_id!r}"
    )
    assert len(sm_payload.edges) > 0, (
        f"edges must be non-empty for a node emitted from a mention "
        f"chat (sender→channel + sender→mention edges accrue weight); "
        f"got edges={sm_payload.edges!r}"
    )

    # PEVR cycle is well-formed — same shape as decision_record's, just
    # for the system_map_node target.
    quad = _system_map_pevr_quad_for(
        rows, execute_seq=int(sm_rows[0]["seq"]),
    )
    pevr_kinds = [r.get("kind") for r in quad]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"], (
        f"expected canonical PEVR seq-order for the system_map_node "
        f"cycle; got {pevr_kinds!r}"
    )


# ---------------------------------------------------------------------------
# SystemMap — canonical behavioural-drift assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_map_e2e_drains_one_per_fire_drift() -> None:
    """Behavioural-drift regression: one node per fire (vs polling's batch flush).

    Per spike §4 caveat 5 (cited in the docstring of
    ``flush_one_node`` and ``SystemMapNodeReactivity``): the legacy
    polling implementation in ``ProcessExtractor._flush_system_map``
    flushed *all* dirty nodes per batch — one tight inner loop emitted
    every node in one ``ProcessExtractor.tick`` cycle. The Reactivity
    model emits **one node per fire** in priority order (highest
    cumulative edge weight first; ties broken by node-id sort).

    This test pins the drift: 5 chat_received entries with text + actors
    + channel that produce 7 dirty nodes; dispatch each + 2 empty-text
    chats to drain the trailing pair. Total: 7 dispatches → 7 separate
    ``system_map_node`` ledger entries (one per fire), NOT 7 in a single
    fire's batch.

    Why 7 dispatches for 7 nodes? Because the Reactivity flushes one
    node per fire, draining the rest requires additional dispatches.
    The two empty-text chats follow the existing pattern from
    ``test_system_map_drained_then_no_new_traffic_no_fire`` in
    ``test_reactivities.py`` — chats that update the accumulator with
    no new edge contribution but still trigger the Reactivity, letting
    the residual dirty nodes drain one per fire. This is the
    behavioural shape callers must adopt; documented here so the
    regression can't silently revert to batch-flush.

    Cite spike §4 caveat 5 (this docstring) — canonical reference for
    the drift.
    """
    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    wire_process_for_install(registry=registry, llm_client=None)

    # Five productive chats — three different senders and three different
    # channels gives us seven distinct dirty-nodes (no dedup of senders
    # across channels, plus channels-as-nodes once each).
    #
    # Senders dirtied: ALICE, BOB, CAROL → 3 distinct person nodes
    # Channels dirtied: C-eng, C-fin, C-ops, C-ops → 3 distinct channel
    #   nodes (C-ops gets re-dirtied but that's still one node)
    # Total distinct dirty nodes: 3 persons + 3 channels = 6.
    # But the SAME (sender, channel) pairs accrue weight on both nodes,
    # and each cross-actor mention adds another dirty bit on the sender.
    # We seed enough distinct (sender, channel) pairs to land 6+ dirty
    # nodes; the assertion below counts emissions, not the exact dirty
    # count, so an off-by-one in the dirty estimate is fine.
    seeds = [
        ("@bob ship the deploy", ALICE, "C-eng", "msg-d1"),  # ALICE, C-eng
        ("@carol approve the invoice", BOB, "C-fin", "msg-d2"),  # BOB, C-fin
        ("@alice on-call rotation", CAROL, "C-ops", "msg-d3"),  # CAROL, C-ops
        ("@bob need help with deploy", ALICE, "C-ops", "msg-d4"),  # +A-mention-bob, +ALICE↔C-ops
        ("@alice incident escalation", BOB, "C-ops", "msg-d5"),  # +B-mention-alice, +BOB↔C-ops
    ]

    fire_count = 0
    sm_emit_count_running: list[int] = []
    for text, sender, channel, message_id in seeds:
        seed_row = await _seed_chat_received(
            ledger,
            COMPANY,
            text=text,
            message_id=message_id,
            channel_id=channel,
            sender_person=sender,
        )
        fired = await registry.dispatch(seed_row)
        if "system_map_node" in fired:
            fire_count += 1
        rows_now = await ledger.fetch(COMPANY)
        sm_emit_count_running.append(len(_system_map_rows(rows_now)))

    # After 5 productive dispatches, exactly 5 system_map_node entries —
    # one per fire, NOT 6+ from a batch flush of all dirty nodes.
    rows_after_5 = await ledger.fetch(COMPANY)
    sm_after_5 = _system_map_rows(rows_after_5)
    assert len(sm_after_5) == 5, (
        f"expected exactly 5 emit_system_map_node entries after 5 "
        f"productive chat dispatches (one per fire — the polling "
        f"loop's batch-flush behaviour would have emitted 6+ at this "
        f"point); got {len(sm_after_5)}. spike §4 caveat 5 regression."
    )
    # Per-step monotonic increment confirms one-per-fire (running counts
    # should be 1, 2, 3, 4, 5 — never +2 in a single dispatch).
    assert sm_emit_count_running == [1, 2, 3, 4, 5], (
        f"expected per-dispatch running counts [1, 2, 3, 4, 5] "
        f"(one emission per fire); got {sm_emit_count_running!r}"
    )

    # Confirm the accumulator still has dirty nodes — these are the
    # ones the polling loop would have batched in. Drain them with
    # empty-text dispatches.
    from wormbase_process_extractor.system_map import (
        get_tenant_accumulator,
    )
    acc = get_tenant_accumulator(COMPANY)
    remaining_dirty = len(acc.dirty_nodes)
    assert remaining_dirty >= 1, (
        f"expected at least one dirty node still pending after 5 fires "
        f"(the residual the polling loop would have batched); got "
        f"dirty_nodes={acc.dirty_nodes!r}"
    )

    # Drain the remaining dirty nodes with empty-text dispatches (no
    # new edge contribution, but each fire still drains one). This
    # mirrors the existing pattern in
    # ``test_system_map_drained_then_no_new_traffic_no_fire``.
    drain_dispatches = 0
    for i in range(remaining_dirty + 2):  # +2 for safety; extras no-op
        seed_row = await _seed_chat_received(
            ledger,
            COMPANY,
            text="",
            message_id=f"msg-drain-{i:02d}",
            channel_id="C-noop",
            sender_person=ALICE,
        )
        await registry.dispatch(seed_row)
        drain_dispatches += 1

    # Final tally: emissions equals 5 + remaining_dirty. Even with safety
    # extras dispatched, no extra emissions occur because the dirty set
    # is drained.
    rows_final = await ledger.fetch(COMPANY)
    sm_final = _system_map_rows(rows_final)
    expected_total = 5 + remaining_dirty
    assert len(sm_final) == expected_total, (
        f"expected exactly {expected_total} total emit_system_map_node "
        f"entries (5 productive + {remaining_dirty} drain); got "
        f"{len(sm_final)} after {5 + drain_dispatches} dispatches. "
        f"This is the canonical 'one per fire' drift assertion — if it "
        f"jumps, the polling loop's batch-flush behaviour has been "
        f"reintroduced. Spike §4 caveat 5."
    )

    # Final accumulator state: drained.
    assert acc.dirty_nodes == set(), (
        f"accumulator dirty set must drain to empty after every dirty "
        f"node has been flushed; got {acc.dirty_nodes!r}"
    )


# ---------------------------------------------------------------------------
# RecurringQuestion (P10) — triplet recurrence fires through factory wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recurring_question_e2e_triplet_fires_via_factory() -> None:
    """Three (asker, askee, topic) recurrences via factory wiring → process_map.

    Plan I.2 §1550-1560: actor A asks actor B about topic T three times
    in the same thread; the first two dispatches do NOT fire P10 (count
    < threshold=3); the third dispatch fires P10 and a
    ``data_product_proposed`` entry of ``kind="process_map"`` lands on
    the ledger; PEVR cycle is well-formed.

    This is the load-bearing regression test for Block F.2's wiring
    decision — process-worm aliases ``RecurringQuestionReactivity`` to
    P10's ``RecurringQuestionProcessMapperReactivity`` directly (no
    wrapper class). If P10 ever stops firing through ``wire_process_for_install``,
    this test fails before any other surface notices.
    """
    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    ids = wire_process_for_install(registry=registry, llm_client=None)
    assert "recurring_question_process_mapper" in ids, (
        f"wire_process_for_install must register P10 under its canonical "
        f"id 'recurring_question_process_mapper'; got ids={ids!r}"
    )

    # Three threaded chats — same (asker=BOB, askee=CAROL, topic=churn_rate)
    # triplet, three different message_ids so the runner sees them as
    # distinct entries. ts_epoch values fall inside the default 14-day
    # window when context.now() is NOW (2026-05-03).
    base_ts = 1777334000.0
    for i in range(1, 4):
        seed_row = await _seed_threaded_chat(
            ledger,
            COMPANY,
            text=(
                f"hey @carol — what's the churn rate this week? (q#{i})"
            ),
            message_id=f"msg-rq-{i:03d}",
            asker=BOB,
            askee=CAROL,
            topic="churn_rate",
            channel_id="C-revenue",
            ts_epoch=base_ts + i,
            thread_ts_epoch=base_ts,
        )
        fired = await registry.dispatch(seed_row)

        if i < 3:
            # First two dispatches: P10 does not fire (count < threshold).
            assert "recurring_question_process_mapper" not in fired, (
                f"P10 must NOT fire on dispatch {i} (count<threshold=3); "
                f"got fired_ids={fired!r}"
            )
            rows_so_far = await ledger.fetch(COMPANY)
            assert _process_map_rows(rows_so_far) == [], (
                f"no data_product_proposed of kind=process_map should "
                f"land before threshold; got "
                f"{len(_process_map_rows(rows_so_far))} after {i} "
                f"dispatches"
            )
        else:
            # Third dispatch: count == threshold → P10 fires.
            assert "recurring_question_process_mapper" in fired, (
                f"P10 must fire on dispatch 3 (count==threshold=3); "
                f"got fired_ids={fired!r}"
            )

    # Exactly one process_map data_product_proposed lands.
    rows_final = await ledger.fetch(COMPANY)
    pm_rows = _process_map_rows(rows_final)
    assert len(pm_rows) == 1, (
        f"expected exactly one emit_data_product_proposed of "
        f"kind=process_map after 3 triplet recurrences; got "
        f"{len(pm_rows)}"
    )

    # Schema-validate the parameters payload — the process_map itself.
    pm_args = pm_rows[0]["payload"]["args"]
    assert pm_args["kind"] == "process_map"
    parameters = pm_args["parameters"]
    # The single (BOB, CAROL, churn_rate) triplet is the lone edge.
    assert len(parameters["edges"]) == 1
    edge = parameters["edges"][0]
    assert edge["from"] == str(BOB)
    assert edge["to"] == str(CAROL)
    assert edge["topic"] == "churn_rate"
    assert edge["frequency"] == 3, (
        f"edge frequency must reflect the 3 observations; got "
        f"{edge['frequency']}"
    )
    # Both BOB and CAROL appear as nodes.
    actor_ids = {n["actor_person_id"] for n in parameters["nodes"]}
    assert actor_ids == {str(BOB), str(CAROL)}, (
        f"process_map nodes must include both asker and askee; got "
        f"{actor_ids!r}"
    )

    # PEVR cycle is well-formed for the data_product_proposed.
    pm_execute = pm_rows[0]
    propose_entry_id = pm_execute["payload"]["propose_entry_id"]
    propose_row = next(
        r for r in rows_final
        if r.get("kind") == "propose"
        and str(r.get("entry_id")) == propose_entry_id
    )
    verify_row = next(
        r for r in rows_final
        if r.get("kind") == "verify"
        and (r.get("payload") or {}).get("execute_entry_id") == str(
            pm_execute.get("entry_id"),
        )
    )
    resolve_row = next(
        r for r in rows_final
        if r.get("kind") == "resolve"
        and (r.get("payload") or {}).get("verify_entry_id") == str(
            verify_row.get("entry_id"),
        )
    )
    quad = sorted(
        [propose_row, pm_execute, verify_row, resolve_row],
        key=lambda r: int(r.get("seq", 0)),
    )
    pevr_kinds = [r.get("kind") for r in quad]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"], (
        f"expected canonical PEVR seq-order for the data_product_proposed "
        f"cycle; got {pevr_kinds!r}"
    )
    # The propose row's target_kind locks in the artifact contract.
    assert propose_row["payload"]["target_kind"] == "data_product_proposed"


# ---------------------------------------------------------------------------
# RecurringQuestion (P10) — factory wiring smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recurring_question_factory_wiring_registers_p10() -> None:
    """Smoke regression: ``wire_process_for_install`` registers the
    canonical P10 reactivity instance into the registry, with the same
    id ``RecurringQuestionProcessMapperReactivity`` ships under. Block
    F.2's load-bearing claim is that process-worm aliases P10 directly
    (zero LOC of new class code); this test pins it.

    The deeper P10 unit suite at
    ``packages/reactivities/tests/test_process_mapper_reactivity.py``
    runs as part of ``pytest packages/reactivities`` — that is the
    authoritative regression for P10's internal behaviour. This test
    asserts only the wiring contract (the id, the registration, the
    instance type).
    """
    from wormbase_reactivities.process_mapper import (
        RecurringQuestionProcessMapperReactivity,
    )

    ledger = InMemoryLedger()
    clock = lambda: NOW  # noqa: E731
    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )
    ids = wire_process_for_install(registry=registry, llm_client=None)

    # Plan §1561-1566: the canonical id must be present.
    assert "recurring_question_process_mapper" in ids, (
        f"wire_process_for_install must register P10 under its canonical "
        f"id 'recurring_question_process_mapper'; got ids={ids!r}"
    )

    # Pull the binding back out and assert the instance type. Use the
    # public ``registry.get(id)`` API rather than reaching into
    # ``registry._bindings`` — the latter would be a private-attribute
    # reach (CLAUDE.md §9 cleanup checklist forbids).
    p10 = registry.get("recurring_question_process_mapper")
    assert p10 is not None, (
        f"P10 reactivity must be retrievable from registry.get(id) "
        f"after wire_process_for_install; ids={ids!r}"
    )
    # Block F.2 alias: the registered instance IS P10's class — no
    # wrapper. If someone introduces a wrapper class (re-defining .fire
    # locally in process-worm), this assertion fails immediately.
    assert isinstance(p10, RecurringQuestionProcessMapperReactivity), (
        f"the registered 'recurring_question_process_mapper' Reactivity "
        f"must be a direct instance of "
        f"RecurringQuestionProcessMapperReactivity (Block F.2 alias "
        f"contract — zero LOC of new class code); got type={type(p10)!r}"
    )


# ---------------------------------------------------------------------------
# W5b composition — explicitly deferred per plan §1567-1572
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "W5b composition test deferred to higher-level integration "
        "suite per plan §1567-1572 + spike §8 C6. "
        "ProcessReferenceWithoutProcessReactivity (W5b's "
        "phenomenon_gaps.py:362) and process-worm's "
        "RecurringQuestionReactivity (P10) both emit "
        "process_map_proposed-shaped artifacts. They co-exist via the "
        "ledger and never call each other directly. A composition test "
        "asserting both fire on appropriate signals AND the dashboard "
        "/processes view aggregates both belongs in tests/integration/, "
        "not in the per-package conformance suite."
    ),
)
@pytest.mark.asyncio
async def test_w5b_composition_deferred() -> None:
    """Placeholder for the deferred W5b composition test.

    Skipped at the conformance layer — the assertion belongs in the
    cross-package integration suite where both W5b and process-worm
    are wired together and a dashboard projection over the ledger can
    be exercised. Pure-process-worm conformance is the scope of THIS
    file.
    """
    pytest.fail(
        "this body should not run; @pytest.mark.skip enforces the deferral",
    )
