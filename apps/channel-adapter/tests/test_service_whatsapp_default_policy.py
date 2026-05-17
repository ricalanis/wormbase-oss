"""Tests for WhatsAppLogCapture's default-lurker first-touch policy (Wave A2).

When the channel-adapter's WhatsApp dispatch handler sees an admit signal
for a previously-unseen WhatsApp channel, it writes an explicit
``policy_applied`` ledger entry binding that channel to
``talkativeness="lurker", daily_interjection_budget=0``.

Why: the chat-presence default is ``responsive, 3`` — correct for Slack,
unsafe for WhatsApp where Wave C will wire outbound ``send`` and a silent
posture flip would mean unwanted messages in real WhatsApp groups.

Behaviors locked down:

* First admit of a NEW WhatsApp channel writes a ``policy_applied`` PEVR
  cycle with the lurker template; second admit of the same channel is a
  no-op (idempotent via in-process LRU + ledger fold).
* The Slack capture path (``GlobalLogCapture``) is untouched — Slack
  channels never get a policy_applied written by this code path.
* Multi-tenant: same channel id under different ``company_id`` writes
  separate entries (per-tenant capture instance owns its own LRU; ledger
  fold is company-scoped).
* When a prior policy already exists in the ledger (e.g. an admin set
  the channel to ``proactive``), the capture does NOT overwrite it on
  first admit — the fold short-circuits and only the cache marker is set.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter

from wormbase_channel_adapter.service import GlobalLogCapture, WhatsAppLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def writer(ledger: InMemoryLedger, company_id: UUID) -> LedgerWriter:
    return LedgerWriter(ledger, company_id)


def _policy_executes(rows: list[dict]) -> list[dict]:
    """Filter to ``emit_policy_applied`` execute rows."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_policy_applied"
    ]


def _talkativeness_executes(rows: list[dict], channel_id: str) -> list[dict]:
    """Filter further to channel_talkativeness policies for a specific channel."""
    out = []
    for r in _policy_executes(rows):
        args = r["payload"].get("args") or {}
        if args.get("policy_name") != "policy:channel_talkativeness":
            continue
        applies_to = args.get("applies_to") or {}
        if applies_to.get("channel_id") != channel_id:
            continue
        out.append(r)
    return out


def _baileys_msg(
    *,
    msg_id: str,
    jid: str = "5511999999999@s.whatsapp.net",
    body: str = "hello",
    ts_unix: int | None = None,
) -> dict:
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


async def _build_capture(
    writer: LedgerWriter,
    company_id: UUID,
) -> tuple[WhatsAppLogCapture, WhatsAppChannelAdapter]:
    """Build a WhatsAppLogCapture + adapter pinned to LIVE state.

    The adapter is in a state that produces real InfraEvents on
    ``fetch_latest_and_normalize`` once a message is injected, so the
    full on_channel_admit flow exercises both the policy write AND the
    chat_received path.
    """
    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()  # LIVE
    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )
    return capture, adapter


# ---------------------------------------------------------------------------
# A2.1 — first admit writes lurker policy_applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_admit_writes_default_lurker_policy(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    capture, _adapter = await _build_capture(writer, company_id)

    jid = "5511999999999@s.whatsapp.net"
    await capture.on_channel_admit(jid)

    rows = await ledger.fetch(company_id)
    policies = _talkativeness_executes(rows, jid)
    assert len(policies) == 1, (
        "first admit should write exactly one policy_applied entry "
        "for the WhatsApp channel"
    )
    args = policies[0]["payload"]["args"]
    assert args["talkativeness"] == "lurker"
    assert args["daily_interjection_budget"] == 0
    assert args["policy_name"] == "policy:channel_talkativeness"
    assert args["applies_to"] == {"scope": "channel", "channel_id": jid}
    # gate_impl resolves via governance.gates.channel_talkativeness_default
    assert args["gate_impl"] == "channel_talkativeness_default"

    # PEVR cycle: the ledger should have ONE propose with target_kind
    # "policy_applied" attributed to the WhatsApp capture path. The
    # ledger's write primitive guarantees the matching execute / verify
    # / resolve land in the same write call — we count only the propose
    # (the execute is already counted in the policies list above).
    propose_rows = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "policy_applied"
        and r["payload"].get("proposed_by") == "channel-adapter.whatsapp"
    ]
    assert len(propose_rows) == 1

    # And the cache is populated.
    assert jid in capture.seen_channels


