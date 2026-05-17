"""Multi-tenant per-account verification for WhatsApp (Wave E4).

OpenClaw config supports ``channels.whatsapp.accounts.<tenant>`` already
(Phase 2 of yesterday + this morning's E4 prerequisites). This test pins
that the WhatsApp adapter + writer + identity-discovery Reactivity all
resolve per-tenant correctly: two tenants with different bot phones must
produce separate Install entries, separate ``chat_received`` rows tagged
with their own ``company_id``, separate ``conversation_sync`` lineage,
separate Person proposals, and separate rate-limit buckets.

The test exercises the **real adapter** (one ``WhatsAppChannelAdapter``
instance per tenant) with fakes only at the writer/emitter boundary
(in-memory ledger, no HTTP transport). Determinism: short
``sync_quiet_window_s``, fake clock, and the well-known env-var
convention ``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UUID_UPPER>`` /
``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_SLUG_UPPER>`` that B1+B3+E2 all
honor (we set both to keep the test working under either resolution
order — see B1.1's status note for the dual-convention rationale).

What the test does NOT cover (out of scope per the plan §3 E4 dispatch):
  * Live OpenClaw transport — fakes only at writer + HTTP boundary.
  * Identity-merge across tenants — per CLAUDE.md §4, identity merge is
    admin-driven and explicitly NOT automatic; the same sender jid in two
    tenants surfaces as TWO distinct Person proposals.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter
from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)
from wormbase_channel_adapters.whatsapp_rate_limit import (
    RateLimitTimeoutError,
    TokenBucketRateLimiter,
    _LIMITER_REGISTRY,
    _bucket_key,
    reset_throttle_session_for_tests,
)
from wormbase_identity_tracker.whatsapp_discovery import (
    WhatsAppOrganicDiscoveryReactivity,
)
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner


# Tenant A.
_TENANT_A = "tenant_a"
_COMPANY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_BOT_A_PHONE = "15551112222"
_BOT_A_JID = f"{_BOT_A_PHONE}@s.whatsapp.net"

# Tenant B.
_TENANT_B = "tenant_b"
_COMPANY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_BOT_B_PHONE = "15553334444"
_BOT_B_JID = f"{_BOT_B_PHONE}@s.whatsapp.net"

# Quiet-window short enough to keep the test under 1s wall-clock.
_QUIET_WINDOW_S = 0.05
_TIMER_SETTLE_S = 0.15


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _baileys(
    *,
    msg_id: str,
    sender_jid: str,
    body: str = "x",
    ts_unix: int | None = None,
) -> dict[str, Any]:
    """Build a minimal Baileys message envelope (DM shape)."""
    if ts_unix is None:
        ts_unix = int(datetime.now(UTC).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": sender_jid, "fromMe": False},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


def _executes(rows: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


def _set_tenant_envs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant_slug: str,
    company_id: UUID,
    bot_phone: str,
) -> None:
    """Set BOTH env-var conventions so adapter resolution succeeds.

    B1's ``MentionsWorm`` predicate scopes by ``company_id`` (UUID,
    uppercased). B3 / B4 / E2 ``WhatsAppChannelAdapter`` scopes by
    ``tenant_id`` slug (uppercased). Setting both is the dual-convention
    workaround pinned by ``test_whatsapp_mention_e2e.py`` (B1.1's e2e).
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(company_id).upper()}", bot_phone,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{tenant_slug.upper()}", bot_phone,
    )


async def _seed_chat_received_with_platform(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform_user_id: str,
    channel_id: str,
    text: str = "hi",
) -> None:
    """Seed a chat_received entry shaped to fire WhatsApp identity discovery.

    The production writer drops ``platform`` / ``platform_user_id`` from
    args (they're not in :class:`ChatReceivedPayload`), so to exercise
    the discovery Reactivity we seed the row with those fields injected
    — same shape as the existing
    ``packages/wormbase-identity-tracker/tests/test_whatsapp_identity_discovery.py``
    helper. This keeps the discovery-isolation assertion independent of
    a future writer upgrade that would persist them.
    """
    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=str(uuid4()),
        sender_person=uuid4(),
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    args["platform"] = "whatsapp"
    args["platform_user_id"] = platform_user_id

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": args["message_id"],
            "reason": "test seed (multi-tenant identity)",
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


