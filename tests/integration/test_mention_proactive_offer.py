"""L5 integration: a Stripe mention in a channel must fire a proactive offer.

C2 root cause (PRD §9.2): the chat_received reactivity poller only
dispatched to the flow_dispatcher when ``synthesized.type == "file_drop"``.
Chat events with ``suggested_flow="mentioned_in_conversation"`` were
classified, the relevance gate decided to react, but the flow never ran
— so ``emit_source_proposed`` and ``emit_proactive_offer`` never landed.

This test exercises the full reactivity-pipeline + dispatcher chain
end-to-end (the same code path the poller drives in production), and
asserts the demo's beat-4 sequence: ``emit_source_proposed`` (stripe)
+ ``emit_proactive_offer``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


async def test_stripe_mention_fires_proactive_offer(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    """End-to-end: a synthesized chat event with the Stripe demo text drives
    on_proactive_mention via the dispatcher chain.

    Mirrors the production flow: ``chat_received_reactivity_poller`` polls
    the ledger, synthesizes a raw event, runs ``pipeline.process()`` (which
    invokes the relevance gate), then fans out to the dispatcher chain.
    The poller itself is Postgres-only, so we replicate its synthesize +
    dispatch step here against the in-memory ledger.
    """
    from wormbase_core.medallion import MedallionCascade
    from wormbase_core.service import (
        _synthesize_event,
        make_flow_dispatcher_with_proactivity,
    )

    worm = worm_core_integration
    ledger = integration_ledger
    company_id = integration_company_id

    cascade = MedallionCascade(ledger)
    dispatcher = make_flow_dispatcher_with_proactivity(
        worm.drop_and_profile,
        worm.credential_in_dm,
        worm.mentioned_in_conversation,
        company_id,
        cascade,
    )

    # Synthesize the chat event the channel-adapter would have written.
    chat_payload = {
        "tool": "channel_adapter.emit_chat_received",
        "args": {
            "channel_id": "C0DEMO",
            "message_id": "1777152800.000001",
            "sender_person": str(uuid4()),
            "text": (
                "we should also pull our Stripe data so the gross-net rec is clean"
            ),
            "classification": "internal",
        },
    }
    event = _synthesize_event(
        "channel_adapter.emit_chat_received", chat_payload, company_id,
    )
    assert event is not None, "synthesizer returned None"

    # Run through the production reactivity pipeline → relevance gate.
    decision = await worm.pipeline.process(event)
    assert decision is not None, "pipeline returned no decision"
    assert decision.should_react, (
        f"relevance gate refused to react. reason={decision.reason!r}"
    )
    assert decision.suggested_flow == "mentioned_in_conversation", (
        f"expected mentioned_in_conversation; got {decision.suggested_flow!r}"
    )

    # Dispatch — the C2 fix is what makes this reachable on a chat event.
    await dispatcher(event, decision)

    # Assertions: emit_source_proposed for stripe + emit_proactive_offer.
    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_source_proposed" in tools, (
        f"emit_source_proposed never landed; saw tools: {sorted(set(tools))}"
    )
    assert "emit_proactive_offer" in tools, (
        f"emit_proactive_offer never landed; saw tools: {sorted(set(tools))}"
    )

    source_proposed_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_source_proposed"
    ]
    args = source_proposed_rows[0]["payload"].get("args", {})
    # SourceProposedPayload exposes the URI on the `uri` field; the
    # proactive flow's added_via_flow is mentioned_in_conversation.
    uri = args.get("uri", "")
    assert "stripe" in uri.lower(), f"expected stripe URI, got {uri!r}"
    assert args.get("added_via_flow") == "mentioned_in_conversation", (
        f"expected added_via_flow=mentioned_in_conversation, got {args!r}"
    )

    offer_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_proactive_offer"
    ]
    offer_args = offer_rows[0]["payload"].get("args", {})
    assert offer_args.get("archetype") == "stripe", (
        f"expected stripe archetype on offer, got {offer_args!r}"
    )