# ---------------------------------------------------------------------------
# A2.2 — second admit is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_admit_is_idempotent(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    capture, _adapter = await _build_capture(writer, company_id)
    jid = "5511999999999@s.whatsapp.net"

    await capture.on_channel_admit(jid)
    await capture.on_channel_admit(jid)
    await capture.on_channel_admit(jid)  # belt-and-braces

    rows = await ledger.fetch(company_id)
    policies = _talkativeness_executes(rows, jid)
    assert len(policies) == 1, (
        "subsequent admits must NOT write additional policy_applied entries "
        "for the same channel"
    )


@pytest.mark.asyncio
async def test_second_admit_idempotent_after_cache_clear(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Cache eviction / process restart simulation: even if the in-process
    ``_seen_channels`` cache is cleared, the ledger fold prevents a
    double-write because the prior policy_applied entry is still on disk.
    """
    capture, _adapter = await _build_capture(writer, company_id)
    jid = "5511999999999@s.whatsapp.net"

    await capture.on_channel_admit(jid)

    # Simulate cache eviction (or service restart).
    capture._seen_channels.clear()

    await capture.on_channel_admit(jid)

    rows = await ledger.fetch(company_id)
    policies = _talkativeness_executes(rows, jid)
    assert len(policies) == 1, (
        "ledger fold must absorb post-restart admits even with empty cache"
    )
    # Cache re-warmed by the fold.
    assert jid in capture.seen_channels


# ---------------------------------------------------------------------------
# A2.3 — Slack first-touch is unaffected
# ---------------------------------------------------------------------------


def _stub_slack(latest_msg: dict | None, *, bot_id: str | None = None):
    stub = AsyncMock()
    stub.fetch_latest_message = AsyncMock(return_value=latest_msg)
    stub.bot_id = bot_id
    stub.bot_user_id = None
    return stub


@pytest.mark.asyncio
async def test_slack_first_touch_writes_no_policy_applied(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The Slack ``GlobalLogCapture`` path must NOT write a default
    policy on first-touch: Slack channels stay on the chat-presence
    default of ``responsive, 3`` (which is the correct Slack posture).
    Wave A2 is WhatsApp-only.
    """
    slack = _stub_slack(
        {
            "ts": "1777152782.000001",
            "user": "U0SENDER",
            "text": "hello world",
        }
    )
    capture = GlobalLogCapture(
        ledger=ledger, company_id=company_id, slack=slack,
    )

    await capture.on_channel_admit("C0SLACK1")

    rows = await ledger.fetch(company_id)
    # No policy_applied entries from the Slack path.
    assert _policy_executes(rows) == []


# ---------------------------------------------------------------------------
# A2.4 — Multi-tenant: per-company isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_tenant_same_channel_id_writes_per_company(
    ledger: InMemoryLedger,
) -> None:
    """Same WhatsApp jid in two different tenants writes a policy_applied
    in each tenant. The ledger fold is company-scoped, so tenant B's
    capture instance does not see tenant A's prior policy and writes its
    own.
    """
    tenant_a = tenant_to_company_uuid("tenant-a")
    tenant_b = tenant_to_company_uuid("tenant-b")
    assert tenant_a != tenant_b

    writer_a = LedgerWriter(ledger, tenant_a)
    writer_b = LedgerWriter(ledger, tenant_b)

    capture_a, _ = await _build_capture(writer_a, tenant_a)
    capture_b, _ = await _build_capture(writer_b, tenant_b)

    jid = "5511888888888@s.whatsapp.net"  # same channel id in both tenants
    await capture_a.on_channel_admit(jid)
    await capture_b.on_channel_admit(jid)

    rows_a = await ledger.fetch(tenant_a)
    rows_b = await ledger.fetch(tenant_b)
    pa = _talkativeness_executes(rows_a, jid)
    pb = _talkativeness_executes(rows_b, jid)
    assert len(pa) == 1, "tenant A's first-touch must write a policy"
    assert len(pb) == 1, "tenant B's first-touch must write a policy"
    # And neither tenant's capture sees the other's cache.
    assert jid in capture_a.seen_channels
    assert jid in capture_b.seen_channels