async def _drive_discovery_for_company(
    ledger: InMemoryLedger,
    company_id: UUID,
    reactivity: WhatsAppOrganicDiscoveryReactivity,
) -> None:
    """Run the identity-discovery Reactivity once over a company's ledger."""
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(reactivity)
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


def _person_proposals_for_company(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter ``emit_person_proposed`` rows from a company's ledger view."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == "emit_person_proposed":
            out.append(r)
    return out


@pytest.fixture(autouse=True)
def _reset_rate_limit_globals() -> Any:
    """Drop the module-level rate-limit registry before/after each test.

    The registry is a process-global by design (one limiter per
    rate-per-min); without a reset, prior tests' buckets bleed into this
    test's tenant-isolation assertions.
    """
    _LIMITER_REGISTRY.clear()
    yield
    _LIMITER_REGISTRY.clear()


@pytest.fixture(autouse=True)
def _clean_whatsapp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any pre-existing WORMBASE_WHATSAPP_* env vars per-test."""
    import os
    for name in list(os.environ.keys()):
        if name.startswith("WORMBASE_WHATSAPP_"):
            monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# 1. Two tenants pair simultaneously + receive distinct messages — the
#    big multi-tenant isolation pin
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_tenants_pair_and_ingest_without_cross_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant A and Tenant B pair concurrently and each receive 5 messages.

    Asserts (per the E4 contract):
      * Each tenant's ledger has exactly 1 ``install_completed`` entry,
        with ``bot_user_id`` matching THAT tenant's bot jid (and NOT the
        other tenant's).
      * Each tenant's ``chat_received`` entries are scoped to the right
        company_id; no cross-leakage in either direction.
      * Each tenant's ``conversation_sync`` references its own
        ``install_id`` (not the other tenant's).
      * Each adapter holds its own state machine instance — tenant A's
        machine completes its sync independently of tenant B's.
    """
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_A,
        company_id=_COMPANY_A,
        bot_phone=_BOT_A_PHONE,
    )
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_B,
        company_id=_COMPANY_B,
        bot_phone=_BOT_B_PHONE,
    )

    # Single shared in-memory ledger holding both tenants' rows. Per
    # InMemoryLedger semantics (``_entries`` is keyed by company_id),
    # cross-tenant leakage would surface as a row in the wrong company's
    # fetch slice — exactly what we assert against.
    ledger = InMemoryLedger()
    writer_a = LedgerWriter(ledger, _COMPANY_A)
    writer_b = LedgerWriter(ledger, _COMPANY_B)

    # Per-tenant adapter. install_id (== OpenClaw account_id) is distinct
    # so we can pin "tenant A's conversation_sync references account_a,
    # not account_b."
    adapter_a = WhatsAppChannelAdapter(
        sync_emitter=writer_a.emit_conversation_sync,
        install_emitter=writer_a.emit_whatsapp_install,
        install_id="account_a",
        tenant_id=_TENANT_A,
        sync_quiet_window_s=_QUIET_WINDOW_S,
    )
    adapter_b = WhatsAppChannelAdapter(
        sync_emitter=writer_b.emit_conversation_sync,
        install_emitter=writer_b.emit_whatsapp_install,
        install_id="account_b",
        tenant_id=_TENANT_B,
        sync_quiet_window_s=_QUIET_WINDOW_S,
    )

    handle_a = await adapter_a.authenticate(
        SecretBundle(payload={"account_id": "account_a", "tenant_id": _TENANT_A})
    )
    handle_b = await adapter_b.authenticate(
        SecretBundle(payload={"account_id": "account_b", "tenant_id": _TENANT_B})
    )
    # Per-adapter state-machine instance check: distinct objects.
    assert adapter_a is not adapter_b
    assert adapter_a.state == _WhatsAppSyncState.IDLE
    assert adapter_b.state == _WhatsAppSyncState.IDLE

    # ------------------------------------------------------------------
    # Both tenants pair simultaneously (synthetic connection_open).
    # ------------------------------------------------------------------
    await asyncio.gather(
        adapter_a.on_connection_open(trigger="initial_connect"),
        adapter_b.on_connection_open(trigger="initial_connect"),
    )
    assert adapter_a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    assert adapter_b.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    # ------------------------------------------------------------------
    # 5 distinct senders per tenant; every sender is a unique DM jid.
    # ------------------------------------------------------------------
    senders_a = [f"5511{i:09d}@s.whatsapp.net" for i in range(5)]
    senders_b = [f"4477{i:09d}@s.whatsapp.net" for i in range(5)]

    async def _drive_one(
        adapter: WhatsAppChannelAdapter,
        writer: LedgerWriter,
        handle: Any,
        *,
        sender_jid: str,
        msg_id: str,
    ) -> None:
        adapter.inject_message(
            sender_jid,
            _baileys(msg_id=msg_id, sender_jid=sender_jid, body="hi"),
        )
        event = await adapter.fetch_latest_and_normalize(handle, sender_jid)
        if event is None:
            return
        # Mirror service.WhatsAppLogCapture.on_channel_admit's writer-call
        # shape: build a ChatReceivedEvent and emit through the writer.
        from wormbase_channel_adapter.parser import ChatReceivedEvent
        chat_event = ChatReceivedEvent(
            kind="chat_received",
            session_id=sender_jid,
            event_id=event.platform_message_id or msg_id,
            ts=event.ts,
            channel_id=sender_jid,
            message_id=event.platform_message_id or msg_id,
            sender_id=event.platform_user_id or "",
            sender_label=None,
            text=event.text,
            conversation_label=None,
            delivery_mode=event.delivery_mode,
            platform_ts=event.platform_ts,
            history_sync_id=event.history_sync_id,
            mentioned_jids=event.mentioned_jids,
        )
        await writer.emit(chat_event)

    # Drive 5 messages for each tenant, interleaved so a real-world
    # concurrent scenario is exercised.
    for i in range(5):
        await _drive_one(
            adapter_a, writer_a, handle_a,
            sender_jid=senders_a[i], msg_id=f"A-MSG-{i}",
        )
        await _drive_one(
            adapter_b, writer_b, handle_b,
            sender_jid=senders_b[i], msg_id=f"B-MSG-{i}",
        )

    # Wait past the quiet window so both state machines flip
    # SYNC_IN_PROGRESS → LIVE and write their conversation_sync.
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter_a.state == _WhatsAppSyncState.LIVE
    assert adapter_b.state == _WhatsAppSyncState.LIVE

    # ------------------------------------------------------------------
    # Per-tenant ledger reads — these are the cross-leakage assertions.
    # ------------------------------------------------------------------
    rows_a = await ledger.fetch(_COMPANY_A)
    rows_b = await ledger.fetch(_COMPANY_B)

    # 1. install_completed: exactly one per tenant, bot_jid is THIS
    #    tenant's, NOT the other's.
    install_a = _executes(rows_a, "emit_install_completed")
    install_b = _executes(rows_b, "emit_install_completed")
    assert len(install_a) == 1, (
        f"tenant A: expected exactly 1 install_completed, got {len(install_a)}"
    )
    assert len(install_b) == 1, (
        f"tenant B: expected exactly 1 install_completed, got {len(install_b)}"
    )
    install_a_args = install_a[0]["payload"]["args"]
    install_b_args = install_b[0]["payload"]["args"]
    assert install_a_args["bot_user_id"] == _BOT_A_JID
    assert install_a_args["bot_user_id"] != _BOT_B_JID, (
        "tenant A's install carries tenant B's bot_jid — CROSS-TENANT LEAK"
    )
    assert install_b_args["bot_user_id"] == _BOT_B_JID
    assert install_b_args["bot_user_id"] != _BOT_A_JID, (
        "tenant B's install carries tenant A's bot_jid — CROSS-TENANT LEAK"
    )
    assert install_a_args["platform"] == "whatsapp"
    assert install_b_args["platform"] == "whatsapp"

    # 2. chat_received: 5 per tenant, EVERY entry's company_id matches
    #    THIS tenant's UUID (the InMemoryLedger keys by company_id, so a
    #    cross-leak would be a row with the wrong company_id appearing
    #    in the wrong slice).
    chat_a = _executes(rows_a, "channel_adapter.emit_chat_received")
    chat_b = _executes(rows_b, "channel_adapter.emit_chat_received")
    assert len(chat_a) == 5, f"tenant A: expected 5 chat_received, got {len(chat_a)}"
    assert len(chat_b) == 5, f"tenant B: expected 5 chat_received, got {len(chat_b)}"

    for r in chat_a:
        assert r["company_id"] == _COMPANY_A, (
            f"tenant A row carries wrong company_id: {r['company_id']}"
        )
    for r in chat_b:
        assert r["company_id"] == _COMPANY_B, (
            f"tenant B row carries wrong company_id: {r['company_id']}"
        )
    # Cross-check: tenant A's channel_ids are ALL in senders_a, none in senders_b.
    a_channels = {r["payload"]["args"]["channel_id"] for r in chat_a}
    b_channels = {r["payload"]["args"]["channel_id"] for r in chat_b}
    assert a_channels == set(senders_a)
    assert b_channels == set(senders_b)
    assert a_channels.isdisjoint(b_channels), (
        "tenant A and B share a channel_id in their ledgers — CROSS-TENANT LEAK"
    )

    # 3. conversation_sync: each tenant's sync references its own
    #    install_id (the str the writer threads in from
    #    adapter._install_id).
    sync_a = _executes(rows_a, "channel_adapter.emit_conversation_sync")
    sync_b = _executes(rows_b, "channel_adapter.emit_conversation_sync")
    assert len(sync_a) == 1
    assert len(sync_b) == 1
    sync_a_args = sync_a[0]["payload"]["args"]
    sync_b_args = sync_b[0]["payload"]["args"]
    assert sync_a_args["install_id"] == "account_a"
    assert sync_a_args["install_id"] != "account_b", (
        "tenant A's sync references tenant B's install_id — CROSS-TENANT LEAK"
    )
    assert sync_b_args["install_id"] == "account_b"
    assert sync_b_args["install_id"] != "account_a", (
        "tenant B's sync references tenant A's install_id — CROSS-TENANT LEAK"
    )
    # Each tenant's conversation_sync covers its own senders only.
    assert set(sync_a_args["channels"]) == set(senders_a)
    assert set(sync_b_args["channels"]) == set(senders_b)
    assert sync_a_args["message_count"] == 5
    assert sync_b_args["message_count"] == 5

    # 4. State machines are distinct instances — neither shared nor
    #    cross-talking. Adapter A holding LIVE doesn't depend on B; both
    #    completed independently above. Pin the property identity.
    assert adapter_a is not adapter_b
    # Different sync_ids prove the sync-session UUIDs are independent.
    assert sync_a_args["sync_id"] != sync_b_args["sync_id"]

    await adapter_a.shutdown()
    await adapter_b.shutdown()


