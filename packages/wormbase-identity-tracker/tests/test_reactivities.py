"""Greenfield Reactivities tests — Wave B.5.

PositionInferenceReactivity (G.4) and (later) ResourceOwnershipReactivity
(G.5) are scored, threshold-gated emitters of *propose-step* kinds
(``position_proposed`` / ``resource_role_proposed``). Both subscribe to
``chat_received`` and use signal-token scoring against the canonical
`positions.py` registry.

The PositionInferenceReactivity contract (G.4):

  * predicate: EntryKind("chat_received")
  * condition: AlwaysAllow (dedup is internal — known-position skip)
  * fire():
      1. read sender_person from the chat_received args
      2. skip if that Person already has a confirmed position (from
         emit_position_assigned OR a kept emit_position_proposed earlier
         in the same fold)
      3. accumulate signal scores over the recent chat history of the
         Person (current entry + prior ``chat_received`` rows)
      4. when best score crosses threshold ≥ 0.5, emit
         ``emit_position_proposed`` PEVR cycle via
         ``write_actions.propose_position``
      5. novelty_key = ``f"position:{person_id}"`` so Reactivity-runner
         dedupes per-Person

Threshold rationale: the canonical positions registry exposes 3-5
patterns per position. A Person whose chatter matches ≥ 2 patterns of
the same position should cross the 0.5 confidence floor —
score = matched / total_patterns_in_position, so 2/4 = 0.5 for Data
Engineer (4 patterns).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload, PersonProposedPayload


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (mirror test_unknown_platform_id_reactivity.py shape)
# ---------------------------------------------------------------------------


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    sender_person: UUID,
    text: str,
    channel_id: str = "C0",
) -> str:
    """Seed a ``channel_adapter.emit_chat_received`` row carrying ``text``.

    The Reactivity reads the canonical Pydantic fields (sender_person +
    text) — no `platform` shim required for position inference because
    sender_person is the resolved Person UUID.
    """
    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=str(uuid4()),
        sender_person=sender_person,
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": args["message_id"],
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": args["message_id"],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )
    return args["message_id"]


async def _seed_person_proposed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    name: str = "Bob",
    position: str | None = None,
) -> None:
    """Seed an ``emit_person_proposed`` for ``person_id`` (optionally with
    a confirmed position).

    Used by the "skip when position already assigned" test to suppress
    re-proposal once the worm has already assigned a position.
    """
    payload = PersonProposedPayload(
        person_id=person_id,
        tenant_id=company_id,
        name=name,
        email=f"{name.lower()}@x.co",
        platform="slack",
        platform_user_id=f"U-{name.lower()}",
        proposed_by="worm",
        position=position,
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": args,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


def _position_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter the ledger to ``emit_position_proposed`` execute rows."""
    return [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_position_proposed"
    ]


