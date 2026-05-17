"""UnknownPlatformIdReactivity tests — lift + rename from worm-core.

Folds two original test files:
  apps/worm-core/tests/test_identity_discovery.py        — Reactivity unit
  apps/worm-core/tests/test_identity_discovery_migration.py — byte-equivalence

Import path changes:
  - `from wormbase_core.identity_discovery import IdentityDiscoveryReactivity`
  + `from wormbase_identity_tracker.reactivities import UnknownPlatformIdReactivity`

Class-name changes throughout the test bodies:
  - `IdentityDiscoveryReactivity(...)` → `UnknownPlatformIdReactivity(...)`
  - assertions on `Reactivity.id == "identity_discovery"` → `"unknown_platform_id"`

Byte-equivalence test imports BOTH the legacy loop AND the renamed
Reactivity:
  - `from wormbase_identity_tracker.legacy import IdentityDiscoveryLoop`
  - `from wormbase_identity_tracker.reactivities import UnknownPlatformIdReactivity`

The byte-equivalence assertion remains: legacy Loop and Reactivity
write IDENTICAL emit_person_proposed entries given the same inputs.
The Reactivity id mismatch in `emit_reactivity_fired` does NOT break
this — the byte-equivalence test compares emit_person_proposed payloads,
not emit_reactivity_fired payloads (the legacy loop doesn't write
reactivity_fired entries at all because it's not a Reactivity).

Note: the legacy module emits a DeprecationWarning at import time. The
byte-equivalence tests import it intentionally (it's the reference
contract for the regression). We suppress the warning at the module
level to keep test output clean.
"""

from __future__ import annotations

import warnings
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    ChatReceivedPayload,
    IdentityLinkedPayload,
    PersonProposedPayload,
)

# Suppress the legacy module's import-time DeprecationWarning. We import
# the legacy IdentityDiscoveryLoop intentionally for the byte-equivalence
# regression — it's the reference contract.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from wormbase_identity_tracker.legacy import IdentityDiscoveryLoop

from wormbase_identity_tracker.reactivities import UnknownPlatformIdReactivity
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner


# ---------------------------------------------------------------------------
# Helpers (lifted verbatim from test_identity_discovery.py)
# ---------------------------------------------------------------------------


class MockMemberLookup:
    """Canned member_lookup callable. Each test plugs in its own response."""

    def __init__(
        self,
        responses: dict[tuple[str, str], dict[str, Any] | None] | None = None,
        *,
        default: dict[str, Any] | None = None,
        raise_on: tuple[str, str] | None = None,
        is_async: bool = False,
    ) -> None:
        self.responses = responses or {}
        self.default = default
        self.raise_on = raise_on
        self.is_async = is_async
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self, platform: str, platform_user_id: str,
    ):
        if self.is_async:
            return self._acall(platform, platform_user_id)
        return self._scall(platform, platform_user_id)

    def _scall(self, platform: str, platform_user_id: str):
        self.calls.append((platform, platform_user_id))
        if self.raise_on == (platform, platform_user_id):
            raise RuntimeError("synthetic lookup failure")
        return self.responses.get(
            (platform, platform_user_id), self.default,
        )

    async def _acall(self, platform: str, platform_user_id: str):
        return self._scall(platform, platform_user_id)


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform: str,
    platform_user_id: str,
    channel_id: str = "C0",
    text: str = "hi",
) -> None:
    """Seed a ``channel_adapter.emit_chat_received`` row.

    Mirrors what the channel-adapter wire writes — including the raw
    ``platform`` + ``platform_user_id`` args the discovery loop watches
    for.
    """
    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=str(uuid4()),
        sender_person=uuid4(),
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    args["platform"] = platform
    args["platform_user_id"] = platform_user_id

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