# --------------------------------------------------------------------------
# 2. Same sender jid in both tenants → two distinct Person proposals
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_sender_jid_in_two_tenants_yields_two_distinct_persons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sender phone in BOTH tenants surfaces as TWO distinct Person proposals.

    Per CLAUDE.md §4, ``PersonIdentity`` rows are tenant-scoped and
    identity merge is **admin-driven, not automatic**. The discovery
    Reactivity must propose one Person per (tenant, jid), even when the
    jid is identical across tenants.

    Test approach: the production writer doesn't persist
    ``platform``/``platform_user_id`` on chat_received args (they're
    NOT in :class:`ChatReceivedPayload`). To exercise the discovery
    Reactivity, we seed chat_received rows with those fields explicitly
    injected — same shape as the existing
    ``test_whatsapp_identity_discovery.py`` seeder. The discovery
    Reactivity's ledger-fold safety net is company-scoped via
    ``ledger.fetch(company_id)``, so even if the same Reactivity
    instance is used across both tenants, the per-tenant fold
    correctly enumerates only THAT tenant's prior proposals.
    """
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_A,
        company_id=_COMPANY_A,
        bot_phone=_BOT_A_PHONE,
    )
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_B,
        company_id=_COMPANY_B,
        bot_phone=_BOT_B_PHONE,
    )

    ledger = InMemoryLedger()

    # Same sender jid in both tenants.
    shared_sender_jid = "15559998888@s.whatsapp.net"

    # Seed a chat_received in EACH tenant from the same jid.
    await _seed_chat_received_with_platform(
        ledger, _COMPANY_A,
        platform_user_id=shared_sender_jid,
        channel_id=shared_sender_jid,
        text="hi tenant A",
    )
    await _seed_chat_received_with_platform(
        ledger, _COMPANY_B,
        platform_user_id=shared_sender_jid,
        channel_id=shared_sender_jid,
        text="hi tenant B",
    )

    # Drive identity discovery once per tenant. Use a single shared
    # Reactivity instance to model the production case where one
    # WhatsAppOrganicDiscoveryReactivity is registered against a
    # registry that runs both companies' fires (in production each
    # company has its own registry; the cache is per-instance, keyed
    # by ``(company_id_str, jid_str)`` per the discovery module). The
    # ledger-fold safety net is the cross-tenant guarantee.
    reactivity = WhatsAppOrganicDiscoveryReactivity()
    await _drive_discovery_for_company(ledger, _COMPANY_A, reactivity)
    await _drive_discovery_for_company(ledger, _COMPANY_B, reactivity)

    rows_a = await ledger.fetch(_COMPANY_A)
    rows_b = await ledger.fetch(_COMPANY_B)
    proposals_a = _person_proposals_for_company(rows_a)
    proposals_b = _person_proposals_for_company(rows_b)

    assert len(proposals_a) == 1, (
        f"tenant A: expected exactly 1 Person proposal, got {len(proposals_a)}"
    )
    assert len(proposals_b) == 1, (
        f"tenant B: expected exactly 1 Person proposal, got {len(proposals_b)}"
    )
    a_args = proposals_a[0]["payload"]["args"]
    b_args = proposals_b[0]["payload"]["args"]
    assert a_args["platform"] == "whatsapp"
    assert b_args["platform"] == "whatsapp"
    assert a_args["platform_user_id"] == shared_sender_jid
    assert b_args["platform_user_id"] == shared_sender_jid

    # CLAUDE.md §4 invariant: distinct Person UUIDs across tenants. The
    # write_actions.propose_person path mints a fresh person_id per call
    # (it's not derived from the jid), so two proposals = two UUIDs.
    a_pid = a_args["person_id"]
    b_pid = b_args["person_id"]
    assert a_pid != b_pid, (
        "same sender jid in two tenants got merged into one person_id — "
        "violates CLAUDE.md §4 (PersonIdentity tenant-scoping; identity "
        "merge is admin-driven not automatic)"
    )

    # Each Person row's tenant_id matches its own company.
    assert UUID(a_args["tenant_id"]) == _COMPANY_A
    assert UUID(b_args["tenant_id"]) == _COMPANY_B

    # Cross-leakage guard: tenant A's ledger does NOT contain B's pid
    # and vice versa.
    a_pid_set = {p["payload"]["args"]["person_id"] for p in proposals_a}
    b_pid_set = {p["payload"]["args"]["person_id"] for p in proposals_b}
    assert a_pid_set.isdisjoint(b_pid_set)


# --------------------------------------------------------------------------
# 3. Rate-limit isolation: tenant A throttled, tenant B unaffected
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_buckets_are_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant A's bucket consumed → tenant B's send still acquires a token.

    Per E2's bucket-key contract (``<tenant>:<phone>``), each tenant has
    an independent token bucket. Draining tenant A's must NOT spill into
    tenant B's. Pinned by exhausting A's bucket via ``try_acquire`` and
    then verifying B's bucket still has full capacity.

    We exercise the actual ``with_whatsapp_rate_limit`` decorator that
    ``WhatsAppChannelAdapter.send`` uses (bucket_key resolution is
    identical), but at the limiter primitive layer so the test stays
    fast and deterministic — no rate-limit retries, no policy_applied
    emit (those are E2's tests, not E4's).
    """
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_A,
        company_id=_COMPANY_A,
        bot_phone=_BOT_A_PHONE,
    )
    _set_tenant_envs(
        monkeypatch,
        tenant_slug=_TENANT_B,
        company_id=_COMPANY_B,
        bot_phone=_BOT_B_PHONE,
    )

    # The two adapters resolve to the same limiter (same default rate
    # 5/min) but DIFFERENT bucket keys.
    bucket_a_key = _bucket_key(_TENANT_A, _BOT_A_PHONE)
    bucket_b_key = _bucket_key(_TENANT_B, _BOT_B_PHONE)
    assert bucket_a_key != bucket_b_key
    assert bucket_a_key == f"{_TENANT_A}:{_BOT_A_PHONE}"
    assert bucket_b_key == f"{_TENANT_B}:{_BOT_B_PHONE}"

    # Use a shared limiter (matches the production shape: one limiter
    # per rate, many keys) with a pinned clock to avoid flakiness.
    now = [0.0]
    limiter = TokenBucketRateLimiter(
        rate_per_min=5, clock=lambda: now[0],
    )
    # Drain A's bucket to zero. Default capacity is 5 (= rate_per_min).
    for i in range(5):
        ok = await limiter.try_acquire(bucket_a_key)
        assert ok is True, f"tenant A acquire #{i + 1} unexpectedly failed"
    # 6th acquire on A → bucket empty.
    assert await limiter.try_acquire(bucket_a_key) is False, (
        "tenant A bucket should be empty after 5 consecutive acquires"
    )

    # Tenant B's bucket is FRESH — independent of A's.
    for i in range(5):
        ok = await limiter.try_acquire(bucket_b_key)
        assert ok is True, (
            f"tenant B acquire #{i + 1} failed — bucket leaked across tenants "
            "(violates E2's <tenant>:<phone> bucket-key contract)"
        )
    # B's 6th is also rate-limited (its own bucket drains independently).
    assert await limiter.try_acquire(bucket_b_key) is False, (
        "tenant B's bucket did not drain after its own 5 acquires"
    )

    # ------------------------------------------------------------------
    # Now verify the SAME isolation holds end-to-end through the real
    # adapter's send path — the decorator on adapter.send resolves to
    # ``<tenant>:<phone>`` keys via ``_bucket_key``. Two distinct
    # adapters must hit two distinct limiter keys.
    # ------------------------------------------------------------------
    adapter_a = WhatsAppChannelAdapter(tenant_id=_TENANT_A)
    adapter_b = WhatsAppChannelAdapter(tenant_id=_TENANT_B)
    handle_a = await adapter_a.authenticate(SecretBundle(
        payload={"account_id": "account_a", "tenant_id": _TENANT_A},
    ))
    handle_b = await adapter_b.authenticate(SecretBundle(
        payload={"account_id": "account_b", "tenant_id": _TENANT_B},
    ))

    captured_keys: list[str] = []
    original_acquire = TokenBucketRateLimiter.acquire

    async def spy_acquire(
        self: TokenBucketRateLimiter,
        key: str,
        *,
        max_wait_s: float | None = None,
    ) -> None:
        captured_keys.append(key)
        return await original_acquire(self, key, max_wait_s=max_wait_s)

    monkeypatch.setattr(TokenBucketRateLimiter, "acquire", spy_acquire)

    channel_a = ChannelRef(
        platform="whatsapp",
        platform_channel_id="15559990001@s.whatsapp.net",
    )
    channel_b = ChannelRef(
        platform="whatsapp",
        platform_channel_id="15559990002@s.whatsapp.net",
    )

    # Wave C2 wired _do_send via OpenClaw CLI subprocess. To keep this
    # multi-tenant rate-limit test hermetic (no docker dependency), we
    # use the WORMBASE_WHATSAPP_SEND_DISABLE kill-switch — _do_send
    # raises NotImplementedError synchronously, but only AFTER the
    # rate-limit acquire. The limiter contract we're verifying is
    # "buckets are tenant-scoped", which is independent of the inner
    # send body shape.
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")
    with pytest.raises(NotImplementedError):
        await adapter_a.send(handle_a, channel_a, OutMessage(text="from A"))
    with pytest.raises(NotImplementedError):
        await adapter_b.send(handle_b, channel_b, OutMessage(text="from B"))

    # Two distinct keys captured, in order. Pin both individually + the
    # set-level disjointness for clear failure modes.
    assert len(captured_keys) == 2, (
        f"expected 2 acquire calls (one per send), got {captured_keys!r}"
    )
    assert captured_keys[0] == bucket_a_key
    assert captured_keys[1] == bucket_b_key
    assert captured_keys[0] != captured_keys[1], (
        "tenant A and B used the same rate-limit key — "
        "violates <tenant>:<phone> bucket-key contract"
    )

    # Cleanup: drop any throttle-session state to avoid leaking between
    # parallel test runs.
    await reset_throttle_session_for_tests(_TENANT_A, _BOT_A_PHONE)
    await reset_throttle_session_for_tests(_TENANT_B, _BOT_B_PHONE)
