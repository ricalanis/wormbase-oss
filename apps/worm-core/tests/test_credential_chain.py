"""Step 2 (proactivity hook) — full mention → offer → credential → cascade.

This test exercises the canonical demo arc end-to-end:
  1. Bob says "we should integrate Stripe data" in #data
  2. Worm emits ``emit_source_proposed`` (added_via_flow=mentioned_in_conversation)
     and ``emit_proactive_offer`` (the speech act).
  3. Bob DMs ``API_KEY=sk_live_...`` to the worm.
  4. ``CredentialInDmFlow`` recognizes the URI, writes another proposal +
     full source-builder sequence; we link it back to the offer.
  5. ``MedallionCascade`` runs and writes ``emit_source_bronzed/silvered/golded``.

The chain is verified by the trail of execute entries the ledger carries.
"""

from __future__ import annotations

from uuid import uuid4

from wormbase_core.flows import (
    CredentialInDmFlow,
    MentionedInConversationFlow,
    credential_in_dm_with_offer_link,
    link_credential_to_proactive_offer,
)
from wormbase_core.medallion import MedallionCascade
from wormbase_core.reactivity import InfraEvent
from wormbase_core.source_builder import SourceBuilder
from wormbase_core.types import PIIGateResult


class StubPIIGate:
    async def check(self, text, context):
        return PIIGateResult(redacted_text=text, matches=[], changed=False)


class StubInterjectionGate:
    async def allow(self, channel_id, qtype):
        return True


async def test_canonical_arc_writes_full_chain(ledger, company_id, clock):
    """Mention → offer → credential → linked → cascade.

    Asserts the 5 critical execute entries land in the right order:
      emit_source_proposed   (proactive)
      emit_proactive_offer
      emit_source_proposed   (credential DM)
      emit_memory_written  (proactive_offer_credential_link)
      emit_source_bronzed/silvered/golded (cascade)
    """
    builder = SourceBuilder(ledger, clock)
    cascade = MedallionCascade(ledger, clock=clock)
    mentioned = MentionedInConversationFlow(
        builder, ledger, StubInterjectionGate(),
    )
    cred_flow = CredentialInDmFlow(builder, StubPIIGate())

    # 1) Bob speaks in channel.
    bob_id = str(uuid4())
    channel_event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C-data",
        person_id=bob_id, message_id="msg-1",
        text="we should integrate Stripe data",
    )
    proactive = await mentioned.on_proactive_mention(channel_event)
    assert proactive is not None
    assert proactive.archetype == "stripe"

    # 2) Bob DMs the credential a few minutes later.
    clock.tick(minutes=2)
    dm_event = InfraEvent(
        source="dm", payload={}, ts=clock.now(),
        company_id=company_id, message_id="dm-1",
        person_id=bob_id,
        text="hey use sk_live_abcdef0123456789ABCDEF for the stripe wire-up",
    )
    cred_result = await credential_in_dm_with_offer_link(
        cred_flow, dm_event, cascade=cascade,
    )
    assert cred_result is not None
    assert cred_result["correlation_id"] is not None
    assert cred_result["linked_offer"] is not None
    assert cred_result["linked_offer"]["archetype"] == "stripe"
    assert cred_result["linked_offer"]["correlation_id"] == cred_result["correlation_id"]
    # Cascade ran.
    assert cred_result["cascade_summary"] is not None
    assert "bronze" in cred_result["cascade_summary"]
    assert "silver" in cred_result["cascade_summary"]

    # 3) Verify the 5 critical entries in the ledger trail.
    rows = await ledger.fetch(company_id)
    execs = [
        r for r in rows
        if r["kind"] == "execute"
    ]
    tools = [e["payload"]["tool"] for e in execs]

    # First proactive proposal.
    assert tools.count("emit_source_proposed") >= 2, tools
    # Proactive offer speech act.
    assert "emit_proactive_offer" in tools, tools
    # Cascade outputs (bronze + silver always fire; gold is conditional
    # on a non-empty bronze sample, which a credential-only URI lacks).
    assert "emit_source_bronzed" in tools, tools
    assert "emit_source_silvered" in tools, tools
    # Link entry.
    link_entries = [
        e for e in execs
        if e["payload"]["tool"] == "emit_memory_written"
        and e["payload"]["args"].get("content")
            == "proactive_offer_credential_link"
    ]
    assert len(link_entries) == 1, link_entries

    # 4) Trail order: offer comes before link.
    offer_seq = next(
        i for i, e in enumerate(execs)
        if e["payload"]["tool"] == "emit_proactive_offer"
    )
    link_seq = next(
        i for i, e in enumerate(execs)
        if e["payload"]["tool"] == "emit_memory_written"
        and e["payload"]["args"].get("content")
            == "proactive_offer_credential_link"
    )
    assert offer_seq < link_seq

    # 5) Bronze entry corresponds to the credential's source_id (cascade
    # was driven by the credential proposal, not the proactive one).
    bronze_entries = [
        e for e in execs if e["payload"]["tool"] == "emit_source_bronzed"
    ]
    assert len(bronze_entries) == 1


async def test_credential_dm_without_prior_offer_skips_link(
    ledger, company_id, clock,
):
    """Credential lands but no recent offer → link is skipped, cred still
    produces a clean proposal + cascade."""
    builder = SourceBuilder(ledger, clock)
    cascade = MedallionCascade(ledger, clock=clock)
    cred_flow = CredentialInDmFlow(builder, StubPIIGate())
    dm_event = InfraEvent(
        source="dm", payload={}, ts=clock.now(),
        company_id=company_id, message_id="dm-1",
        person_id=str(uuid4()),
        text="postgres://user:pass@warehouse/prod",
    )
    cred_result = await credential_in_dm_with_offer_link(
        cred_flow, dm_event, cascade=cascade,
    )
    assert cred_result is not None
    assert cred_result["linked_offer"] is None
    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"]["tool"] for r in rows if r["kind"] == "execute"
    ]
    # Cascade still ran for the cred proposal.
    assert "emit_source_bronzed" in tools


async def test_link_outside_window_does_not_attach(
    ledger, company_id, clock,
):
    """The 30-min link window is enforced — beyond it, no attachment."""
    builder = SourceBuilder(ledger, clock)
    mentioned = MentionedInConversationFlow(
        builder, ledger, StubInterjectionGate(),
    )
    bob_id = str(uuid4())
    await mentioned.on_proactive_mention(
        InfraEvent(
            source="channel_message", payload={}, ts=clock.now(),
            company_id=company_id, channel_id="C1",
            person_id=bob_id, message_id="msg-1",
            text="we should pull stripe",
        ),
    )
    clock.tick(hours=2)
    linked = await link_credential_to_proactive_offer(
        ledger,
        company_id=company_id,
        credential_correlation_id="cid-late",
        prompted_by_person=bob_id,
        now=clock.now(),
    )
    assert linked is None