async def _seed_file_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform: str,
    platform_user_id: str,
    channel_id: str = "C0",
) -> None:
    """Seed a ``channel_adapter.emit_file_received`` row."""
    args = {
        "channel_id": channel_id,
        "message_id": str(uuid4()),
        "sender_person": str(uuid4()),
        "filename": "report.csv",
        "mimetype": "text/csv",
        "bytes_url": "file:///tmp/report.csv",
        "platform": platform,
        "platform_user_id": platform_user_id,
        "classification": "internal",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "file_received",
            "ref_id": args["message_id"],
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_file_received",
            "args": args,
            "result_ref": args["message_id"],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _seed_person_proposed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform: str,
    platform_user_id: str,
    name: str = "Bob",
    email: str | None = "bob@x.co",
) -> UUID:
    """Seed a pre-existing ``emit_person_proposed`` cycle."""
    pid = uuid4()
    payload = PersonProposedPayload(
        person_id=pid,
        tenant_id=company_id,
        name=name,
        email=email,
        platform=platform,
        platform_user_id=platform_user_id,
        proposed_by="worm",
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(pid),
            "reason": "test seed pre-existing",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": args,
            "result_ref": str(pid),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    return pid


async def _seed_identity_linked(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
) -> None:
    """Seed an ``emit_identity_linked`` for an existing Person."""
    payload = IdentityLinkedPayload(
        person_id=person_id,
        platform=platform,
        platform_user_id=platform_user_id,
        linked_by=uuid4(),
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "identity_linked",
            "ref_id": str(person_id),
            "reason": "test seed identity link",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_identity_linked",
            "args": args,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


def _person_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter the ledger to ``emit_person_proposed`` execute rows."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == "emit_person_proposed":
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Reactivity unit tests — lifted from test_identity_discovery.py with
# IdentityDiscoveryLoop → UnknownPlatformIdReactivity (driven via the
# ReactivityRunner) and id assertion → "unknown_platform_id".
#
# The legacy tests instantiated `IdentityDiscoveryLoop` directly and
# called `loop.run_once()`. The Reactivity equivalent is to register
# the Reactivity into a `ReactivityRegistry` and let the
# `ReactivityRunner` dispatch entries. We provide a small helper that
# exercises the same Reactivity end-to-end so each lifted scenario
# preserves its semantic.
# ---------------------------------------------------------------------------


async def _drive_via_reactivity(
    ledger: InMemoryLedger,
    company_id: UUID,
    member_lookup,
) -> None:
    """Drive the Reactivity once over the current ledger state.

    Mirrors the legacy `loop.run_once()` semantics — one full pass over
    every newly-arrived entry, all matching Reactivities fired.
    """
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(UnknownPlatformIdReactivity(member_lookup=member_lookup))
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


async def test_reactivity_id_is_unknown_platform_id() -> None:
    """The renamed Reactivity advertises its new id."""
    lookup = MockMemberLookup()
    reactivity = UnknownPlatformIdReactivity(member_lookup=lookup)
    assert reactivity.id == "unknown_platform_id"
    assert reactivity.name == "Unknown Platform ID"


async def test_unknown_platform_user_id_proposes_person(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-stranger",
    )
    lookup = MockMemberLookup({
        ("slack", "U-stranger"): {
            "name": "Stranger Danger",
            "email": "stranger@example.co",
            "avatar_url": None,
        },
    })
    await _drive_via_reactivity(ledger, company_id, lookup)
    assert lookup.calls == [("slack", "U-stranger")]

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert args["platform"] == "slack"
    assert args["platform_user_id"] == "U-stranger"
    assert args["name"] == "Stranger Danger"
    assert args["email"] == "stranger@example.co"
    assert args["proposed_by"] == "worm"

    # Verify a full PEVR cycle landed (4 entries: propose, execute,
    # verify, resolve) — the write went through write_actions.propose_person.
    pid = args["person_id"]
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx: int | None = None
    for i, r in enumerate(rows_sorted):
        if r.get("kind") != "propose":
            continue
        body = r.get("payload") or {}
        if (
            body.get("ref_id") == pid
            and body.get("proposed_by") == "worm"
            and body.get("target_kind") == "person_proposed"
        ):
            propose_idx = i
            break
    assert propose_idx is not None, (
        "reactivity did not emit a propose row with ref_id=person_id"
    )
    pevr_kinds = [r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"], (
        f"expected full PEVR cycle, got {pevr_kinds}"
    )
    # The verify row carries the tool_payload_valid check from
    # write_actions._pevr — confirms it actually went via propose_person.
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == "emit_person_proposed_payload_valid"
    assert checks[0]["ok"] is True


async def test_known_platform_user_id_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_person_proposed(
        ledger, company_id,
        platform="slack", platform_user_id="U-bob",
        name="Bob", email="bob@x.co",
    )
    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-bob",
        text="another from bob",
    )

    # Lookup returns metadata but the Reactivity should not consult it
    # because the identity is already known.
    lookup = MockMemberLookup(default={"name": "Bob", "email": "bob@x.co"})
    await _drive_via_reactivity(ledger, company_id, lookup)

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    # Only the seeded proposal — no new one from the Reactivity.
    assert len(proposals) == 1


async def test_member_lookup_returns_none_skips_proposal(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-ghost",
    )
    lookup = MockMemberLookup(default=None)
    await _drive_via_reactivity(ledger, company_id, lookup)
    assert lookup.calls == [("slack", "U-ghost")]

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []


async def test_member_lookup_failure_logged_not_raised(
    ledger: InMemoryLedger, company_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-explode",
    )
    lookup = MockMemberLookup(raise_on=("slack", "U-explode"))
    import logging as _logging
    with caplog.at_level(
        _logging.WARNING,
        logger="wormbase_identity_tracker.reactivities",
    ):
        await _drive_via_reactivity(ledger, company_id, lookup)

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []

    # Lookup raised but the Reactivity survives + logs.
    assert any(
        "member_lookup raised" in rec.message
        for rec in caplog.records
    )

    # Reactivity is still usable — a second cycle works.
    await _drive_via_reactivity(ledger, company_id, lookup)
    rows2 = await ledger.fetch(company_id)
    assert _person_proposals(rows2) == []


async def test_file_received_events_also_trigger_proposal(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_file_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-uploader",
    )
    lookup = MockMemberLookup(default={"name": "Up Loader", "email": "up@x.co"})
    await _drive_via_reactivity(ledger, company_id, lookup)

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert args["platform_user_id"] == "U-uploader"
    assert args["name"] == "Up Loader"


async def test_identity_linked_marks_id_as_known(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    # Pre-seed a Person on slack, then link a discord identity to it.
    pid = await _seed_person_proposed(
        ledger, company_id,
        platform="slack", platform_user_id="U-bob-slack",
        name="Bob", email="bob@x.co",
    )
    await _seed_identity_linked(
        ledger, company_id,
        person_id=pid, platform="discord", platform_user_id="bob#1234",
    )
    # Now bob chats from discord — the Reactivity should treat (discord,
    # bob#1234) as already-known and not propose a duplicate Person.
    await _seed_chat_received(
        ledger, company_id,
        platform="discord", platform_user_id="bob#1234",
        channel_id="D-general",
    )

    lookup = MockMemberLookup(default={"name": "Bob", "email": "bob@x.co"})
    await _drive_via_reactivity(ledger, company_id, lookup)
    # Lookup should not have been called for the already-linked identity.
    assert ("discord", "bob#1234") not in lookup.calls

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    # Only the one we seeded; no new proposal from the Reactivity.
    assert len(proposals) == 1


# ---------------------------------------------------------------------------
# Tenant-reset test — preserved using the legacy IdentityDiscoveryLoop.
#
# The Reactivity is stateless wrt tenant resets (it rehydrates the
# known-set from the ledger inside fire() on every call), so the
# tenant-reset semantic is implicitly handled. The legacy Loop's
# in-memory `_known` + `_last_seq` state is what required the explicit
# reset detection, and the byte-equivalence regression below covers the
# legacy path. We exercise the legacy reset path here against the
# legacy module to keep coverage at parity.
# ---------------------------------------------------------------------------


async def test_legacy_loop_tenant_reset_resets_last_seq_and_known(
    company_id: UUID,
) -> None:
    # Build a ledger, seed an identity, run the legacy loop to drain it;
    # then swap the ledger for a fresh one (max_seq=0 < loop's
    # last_seq>0) and assert the loop rewinds + re-discovers.
    ledger_a = InMemoryLedger()
    await _seed_chat_received(
        ledger_a, company_id,
        platform="slack", platform_user_id="U-old",
    )
    lookup = MockMemberLookup(default={"name": "Old", "email": "old@x.co"})
    loop = IdentityDiscoveryLoop(
        ledger=ledger_a, company_id=company_id, member_lookup=lookup,
    )
    assert await loop.run_once() == 1
    assert ("slack", "U-old") in loop._known  # noqa: SLF001
    last_seq_before = loop._last_seq  # noqa: SLF001
    assert last_seq_before > 0

    # Simulate a tenant reset by swapping ledgers (matches what
    # `wormbase demo seed --reset-first` does to the DB-backed Ledger).
    ledger_b = InMemoryLedger()
    loop._ledger = ledger_b  # noqa: SLF001
    # New tenant has its own first event for a different identity.
    await _seed_chat_received(
        ledger_b, company_id,
        platform="slack", platform_user_id="U-new-after-reset",
    )

    n = await loop.run_once()
    assert n == 1
    rows = await ledger_b.fetch(company_id)
    args = _person_proposals(rows)[0]["payload"]["args"]
    assert args["platform_user_id"] == "U-new-after-reset"

    # Known set was cleared; old identity is not carried over into the
    # post-reset tenancy.
    assert ("slack", "U-old") not in loop._known  # noqa: SLF001
    assert ("slack", "U-new-after-reset") in loop._known  # noqa: SLF001


# ---------------------------------------------------------------------------
# Byte-equivalence regression — lifted from test_identity_discovery_migration.py
# Imports BOTH the legacy IdentityDiscoveryLoop AND the renamed
# UnknownPlatformIdReactivity. Asserts emit_person_proposed payloads are
# byte-equivalent across the two execution paths.
# ---------------------------------------------------------------------------


async def _seed_chat_received_simple(
    ledger: InMemoryLedger, company_id: UUID,
    *, platform: str, platform_user_id: str,
) -> None:
    """Minimal chat-received seeder used by the byte-equivalence test.

    Same semantic as `_seed_chat_received` above with default channel_id
    and text values; kept as a separate helper to preserve verbatim the
    body of the original migration test.
    """
    payload = ChatReceivedPayload(
        channel_id="C0",
        message_id=str(uuid4()),
        sender_person=uuid4(),
        text="hi",
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    args["platform"] = platform
    args["platform_user_id"] = platform_user_id
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


def _person_proposed_args(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the args dicts of every emit_person_proposed execute row.

    Strips ``person_id`` (uuid4-generated, won't match) but keeps every
    other field so we can byte-compare.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_person_proposed":
            continue
        args = dict(payload.get("args") or {})
        args.pop("person_id", None)
        out.append(args)
    return out


def _pevr_kinds(rows: list[dict[str, Any]]) -> list[str]:
    """Kind sequence for every entry; lets us verify PEVR cycles align."""
    return [r.get("kind", "") for r in sorted(rows, key=lambda r: r["seq"])]


async def _drive_via_legacy_loop(
    ledger: InMemoryLedger,
    company_id: UUID,
    member_lookup,
) -> None:
    loop = IdentityDiscoveryLoop(
        ledger=ledger, company_id=company_id, member_lookup=member_lookup,
    )
    await loop.run_once()


async def _drive_via_reactivity_runner(
    ledger: InMemoryLedger,
    company_id: UUID,
    member_lookup,
) -> None:
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(UnknownPlatformIdReactivity(member_lookup=member_lookup))
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


def _filter_person_proposed_pevr(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Slice of rows belonging to person_proposed PEVR cycles.

    A "person_proposed PEVR cycle" is a contiguous propose→execute→verify→resolve
    quartet whose execute tool is ``emit_person_proposed``. We walk the
    sorted ledger, find each emit_person_proposed execute row, and grab
    the preceding propose + the following two (verify + resolve).
    """
    sorted_rows = sorted(rows, key=lambda r: r["seq"])
    out: list[dict[str, Any]] = []
    for i, r in enumerate(sorted_rows):
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_person_proposed":
            continue
        # Propose is at i-1; verify at i+1; resolve at i+2.
        if i >= 1:
            out.append(sorted_rows[i - 1])
        out.append(sorted_rows[i])
        if i + 1 < len(sorted_rows):
            out.append(sorted_rows[i + 1])
        if i + 2 < len(sorted_rows):
            out.append(sorted_rows[i + 2])
    return out


async def test_legacy_loop_byte_equivalent(
    company_id: UUID,
) -> None:
    """Two ledgers, same input, two execution paths — assert equivalence.

    The legacy IdentityDiscoveryLoop and the renamed
    UnknownPlatformIdReactivity must write IDENTICAL emit_person_proposed
    PEVR cycles. The Reactivity additionally writes
    emit_reactivity_fired entries (with the new id
    ``"unknown_platform_id"``); those are intentional and not compared
    here.
    """

    def member_lookup(platform: str, platform_user_id: str) -> dict[str, Any]:
        return {
            "name": f"Bob-{platform_user_id}",
            "email": f"{platform_user_id}@x.co",
            "avatar_url": None,
        }

    # Path A: legacy loop.
    ledger_a = InMemoryLedger()
    await _seed_chat_received_simple(
        ledger_a, company_id, platform="slack", platform_user_id="U-bob",
    )
    await _seed_chat_received_simple(
        ledger_a, company_id, platform="slack", platform_user_id="U-alice",
    )
    await _drive_via_legacy_loop(ledger_a, company_id, member_lookup)

    # Path B: Reactivity.
    ledger_b = InMemoryLedger()
    await _seed_chat_received_simple(
        ledger_b, company_id, platform="slack", platform_user_id="U-bob",
    )
    await _seed_chat_received_simple(
        ledger_b, company_id, platform="slack", platform_user_id="U-alice",
    )
    await _drive_via_reactivity_runner(ledger_b, company_id, member_lookup)

    rows_a = await ledger_a.fetch(company_id)
    rows_b = await ledger_b.fetch(company_id)

    # Same number of person-proposed rows (one per unknown identity, two seeded).
    args_a = _person_proposed_args(rows_a)
    args_b = _person_proposed_args(rows_b)
    assert len(args_a) == 2
    assert len(args_b) == 2

    # Args match identity-by-identity (order may differ; sort to compare).
    by_id_a = sorted(args_a, key=lambda x: x["platform_user_id"])
    by_id_b = sorted(args_b, key=lambda x: x["platform_user_id"])
    for a, b in zip(by_id_a, by_id_b, strict=True):
        assert a["platform"] == b["platform"]
        assert a["platform_user_id"] == b["platform_user_id"]
        assert a["name"] == b["name"]
        assert a["email"] == b["email"]
        assert a["proposed_by"] == b["proposed_by"] == "worm"
        assert a.get("position") == b.get("position")  # both None

    # Both paths should produce identical PEVR-shaped sequences for the
    # person-proposed cycles; we don't byte-compare full ledgers because
    # the Reactivity adds emit_reactivity_fired entries by design.
    person_pevr_a = _filter_person_proposed_pevr(rows_a)
    person_pevr_b = _filter_person_proposed_pevr(rows_b)
    assert _pevr_kinds(person_pevr_a) == _pevr_kinds(person_pevr_b)
    # Both sides emit two full PEVR cycles (8 entries each).
    assert len(person_pevr_a) == 8
    assert len(person_pevr_b) == 8


async def test_reactivity_emits_reactivity_fired_entry(
    company_id: UUID,
) -> None:
    """The Reactivity pathway records its fires in the ledger for /trace.

    The reactivity_id in the audit entry is the NEW
    ``"unknown_platform_id"``. Historical entries with the legacy
    ``"identity_discovery"`` id remain in the chain (Rule 1) and are
    aliased by trace-UI consumers via
    ``wormbase_identity_tracker.reactivities.LEGACY_REACTIVITY_ID``.
    """

    def member_lookup(platform: str, platform_user_id: str) -> dict[str, Any]:
        return {"name": "Bob", "email": "bob@x.co", "avatar_url": None}

    ledger = InMemoryLedger()
    await _seed_chat_received_simple(
        ledger, company_id, platform="slack", platform_user_id="U-bob",
    )
    await _drive_via_reactivity_runner(ledger, company_id, member_lookup)
    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    assert len(fires) == 1
    args = fires[0]["payload"]["args"]
    assert args["reactivity_id"] == "unknown_platform_id"
    assert args["novelty_key"] == "slack:U-bob"


async def test_reactivity_does_not_repropose_known_identity(
    company_id: UUID,
) -> None:
    """The Reactivity, like the legacy loop, dedupes via the known-set."""

    def member_lookup(platform: str, platform_user_id: str) -> dict[str, Any]:
        return {"name": "Bob", "email": "bob@x.co", "avatar_url": None}

    ledger = InMemoryLedger()
    # First chat → propose.
    await _seed_chat_received_simple(
        ledger, company_id, platform="slack", platform_user_id="U-bob",
    )
    await _drive_via_reactivity_runner(ledger, company_id, member_lookup)
    rows_after_first = await ledger.fetch(company_id)
    person_proposes_first = [
        r for r in rows_after_first
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_person_proposed"
    ]
    assert len(person_proposes_first) == 1

    # Second chat from the same identity → no new propose.
    await _seed_chat_received_simple(
        ledger, company_id, platform="slack", platform_user_id="U-bob",
    )
    await _drive_via_reactivity_runner(ledger, company_id, member_lookup)
    rows_after_second = await ledger.fetch(company_id)
    person_proposes_second = [
        r for r in rows_after_second
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_person_proposed"
    ]
    assert len(person_proposes_second) == 1


# ---------------------------------------------------------------------------
# Legacy-id constant export — used by trace-UI alias mapping in Block H.
# ---------------------------------------------------------------------------


def test_legacy_reactivity_id_constant_exported() -> None:
    """`LEGACY_REACTIVITY_ID` exposes the historical id for trace alias mapping."""
    from wormbase_identity_tracker.reactivities import LEGACY_REACTIVITY_ID

    assert LEGACY_REACTIVITY_ID == "identity_discovery"
