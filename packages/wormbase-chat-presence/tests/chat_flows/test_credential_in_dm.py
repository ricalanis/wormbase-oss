"""CredentialInDmFlow + offer-link tests — lifted from
apps/worm-core/tests/test_flows.py in Wave B (D1)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_chat_presence.chat_flows import (
    CredentialInDmFlow,
    MentionedInConversationFlow,
    link_credential_to_proactive_offer,
)
from wormbase_chat_presence.chat_flows._shared import CredentialLeakError
from wormbase_core.reactivity import InfraEvent
from wormbase_core.source_builder import SourceBuilder
from wormbase_core.types import PIIGateResult


class StubPIIGate:
    async def check(self, text, context):
        return PIIGateResult(redacted_text=text, matches=[], changed=False)


class StubInterjectionGate:
    def __init__(self, allow=True):
        self._allow = allow
        self.calls = []

    async def allow(self, channel_id, qtype):
        self.calls.append((channel_id, qtype))
        return self._allow


# -- 2) credential_offered_in_dm -------------------------------------


async def test_credential_dm_recognizes_postgres_uri(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    flow = CredentialInDmFlow(builder, StubPIIGate())
    event = InfraEvent(
        source="dm",
        payload={},
        ts=clock.now(), company_id=company_id, message_id="dm-1",
        person_id=str(uuid4()),
        text="hey use postgres://user:pass@db.local/prod for the warehouse",
    )
    cid = await flow.on_dm(event)
    assert cid is not None
    rows = await ledger.fetch(company_id)
    proposal = [r for r in rows if r["kind"] == "execute"
                and r["payload"]["tool"] == "emit_source_proposed"][0]
    args = proposal["payload"]["args"]
    assert args["source_kind"] == "database"
    # URI should be scrubbed.
    assert "user:pass" not in args["uri"]
    assert "[REDACTED]" in args["uri"]


async def test_credential_dm_rejects_in_public_channel(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    flow = CredentialInDmFlow(builder, StubPIIGate())
    event = InfraEvent(
        source="channel_message",
        payload={},
        ts=clock.now(), company_id=company_id, message_id="m",
        channel_id="C1", text="postgres://u:p@db/x",
    )
    with pytest.raises(CredentialLeakError):
        await flow.on_dm(event)


async def test_credential_dm_full_sequence(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    flow = CredentialInDmFlow(builder, StubPIIGate())
    event = InfraEvent(
        source="dm", payload={}, ts=clock.now(), company_id=company_id,
        message_id="dm-1", person_id=str(uuid4()),
        text="s3://bucket/ledger/exports",
    )
    await flow.on_dm(event)
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    for t in ("emit_source_proposed", "emit_source_confirmed",
              "emit_source_connected", "emit_source_profiled"):
        assert t in tools, f"missing {t}"


# -- 8) link_credential_to_proactive_offer ---------------------------


async def test_link_credential_to_proactive_offer_finds_recent_offer(
    ledger, company_id, clock,
):
    """After a proactive offer is emitted, a credential DM from the same
    person should be linked via the credential_correlation_id."""
    builder = SourceBuilder(ledger, clock)
    flow = MentionedInConversationFlow(builder, ledger, StubInterjectionGate())
    offer_event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C-data",
        person_id="U-bob", message_id="msg-1",
        text="we should integrate Stripe data",
    )
    await flow.on_proactive_mention(offer_event)

    clock.tick(minutes=2)
    linked = await link_credential_to_proactive_offer(
        ledger,
        company_id=company_id,
        credential_correlation_id="cred-xyz",
        prompted_by_person="U-bob",
        now=clock.now(),
    )
    assert linked is not None
    assert linked["archetype"] == "stripe"
    assert linked["channel_id"] == "C-data"
    assert linked["correlation_id"] == "cred-xyz"
    rows = await ledger.fetch(company_id)
    link_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_memory_written"
        and r["payload"]["args"].get("content") == "proactive_offer_credential_link"
    ]
    assert len(link_entries) == 1
    args = link_entries[0]["payload"]["args"]
    assert args["correlation_id"] == "cred-xyz"
    assert args["archetype"] == "stripe"


async def test_link_credential_to_proactive_offer_returns_none_if_no_offer(
    ledger, company_id, clock,
):
    linked = await link_credential_to_proactive_offer(
        ledger,
        company_id=company_id,
        credential_correlation_id="cred-1",
        prompted_by_person="U-nobody",
        now=clock.now(),
    )
    assert linked is None


async def test_link_credential_to_proactive_offer_respects_window(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = MentionedInConversationFlow(builder, ledger, StubInterjectionGate())
    event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C-data",
        person_id="U-bob", message_id="msg-1",
        text="we should integrate Stripe data",
    )
    await flow.on_proactive_mention(event)

    # Beyond 30 min default window.
    clock.tick(hours=2)
    linked = await link_credential_to_proactive_offer(
        ledger,
        company_id=company_id,
        credential_correlation_id="cred-late",
        prompted_by_person="U-bob",
        now=clock.now(),
    )
    assert linked is None


# -- 9) credential_ref threading (2026-06-10 carry-forward #1 closure) ----


async def test_credential_dm_default_writes_none_credential_ref(
    ledger, company_id, clock,
):
    """No resolver supplied → ledger entry carries ``credential_ref=None``.

    Byte-identical pre-2026-06-10 behavior preserved: hosts that
    haven't wired the credential_ref_resolver kwarg get the same
    ledger output as before.
    """
    builder = SourceBuilder(ledger, clock)
    flow = CredentialInDmFlow(builder, StubPIIGate())
    event = InfraEvent(
        source="dm", payload={}, ts=clock.now(), company_id=company_id,
        message_id="dm-noref", person_id=str(uuid4()),
        text="postgres://user:pass@db.local/prod",
    )
    await flow.on_dm(event)
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1
    assert connected[0]["payload"]["args"].get("credential_ref") is None


async def test_credential_dm_resolver_writes_credential_ref(
    ledger, company_id, clock,
):
    """Resolver-returned ref lands on the source_connected ledger entry.

    Pins the production-ready DM seam: a host that wants to broker-
    provision a slot on receipt of a DM credential can do so via the
    new ``credential_ref_resolver`` kwarg. The raw URI is handed to
    the resolver (only seam where it's visible post-scrub); the
    resolver returns the slot key it provisioned.
    """
    builder = SourceBuilder(ledger, clock)
    raw_uris_seen: list[str] = []

    def resolver(uri: str, scrubbed: str) -> str:
        raw_uris_seen.append(uri)
        # Pretend we wrote the secret to vault under this slot key.
        return f"vault://db-creds/{uuid4().hex[:8]}"

    flow = CredentialInDmFlow(
        builder, StubPIIGate(), credential_ref_resolver=resolver,
    )
    event = InfraEvent(
        source="dm", payload={}, ts=clock.now(), company_id=company_id,
        message_id="dm-ref", person_id=str(uuid4()),
        text="postgres://user:s3cret@db.local/prod",
    )
    await flow.on_dm(event)
    # Resolver saw the raw URI exactly once.
    assert len(raw_uris_seen) == 1
    assert "postgres://" in raw_uris_seen[0]
    assert "user:s3cret" in raw_uris_seen[0]

    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1
    cred_ref = connected[0]["payload"]["args"].get("credential_ref")
    assert cred_ref is not None
    assert cred_ref.startswith("vault://db-creds/")
    # And the ledger URI is scrubbed regardless — resolver doesn't get
    # to bypass the scrub.
    proposal = [
        r for r in rows if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ][0]
    assert "user:s3cret" not in proposal["payload"]["args"]["uri"]


async def test_credential_dm_async_resolver_works(ledger, company_id, clock):
    """Async resolvers are supported (mirror ``connector_register`` shape)."""
    builder = SourceBuilder(ledger, clock)

    async def async_resolver(_uri: str, _scrubbed: str) -> str:
        return "vault://async-resolved"

    flow = CredentialInDmFlow(
        builder, StubPIIGate(), credential_ref_resolver=async_resolver,
    )
    event = InfraEvent(
        source="dm", payload={}, ts=clock.now(), company_id=company_id,
        message_id="dm-async", person_id=str(uuid4()),
        text="postgres://u:p@h/db",
    )
    await flow.on_dm(event)
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ][0]
    assert connected["payload"]["args"]["credential_ref"] == (
        "vault://async-resolved"
    )


async def test_credential_dm_resolver_returning_none_writes_none(
    ledger, company_id, clock,
):
    """Resolver may decline (return None) — entry still writes, ref None."""
    builder = SourceBuilder(ledger, clock)

    def resolver(_uri: str, _scrubbed: str) -> str | None:
        return None  # broker provisioning failed / declined

    flow = CredentialInDmFlow(
        builder, StubPIIGate(), credential_ref_resolver=resolver,
    )
    event = InfraEvent(
        source="dm", payload={}, ts=clock.now(), company_id=company_id,
        message_id="dm-none", person_id=str(uuid4()),
        text="postgres://u:p@h/db",
    )
    await flow.on_dm(event)
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ][0]
    assert connected["payload"]["args"].get("credential_ref") is None