# ---------------------------------------------------------------------------
# A2.5 — Pre-existing policy short-circuits the write (admin override case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_policy_in_ledger_short_circuits_first_admit(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """An admin may have set the channel to ``proactive`` via /channels POST
    before the first wire-side admit. The capture's ledger fold must
    discover that prior entry and skip the defensive lurker write — we
    must not stomp on an admin's posture.
    """
    capture, _adapter = await _build_capture(writer, company_id)
    jid = "5511777777777@s.whatsapp.net"

    # Pre-seed the ledger with a proactive policy (admin override).
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "policy_applied",
            "ref_id": str(uuid4()),
            "reason": "admin override: raise WA channel to proactive",
            "proposed_by": "test-admin",
        },
        execute_fn=lambda: {
            "tool": "emit_policy_applied",
            "args": {
                "policy_id": str(uuid4()),
                "policy_name": "policy:channel_talkativeness",
                "applies_to": {"scope": "channel", "channel_id": jid},
                "rule": "admin: proactive",
                "gate_impl": "channel_talkativeness_default",
                "talkativeness": "proactive",
                "daily_interjection_budget": 5,
            },
            "result_ref": jid,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "applied", "rationale": "admin override",
        },
        timestamp=datetime.now(timezone.utc),
        quadrant="active_deterministic",
    )

    await capture.on_channel_admit(jid)

    rows = await ledger.fetch(company_id)
    policies = _talkativeness_executes(rows, jid)
    # Still exactly one — the admin's proactive entry — not two (admin + lurker).
    assert len(policies) == 1
    assert policies[0]["payload"]["args"]["talkativeness"] == "proactive"
    # Cache populated regardless (so the fast-path triggers next time).
    assert jid in capture.seen_channels


# ---------------------------------------------------------------------------
# A2.6 — _ensure_default_policy runs BEFORE fetch_latest_and_normalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_written_even_when_message_fetch_returns_none(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """A WhatsApp admit with no cached message should still write the
    defensive policy. The chat_received path is gated on the adapter
    returning an InfraEvent; the policy path must not be.
    """
    capture, _adapter = await _build_capture(writer, company_id)

    # No injected message — adapter returns None.
    jid = "5511666666666@s.whatsapp.net"
    await capture.on_channel_admit(jid)

    rows = await ledger.fetch(company_id)
    policies = _talkativeness_executes(rows, jid)
    assert len(policies) == 1, (
        "policy_applied must be written even when no message is available"
    )
    # And no chat_received was emitted (defensive, not a regression).
    chat_executes = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    ]
    assert chat_executes == []


# ---------------------------------------------------------------------------
# A2.7 — distinct channels in the same tenant each get their own policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distinct_channels_each_get_own_policy(
    writer: LedgerWriter, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    capture, _adapter = await _build_capture(writer, company_id)

    jid_a = "5511111111111@s.whatsapp.net"
    jid_b = "5512222222222@s.whatsapp.net"
    await capture.on_channel_admit(jid_a)
    await capture.on_channel_admit(jid_b)

    rows = await ledger.fetch(company_id)
    assert len(_talkativeness_executes(rows, jid_a)) == 1
    assert len(_talkativeness_executes(rows, jid_b)) == 1
    assert jid_a in capture.seen_channels
    assert jid_b in capture.seen_channels
