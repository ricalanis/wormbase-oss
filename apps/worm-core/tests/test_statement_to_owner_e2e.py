"""W5.A2 — end-to-end test for the statement-to-owner reactivity.

Drives a chat_received ledger entry through the full pipeline:

  1. seed canonical ontology (KPI churn in retention domain, Carol owns
     retention, Carol's preferences allow conversations).
  2. write a chat_received entry with the statement "our churn is up".
  3. invoke the registry's dispatch(...) — same path the runner takes.
  4. assert the ledger contains the expected sequence:
        emit_chat_received → emit_resource_conversation_proposed →
        emit_chat_sent (DM) → emit_reactivity_fired
  5. assert the DM body was rendered correctly (topic, statement,
     pinned resources).

The DM is sent through an in-memory ChannelAdapter mock that records
each call. The mock writes ``emit_chat_sent`` to the ledger directly so
the e2e ledger sequence reflects what the wire path would do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_core.owner_lookup import lookup_owner
from wormbase_core.resource_aggregator import gather_related_resources
from wormbase_core.topic_extractor import extract_topic
from wormbase_reactivities import (
    ReactivityRegistry,
    StatementToOwnerReactivity,
)


CAROL = UUID("eeeeeeee-0000-0000-0000-0000000000c1")
BOB = UUID("eeeeeeee-0000-0000-0000-0000000000b1")
DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")
SOURCE_STRIPE = UUID("bbbbbbbb-0000-0000-0000-000000000001")
ADMIN = UUID("00000000-0000-0000-0000-000000000099")


# ---------------------------------------------------------------------------
# Mock ChannelAdapter — opens DMs, sends DMs, writes emit_chat_sent.
# ---------------------------------------------------------------------------


@dataclass
class _MockChannelAdapter:
    """Minimal DMSender that records calls and writes emit_chat_sent.

    The production channel-adapter writes emit_chat_sent into the ledger
    when an outbound message lands; this mock mirrors that so our e2e
    assertion can see the full ledger sequence.
    """

    ledger: Any
    company_id: UUID
    platform: str = "slack"
    sent_messages: list[tuple[str, str]] = field(default_factory=list)

    async def open_dm(self, platform_user_id: str) -> str:
        return f"D-{platform_user_id}"

    async def send_dm(self, platform_channel_id: str, text: str,
                      *, blocks: list[dict[str, Any]] | None = None) -> str:
        self.sent_messages.append((platform_channel_id, text))
        msg_id = f"M-{len(self.sent_messages)}"

        # Mirror the channel-adapter writer: emit_chat_sent into ledger.
        chat_args = {
            "channel_id": platform_channel_id,
            "message_id": msg_id,
            "text": text,
            "in_reply_to": None,
            "attribution": {"source": "mock", "session_id": "test"},
            "speech_act": "answer",
        }
        await self.ledger.write(
            company_id=self.company_id,
            propose={"target_kind": "chat_sent", "ref_id": msg_id,
                     "reason": "mock channel adapter", "proposed_by": "worm"},
            execute_fn=lambda: {
                "tool": "channel_adapter.emit_chat_sent",
                "args": chat_args,
                "result_ref": msg_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "payload_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {"outcome": "keep",
                                    "rationale": "mock dm sent"},
            quadrant="active_probabilistic",
        )
        return msg_id


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _w(ledger, company_id, target_kind, tool, args):
    """Tight write helper for fixture seeding."""
    return await ledger.write(
        company_id=company_id,
        propose={"target_kind": target_kind, "ref_id": str(uuid4()),
                 "reason": "seed", "proposed_by": "test"},
        execute_fn=lambda: {"tool": tool, "args": args,
                             "result_ref": "seed"},
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _seed_org(ledger, company_id):
    """Set up Carol-owns-retention with a churn KPI + stripe source."""
    # Persons (Carol, Bob).
    await _w(ledger, company_id, "person_proposed", "emit_person_proposed", {
        "person_id": str(CAROL),
        "tenant_id": str(company_id),
        "name": "Carol",
        "email": "carol@x.com",
        "platform": "slack",
        "platform_user_id": "U-CAROL",
        "proposed_by": "worm",
    })
    await _w(ledger, company_id, "person_proposed", "emit_person_proposed", {
        "person_id": str(BOB),
        "tenant_id": str(company_id),
        "name": "Bob",
        "email": "bob@x.com",
        "platform": "slack",
        "platform_user_id": "U-BOB",
        "proposed_by": "worm",
    })
    # KPI tree (churn in retention).
    await _w(ledger, company_id, "kpi_node", "emit_kpi_node", {
        "id": str(KPI_CHURN),
        "label": "churn",
        "domain_id": str(DOMAIN_RETENTION),
        "formula": "delta(active)/active_prev",
        "unit": "pct",
    })
    # Source (stripe in retention).
    await _w(ledger, company_id, "source_proposed", "emit_source_proposed", {
        "source_id": str(SOURCE_STRIPE),
        "source_kind": "database",
        "uri": "postgres://example/stripe",
        "added_via_flow": "dashboard_form",
        "suggested_domain": "retention",
        "suggested_classification": "internal",
        "name": "stripe",
    })
    await _w(ledger, company_id, "source_confirmed", "emit_source_confirmed", {
        "source_id": str(SOURCE_STRIPE),
        "domain_id": str(DOMAIN_RETENTION),
        "classification": "internal",
        "confirmed_by_person": str(ADMIN),
    })
    # Domain ownership: Carol owns retention.
    await _w(ledger, company_id, "domain_role_assigned",
             "emit_domain_role_assigned", {
        "person_id": str(CAROL),
        "domain_id": str(DOMAIN_RETENTION),
        "role": "owner",
        "granted_by": str(ADMIN),
    })


async def _write_chat_received(ledger, company_id, *, text: str,
                                sender_person_id: UUID = BOB,
                                channel_id: str = "C-rev",
                                message_id: str = "M-001") -> int:
    """Write a chat_received PEVR cycle and return the seq of the
    execute envelope (so tests can pin the source_seq)."""
    args = {
        "channel_id": channel_id,
        "message_id": message_id,
        "sender_person": str(sender_person_id),
        "text": text,
        "classification": "internal",
        "sender_label": "Bob",
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "chat_received", "ref_id": message_id,
                 "reason": "test inbound", "proposed_by": "channel-adapter"},
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": message_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep",
                                "rationale": "inbound persisted"},
        quadrant="active_probabilistic",
    )
    rows = await ledger.fetch(company_id)
    # Find the execute envelope of the chat_received we just wrote.
    for r in reversed(rows):
        if (r["kind"] == "execute"
                and r["payload"].get("tool")
                == "channel_adapter.emit_chat_received"):
            return int(r["seq"])
    raise AssertionError("chat_received execute not found")


# ---------------------------------------------------------------------------
# E2E
# ---------------------------------------------------------------------------


async def test_statement_to_owner_full_pipeline(ledger, company_id):
    """Bob says 'our churn is up' → Carol receives a DM → ledger sequence."""
    await _seed_org(ledger, company_id)
    chat_seq = await _write_chat_received(
        ledger, company_id, text="our churn is up 8% MoM in Europe",
    )

    sender = _MockChannelAdapter(ledger=ledger, company_id=company_id)
    rx = StatementToOwnerReactivity(
        topic_extractor=extract_topic,
        owner_lookup=lookup_owner,
        resource_aggregator=gather_related_resources,
        dm_sender=sender,
    )
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=lambda: state["now"],
    )
    reg.register(rx)

    # Pull the chat_received row (the runner would do this) and dispatch.
    rows = await ledger.fetch(company_id)
    chat_row = next(r for r in rows
                    if r["kind"] == "execute"
                    and r["payload"].get("tool")
                    == "channel_adapter.emit_chat_received")
    fired = await reg.dispatch(chat_row)
    assert fired == [rx.id]

    # Assert the DM was sent.
    assert len(sender.sent_messages) == 1
    dm_channel, dm_body = sender.sent_messages[0]
    assert dm_channel == "D-U-CAROL"
    assert "churn" in dm_body
    assert "our churn is up 8% MoM in Europe" in dm_body
    assert "KPI: churn" in dm_body
    assert "Source: stripe" in dm_body

    # Assert the full ledger sequence.
    rows = await ledger.fetch(company_id)
    tools_in_order = []
    for r in rows:
        if r["kind"] != "execute":
            continue
        t = r["payload"].get("tool")
        if t in (
            "channel_adapter.emit_chat_received",
            "emit_resource_conversation_proposed",
            "channel_adapter.emit_chat_sent",
            "emit_reactivity_fired",
        ):
            tools_in_order.append(t)

    # Note on ordering: the wire DM lands BEFORE the ledger receipt
    # because the reactivity sends the DM first and only then writes
    # the ledger entry. This is the production sequence; the receipts
    # for both writes carry the same conversation_id so /trace can
    # thread them back together.
    expected_subseq = [
        "channel_adapter.emit_chat_received",
        "channel_adapter.emit_chat_sent",
        "emit_resource_conversation_proposed",
        "emit_reactivity_fired",
    ]
    assert tools_in_order == expected_subseq, (
        f"unexpected ledger sequence: {tools_in_order}"
    )

    # The fired entry references the chat_received seq and our reactivity_id.
    fired_row = next(r for r in rows if r["kind"] == "execute"
                     and r["payload"].get("tool") == "emit_reactivity_fired")
    fa = fired_row["payload"]["args"]
    assert fa["reactivity_id"] == "statement_to_owner"
    assert fa["source_seq"] == chat_seq

    # The proposed entry carries the topic + owner.
    proposed_row = next(r for r in rows if r["kind"] == "execute"
                        and r["payload"].get("tool")
                        == "emit_resource_conversation_proposed")
    pa = proposed_row["payload"]["args"]
    assert pa["topic"]["label"] == "churn"
    assert pa["topic"]["kind"] == "kpi"
    assert pa["owner_id"] == str(CAROL)
    assert pa["statement_seq"] == chat_seq
    # Pinned resources rendered.
    assert any(k["label"] == "churn" for k in pa["resources"]["kpis"])
    assert any(s["label"] == "stripe" for s in pa["resources"]["sources"])


async def test_statement_to_owner_self_statement_no_fire(
    ledger, company_id,
):
    """Carol says 'our churn is up' → no DM (self-statement)."""
    await _seed_org(ledger, company_id)
    await _write_chat_received(
        ledger, company_id, text="our churn is up",
        sender_person_id=CAROL,
    )

    sender = _MockChannelAdapter(ledger=ledger, company_id=company_id)
    rx = StatementToOwnerReactivity(
        topic_extractor=extract_topic,
        owner_lookup=lookup_owner,
        resource_aggregator=gather_related_resources,
        dm_sender=sender,
    )
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(rx)

    rows = await ledger.fetch(company_id)
    chat_row = next(r for r in rows
                    if r["kind"] == "execute"
                    and r["payload"].get("tool")
                    == "channel_adapter.emit_chat_received")
    fired = await reg.dispatch(chat_row)
    assert fired == []
    assert sender.sent_messages == []


async def test_statement_to_owner_irrelevant_chatter_no_fire(
    ledger, company_id,
):
    """Generic chatter doesn't match any topic → no DM."""
    await _seed_org(ledger, company_id)
    await _write_chat_received(
        ledger, company_id, text="lunch was great today thanks",
    )

    sender = _MockChannelAdapter(ledger=ledger, company_id=company_id)
    rx = StatementToOwnerReactivity(
        topic_extractor=extract_topic,
        owner_lookup=lookup_owner,
        resource_aggregator=gather_related_resources,
        dm_sender=sender,
    )
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(rx)
    rows = await ledger.fetch(company_id)
    chat_row = next(r for r in rows
                    if r["kind"] == "execute"
                    and r["payload"].get("tool")
                    == "channel_adapter.emit_chat_received")
    fired = await reg.dispatch(chat_row)
    assert fired == []
    assert sender.sent_messages == []
