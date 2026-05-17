"""Chaos: outbound chat send hits an httpx.NetworkError.

Failure mode
------------
The channel-adapter's outbound DM-send (``send_resource_conversation_dm``
through the ``DMSender`` Protocol) raises ``httpx.NetworkError`` —
the production failure shape when Slack rate-limits us, when DNS fails,
or when the OpenClaw sidecar's TCP socket dies mid-call.

Invariants the system MUST preserve
-----------------------------------
1. The Reactivity catches the error at the worm boundary and logs at
   WARNING, naming the owner + topic so demo-day operators can triage
   (it does NOT silently swallow).
2. The corresponding ``emit_chat_sent`` ledger entry NEVER lands. The
   /trace tab cannot show a fake "we sent the DM" receipt for a send
   that did not actually happen.
3. The worm's *intent* is still recorded via
   ``emit_resource_conversation_proposed`` with an empty
   ``platform_message_id`` — the ledger reflects "we wanted to send
   this; the wire failed" — so the dashboard surfaces an honest
   "send failed" UI by spotting the missing chat_sent receipt.
4. Reactivity-budget counters are NOT corrupted by the failure: the
   ``ReactivityResult`` returned reports the work it did do (budget
   consumed, novelty key updated) so subsequent fires stay bounded.

Failure-injection point
-----------------------
We patch the ``DMSender.send_dm`` method (the dependency boundary) to
raise ``httpx.NetworkError``. The Reactivity sees the exception via
``send_resource_conversation_dm`` which propagates it; the Reactivity's
``except Exception`` branch (statement_to_owner.py:304-313) catches and
records the honest ledger trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    ReactivityContext,
    StatementToOwnerReactivity,
)


CAROL = UUID("eeeeeeee-0000-0000-0000-0000000000c1")
DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Stubs — minimum surface to exercise the failing send path
# ---------------------------------------------------------------------------


@dataclass
class _StubTopic:
    kind: str
    id: UUID
    label: str
    confidence: float
    domain_id: UUID | None


@dataclass
class _StubPerson:
    person_id: UUID
    name: str
    email: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class _StubBundle:
    def to_payload(self) -> dict[str, Any]:
        return {
            "kpis": [], "sources": [], "decisions": [],
            "processes": [], "data_products": [],
        }


def _topic_extractor() -> Any:
    async def _impl(message: str, *, ledger: Any, company_id: UUID) -> Any:
        if "churn" in message.lower():
            return _StubTopic(
                kind="kpi", id=KPI_CHURN, label="churn",
                confidence=0.9, domain_id=DOMAIN_RETENTION,
            )
        return None
    return _impl


def _owner_lookup(person: _StubPerson) -> Any:
    async def _impl(topic: Any, *, ledger: Any, company_id: UUID) -> Any:
        return person
    return _impl


def _aggregator() -> Any:
    async def _impl(topic: Any, *, ledger: Any, company_id: UUID) -> Any:
        return _StubBundle()
    return _impl


class _NetworkErrorDMSender:
    """``DMSender`` that simulates Slack's chat.postMessage being dead.

    On every call we record the attempt count and raise an
    ``httpx.NetworkError`` from ``send_dm``. We let ``open_dm`` succeed
    so the failure manifests at exactly the chat.postMessage boundary —
    the surface the plan calls out.
    """

    platform = "slack"

    def __init__(self) -> None:
        self.open_dm_calls = 0
        self.send_dm_calls = 0

    async def open_dm(self, platform_user_id: str) -> str:
        self.open_dm_calls += 1
        return f"D-{platform_user_id}"

    async def send_dm(
        self,
        platform_channel_id: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        self.send_dm_calls += 1
        raise httpx.NetworkError(
            "chat.postMessage failed: network unreachable",
        )


def _chat_entry(seq: int, text: str, sender_person: UUID | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {
        "text": text,
        "channel_id": "C-rev",
        "message_id": f"M-{seq}",
        "sender_label": "Bob",
    }
    if sender_person is not None:
        args["sender_person"] = str(sender_person)
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


async def test_outbound_send_network_error_does_not_emit_chat_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No fake emit_chat_sent. Honest failure trail. Budget intact."""
    ledger = InMemoryLedger()
    company_id = uuid4()

    sender = _NetworkErrorDMSender()
    rx = StatementToOwnerReactivity(
        topic_extractor=_topic_extractor(),
        owner_lookup=_owner_lookup(_StubPerson(
            person_id=CAROL, name="Carol", platform="slack",
            platform_user_id="U-CAROL",
        )),
        resource_aggregator=_aggregator(),
        dm_sender=sender,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )

    rows_before = len(await ledger.fetch(company_id))

    with caplog.at_level(
        logging.WARNING, logger="wormbase_reactivities.statement_to_owner",
    ):
        result = await rx.fire(_chat_entry(1, "our churn is up"), ctx)

    # Invariant 1: the failure was logged at WARNING with topic + owner
    # context — no silent swallow.
    warns = [
        rec for rec in caplog.records
        if rec.levelno >= logging.WARNING
    ]
    assert any(
        "send_resource_conversation_dm" in rec.getMessage()
        and "topic=churn" in rec.getMessage()
        for rec in warns
    ), (
        f"expected WARNING naming the failing send + topic; got: "
        f"{[r.getMessage() for r in warns]}"
    )

    # Invariant 1 cont'd: send_dm WAS attempted (we did try the wire).
    assert sender.send_dm_calls == 1, (
        "the channel-adapter DOES attempt the send before catching"
    )

    # Invariant 4: the reactivity still returns ``fired=True`` so the
    # registry's budget bookkeeping (per_owner / per_domain / per_tenant)
    # stays correct — we DID consume budget for the attempt; the wire
    # failure is a downstream concern.
    assert result.fired is True, (
        "the reactivity records its work as fired so budget counters are "
        "not corrupted by a transient wire failure"
    )
    assert result.budget_used.get("per_owner") == 1
    assert result.novelty_key == f"topic:{KPI_CHURN}:owner:{CAROL}"

    # Invariant 2: NO emit_chat_sent landed. /trace must not show a fake
    # send receipt for a send that didn't happen.
    rows = await ledger.fetch(company_id)
    chat_sent_tools = [
        r["payload"].get("tool") for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") in (
            "channel_adapter.emit_chat_sent",
            "emit_chat_sent",
        )
    ]
    assert chat_sent_tools == [], (
        "no chat_sent entry must land when the wire failed; got "
        f"{chat_sent_tools}"
    )

    # Invariant 3: emit_resource_conversation_proposed DID land — the
    # worm's intent is the audit trail. The dashboard renders an honest
    # "send failed" state by detecting this entry without the matching
    # chat_sent receipt.
    rcp = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_resource_conversation_proposed"
    ]
    assert len(rcp) == 1, (
        "the proposal entry must land so the dashboard can surface the "
        "send-failure delta"
    )
    # And the channel field carries no platform_message_id — the
    # honest "send failed" marker.
    proposal_args = rcp[0]["payload"]["args"]
    assert proposal_args["channel"] == "", (
        "empty channel ref signals the wire send failed"
    )

    # 4-row PEVR cycle landed for the proposal (the only delta).
    rows_after = len(rows)
    assert rows_after == rows_before + 4, (
        f"exactly one PEVR cycle (4 entries) must land, got delta="
        f"{rows_after - rows_before}"
    )