async def _drive_position_reactivity(
    ledger: InMemoryLedger,
    company_id: UUID,
) -> None:
    """Drive PositionInferenceReactivity once over the current ledger state."""
    from wormbase_identity_tracker.reactivities import (
        PositionInferenceReactivity,
    )
    from wormbase_reactivities import ReactivityRegistry, ReactivityRunner

    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(PositionInferenceReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


# ---------------------------------------------------------------------------
# G.4 — PositionInferenceReactivity tests
# ---------------------------------------------------------------------------


async def test_position_inference_reactivity_id_and_metadata() -> None:
    """The Reactivity advertises a stable id + name."""
    from wormbase_identity_tracker.reactivities import (
        PositionInferenceReactivity,
    )

    r = PositionInferenceReactivity()
    assert r.id == "position_inference"
    assert r.name == "Position Inference"
    assert r.scope == "company"


async def test_position_inference_reactivity_proposes_on_signal_threshold(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Inject N chat_received entries with data-engineer patterns; expect
    an emit_position_proposed PEVR cycle landing with confidence ≥ 0.5.
    """
    pid = uuid4()
    # Pre-seed a Person row so the projection fold has a target. The
    # Reactivity itself doesn't require this (it reads sender_person
    # off the chat entry directly), but it mirrors production wire order.
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Dee")

    # Three chat messages from Dee with data-engineer signal tokens.
    # The DE position has 5 patterns: "why is", "when did this break",
    # "what changed", "schema", "query cost". Three tokens → confidence
    # 3/5 = 0.6 (≥ 0.5 threshold).
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="why is the bronze→silver pipeline lagging?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="schema drift on the orders table — what changed?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="our query cost on snowflake spiked overnight",
    )

    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _position_proposals(rows)
    assert len(proposals) == 1, (
        f"expected 1 emit_position_proposed; got {len(proposals)}"
    )
    args = proposals[0]["payload"]["args"]
    assert args["person_id"] == str(pid)
    assert args["position"] == "data_engineer"
    assert args["confidence"] >= 0.5
    # signals carries the matched pattern tokens for explainability
    assert args["signals"], "signals tuple should be non-empty"

    # Full PEVR cycle landed (propose → execute → verify → resolve).
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx = None
    for i, r in enumerate(rows_sorted):
        if r.get("kind") != "propose":
            continue
        body = r.get("payload") or {}
        if (
            body.get("target_kind") == "position_proposed"
            and body.get("ref_id") == str(pid)
        ):
            propose_idx = i
            break
    assert propose_idx is not None
    pevr_kinds = [r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"]
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == "emit_position_proposed_payload_valid"
    assert checks[0]["ok"] is True


async def test_position_inference_below_threshold_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """A single weak signal (1 match in a 5-pattern position) is below
    threshold (1/5 = 0.2 < 0.5) → no proposal.
    """
    pid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Edd")
    # Only one DE pattern matches: "schema".
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="just shared the schema docs in #general",
    )
    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _position_proposals(rows) == []


async def test_position_inference_skips_person_with_position_already(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """If the Person already has a confirmed position, the Reactivity
    must not re-propose — Doctrine Rule 4 (idempotent fold semantics):
    repeating the propose is observation-only noise.
    """
    pid = uuid4()
    # Pre-seed the Person with position already set on the seed row.
    await _seed_person_proposed(
        ledger, company_id, person_id=pid, name="Fox",
        position="data_engineer",
    )
    # Send three DE-signaling messages; should NOT re-propose.
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="why is the pipeline broken? schema migration?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="what changed in the silver schema?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="query cost is up 3x",
    )
    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _position_proposals(rows) == []


async def test_position_inference_dedupes_per_person(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two runs over the same chat history → at most one propose per Person.

    The Reactivity-runner's novelty_key dedup protects against
    re-emitting on every poll; for the same Person, the second run is a
    no-op. Belt-and-suspenders dedup also lives inside fire() (skip if a
    pending position_proposed is already in the chain).
    """
    pid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Gem")
    for text in (
        "why is bronze→silver lagging? schema drift?",
        "what changed in cardinality on the orders table?",
        "query cost spike — when did this break?",
    ):
        await _seed_chat_received(
            ledger, company_id, sender_person=pid, text=text,
        )

    await _drive_position_reactivity(ledger, company_id)
    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _position_proposals(rows)
    assert len(proposals) == 1


async def test_position_inference_emits_reactivity_fired(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The Reactivity records its fires for /trace under id ``position_inference``."""
    pid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Hex")
    for text in (
        "why is the pipeline lagging?",
        "schema drift this morning",
        "what changed in the silver layer?",
    ):
        await _seed_chat_received(
            ledger, company_id, sender_person=pid, text=text,
        )
    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    assert len(fires) == 1
    args = fires[0]["payload"]["args"]
    assert args["reactivity_id"] == "position_inference"
    assert args["novelty_key"] == f"position:{pid}"


# ---------------------------------------------------------------------------
# G.5 — ResourceOwnershipReactivity tests
# ---------------------------------------------------------------------------
#
# ResourceOwnershipReactivity subscribes to ``chat_received`` AND
# ``data_product_consumed``. It aggregates per-(person, resource) signal
# counts and, when total signals ≥ 2 (confidence ≥ 0.5), emits a
# ``emit_resource_role_proposed`` PEVR cycle with role="maintainer".
#
# Signal sources:
#   * chat_mention: a chat_received text contains the resource_id UUID
#   * data_product_consumed: a Person consumed the data product (resource)
#
# Confidence formula: min(1.0, signal_count / 4.0). Threshold 0.5 → ≥ 2 signals.


from wormbase_ledger.entries import DataProductConsumedPayload


async def _seed_data_product_consumed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    resource_id: UUID,
    surface: str = "dashboard",
) -> None:
    """Seed an ``emit_data_product_consumed`` execute row."""
    payload = DataProductConsumedPayload(
        data_product_id=resource_id,
        consumed_by_person_id=person_id,
        surface=surface,
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_consumed",
            "ref_id": str(resource_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_consumed",
            "args": args,
            "result_ref": str(resource_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


def _resource_role_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_resource_role_proposed"
    ]


async def _drive_resource_ownership_reactivity(
    ledger: InMemoryLedger,
    company_id: UUID,
) -> None:
    from wormbase_identity_tracker.reactivities import (
        ResourceOwnershipReactivity,
    )
    from wormbase_reactivities import ReactivityRegistry, ReactivityRunner

    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(ResourceOwnershipReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


async def test_resource_ownership_reactivity_id_and_metadata() -> None:
    from wormbase_identity_tracker.reactivities import (
        ResourceOwnershipReactivity,
    )

    r = ResourceOwnershipReactivity()
    assert r.id == "resource_ownership"
    assert r.name == "Resource Ownership"
    assert r.scope == "company"


async def test_resource_ownership_reactivity_proposes_maintainer_on_chatter(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Chat-mention + data_product_consumed signals cross threshold → propose maintainer."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Iris")
    # Two chat_mention signals: text contains the resource_id UUID.
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"working on {rid} this morning",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"shipped a fix to {rid}",
    )

    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _resource_role_proposals(rows)
    assert len(proposals) == 1, (
        f"expected 1 emit_resource_role_proposed; got {len(proposals)}"
    )
    args = proposals[0]["payload"]["args"]
    assert args["person_id"] == str(pid)
    assert args["resource_id"] == str(rid)
    assert args["role"] == "maintainer"
    assert args["confidence"] >= 0.5
    assert args["signals"], "signals tuple should be non-empty"
    assert "chat_mention" in args["signals"]

    # Full PEVR cycle landed (propose → execute → verify → resolve).
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx = None
    for i, r in enumerate(rows_sorted):
        if r.get("kind") != "propose":
            continue
        body = r.get("payload") or {}
        if (
            body.get("target_kind") == "resource_role_proposed"
            and body.get("ref_id") == str(rid)
        ):
            propose_idx = i
            break
    assert propose_idx is not None
    pevr_kinds = [r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"]
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == "emit_resource_role_proposed_payload_valid"
    assert checks[0]["ok"] is True


async def test_resource_ownership_combines_chat_and_consumed_signals(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """One chat_mention + one data_product_consumed = 2 signals → propose."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Jay")
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"taking a look at {rid}",
    )
    await _seed_data_product_consumed(
        ledger, company_id, person_id=pid, resource_id=rid,
    )

    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _resource_role_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert "chat_mention" in args["signals"]
    assert "data_product_consumed" in args["signals"]


async def test_resource_ownership_below_threshold_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """A single signal (1/4 = 0.25 < 0.5) does not cross threshold."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Kim")
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"saw {rid} in passing",
    )
    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _resource_role_proposals(rows) == []


async def test_resource_ownership_skips_already_proposed_pair(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """If a (person, resource) pair already has a proposal in flight, skip."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Lou")
    for _ in range(3):
        await _seed_chat_received(
            ledger, company_id, sender_person=pid,
            text=f"keeping eyes on {rid}",
        )

    await _drive_resource_ownership_reactivity(ledger, company_id)
    # Add more signals after the first proposal lands.
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"another pass on {rid}",
    )
    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert len(_resource_role_proposals(rows)) == 1


async def test_resource_ownership_dedupes_per_pair(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two runs over the same signals → at most one proposal per (person, resource)."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Mab")
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"working on {rid}",
    )
    await _seed_data_product_consumed(
        ledger, company_id, person_id=pid, resource_id=rid,
    )

    await _drive_resource_ownership_reactivity(ledger, company_id)
    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert len(_resource_role_proposals(rows)) == 1


async def test_resource_ownership_emits_reactivity_fired(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The Reactivity records its fires for /trace under id ``resource_ownership``."""
    pid = uuid4()
    rid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Nyx")
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text=f"on {rid} now",
    )
    await _seed_data_product_consumed(
        ledger, company_id, person_id=pid, resource_id=rid,
    )

    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
        and (r.get("payload") or {}).get("args", {}).get("reactivity_id")
        == "resource_ownership"
    ]
    assert len(fires) >= 1
    args = fires[0]["payload"]["args"]
    assert args["novelty_key"] == f"resource_role:{pid}:{rid}"


async def test_resource_ownership_segregates_by_pair(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two distinct (person, resource) pairs each cross threshold independently."""
    pid_a = uuid4()
    pid_b = uuid4()
    rid_x = uuid4()
    rid_y = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid_a, name="Oz")
    await _seed_person_proposed(ledger, company_id, person_id=pid_b, name="Pia")

    # Pair (A, X): 2 chat mentions
    await _seed_chat_received(
        ledger, company_id, sender_person=pid_a,
        text=f"working on {rid_x}",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid_a,
        text=f"another pass at {rid_x}",
    )
    # Pair (B, Y): 1 chat mention + 1 consumption
    await _seed_chat_received(
        ledger, company_id, sender_person=pid_b,
        text=f"reviewing {rid_y}",
    )
    await _seed_data_product_consumed(
        ledger, company_id, person_id=pid_b, resource_id=rid_y,
    )
    # Cross signals (A mentions Y once) — below threshold for that pair.
    await _seed_chat_received(
        ledger, company_id, sender_person=pid_a,
        text=f"glanced at {rid_y}",
    )

    await _drive_resource_ownership_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _resource_role_proposals(rows)
    pairs = {
        (p["payload"]["args"]["person_id"], p["payload"]["args"]["resource_id"])
        for p in proposals
    }
    assert (str(pid_a), str(rid_x)) in pairs
    assert (str(pid_b), str(rid_y)) in pairs
    assert (str(pid_a), str(rid_y)) not in pairs  # below threshold
    assert len(proposals) == 2
