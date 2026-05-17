"""Tests for WhatsApp Install detection on pairing-complete (Wave B3).

Slack writes an Install entity from an OAuth grant
(``apps/worm-core/src/wormbase_core/write_actions.py::complete_install``).
WhatsApp has no OAuth — its pairing-complete signal is Baileys'
``connection_open`` after a successful QR scan. This wave wires that
signal: on the FIRST ``on_connection_open`` per ``(tenant_id, bot_jid)``,
the adapter invokes a constructor-injected ``install_emitter`` so an
Install ledger entry lands. Subsequent ``connection_open`` events on
the same warm process are no-ops (cache hit); cache wraparound is
caught by the emitter's ledger fold (production-side; mirrored by
``_FoldingEmitter`` in these tests).

The plan locks the metadata shape:

* ``pairing_method="qr"``
* ``paired_at=<utc tz-aware datetime>`` (adapter's clock)
* ``provider="openclaw_baileys"``
* ``creds_path=<descriptive container path>`` — NOT credential material

Tenant scoping for bot-jid resolution mirrors B1 / B4: read
``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>`` first, fall back to
``WORMBASE_WHATSAPP_BOT_PHONE`` for single-tenant deployments.

NB: Slack's Install path is intentionally NOT touched by this wave;
the no-regression contract is enforced indirectly by leaving
``install_emitter`` unset on adapters that don't pair (the default).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)


_TENANT = "baseworm"
_OTHER_TENANT = "acme"
_BOT_PHONE = "5511888888888"
_BOT_JID = f"{_BOT_PHONE}@s.whatsapp.net"
_OTHER_BOT_PHONE = "5511777777777"
_OTHER_BOT_JID = f"{_OTHER_BOT_PHONE}@s.whatsapp.net"
_ACCOUNT_ID = "wa-1"


class _CaptureInstallEmitter:
    """Test stand-in for ``LedgerWriter.emit_whatsapp_install``.

    Records every invocation's kwargs. NOT idempotent at the ledger
    level — used to verify the adapter's in-process cache contract
    only. For ledger-fold safety net coverage, see
    :class:`_FoldingInstallEmitter`.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _FoldingInstallEmitter:
    """Test stand-in that simulates the production emitter's ledger fold.

    Tracks emitted ``(tenant_id, bot_jid)`` pairs internally and skips
    re-writing on a duplicate. Models what the real
    ``LedgerWriter.emit_whatsapp_install`` does (in-process cache +
    ledger fold). Used to test the cache-cleared safety net.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self._fold: set[tuple[str | None, str]] = set()

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        key = (kwargs.get("tenant_id"), kwargs["bot_jid"])
        if key in self._fold:
            # Ledger-fold says "we already wrote this install" → no-op.
            return
        self._fold.add(key)
        self.writes.append(kwargs)


def _drain_clock_to_iso(dt_obj: datetime) -> str:
    """Sanity helper: ensure tz-aware datetime serializes cleanly."""
    assert dt_obj.tzinfo is not None
    return dt_obj.isoformat()


# --------------------------------------------------------------------------
# 1. First connection_open writes an Install entry with the locked metadata
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_connection_open_writes_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pairing-complete signal → emitter called once with full metadata."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    emitter = _CaptureInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")

    assert len(emitter.calls) == 1
    call = emitter.calls[0]
    # Identity
    assert call["tenant_id"] == _TENANT
    assert call["bot_jid"] == _BOT_JID
    assert call["account_id"] == _ACCOUNT_ID
    # Locked metadata shape (plan §3 B3)
    assert call["pairing_method"] == "qr"
    assert call["provider"] == "openclaw_baileys"
    paired_at = call["paired_at"]
    assert isinstance(paired_at, datetime)
    assert paired_at.tzinfo is not None  # UTC tz-aware
    # Descriptive only — must reference the OpenClaw mount, not creds material
    creds_path = call["creds_path"]
    assert isinstance(creds_path, str)
    assert "openclaw" in creds_path.lower()
    assert "creds" in creds_path.lower()
    # No raw credential material smuggled in
    assert "BEGIN PRIVATE" not in creds_path
    assert "AKIA" not in creds_path  # AWS key prefix sanity-check

    # Cache reflects the install
    assert (_TENANT, _BOT_JID) in a.seen_installs

    # State-machine transition still happens (install runs alongside, not instead)
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS


# --------------------------------------------------------------------------
# 2. Reconnect (second connection_open, same bot) → no double-install
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_does_not_double_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second ``connection_open`` with creds preserved → cache hit, no re-emit."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    emitter = _CaptureInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")
    assert len(emitter.calls) == 1

    # Drop and reconnect: simulate the production reconnect storm.
    await a.on_connection_drop()
    await a.on_connection_open(trigger="reconnect")

    # No double-install — cache hit on second open
    assert len(emitter.calls) == 1


# --------------------------------------------------------------------------
# 3. Cache-cleared, install already in ledger → no double-install
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_cleared_with_existing_ledger_entry_does_not_double_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter cache cleared (process restart) + emitter's ledger fold → no double-write.

    Models the production posture where:
    * a worm restarts, losing its in-process LRU,
    * but the ledger still carries the prior ``install_completed`` entry,
    * so the emitter's fold absorbs the second invocation as a no-op.

    The adapter is the fast path; the emitter is the source of truth.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    emitter = _FoldingInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")
    assert len(emitter.writes) == 1
    assert len(emitter.calls) == 1

    # Simulate process restart: cache lost, ledger preserved.
    a.clear_seen_installs()
    assert a.seen_installs == set()

    await a.on_connection_drop()
    await a.on_connection_open(trigger="reconnect")

    # Emitter was invoked again (cache miss after clear)…
    assert len(emitter.calls) == 2
    # …but the fold absorbed it — no second ledger write.
    assert len(emitter.writes) == 1


# --------------------------------------------------------------------------
# 4. Multi-tenant: same bot_jid in different tenants → separate installs
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_tenant_same_bot_jid_separate_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tenants share the same bot phone → installs are tenant-scoped."""
    # Same phone in both tenant envs.
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_OTHER_TENANT.upper()}", _BOT_PHONE,
    )

    # In production each tenant has its own adapter instance — we
    # mirror that here. The fold is also tenant-scoped (the production
    # `LedgerWriter` is per-`company_id`); _FoldingInstallEmitter
    # implements the same contract with `(tenant_id, bot_jid)` keys.
    fold = _FoldingInstallEmitter()
    a1 = WhatsAppChannelAdapter(
        install_emitter=fold,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )
    a2 = WhatsAppChannelAdapter(
        install_emitter=fold,
        install_id="wa-2",
        tenant_id=_OTHER_TENANT,
    )

    await a1.on_connection_open(trigger="initial_connect")
    await a2.on_connection_open(trigger="initial_connect")

    # Two separate writes — one per tenant, even with same bot_jid.
    assert len(fold.writes) == 2
    tenants = {w["tenant_id"] for w in fold.writes}
    assert tenants == {_TENANT, _OTHER_TENANT}
    bot_jids = {w["bot_jid"] for w in fold.writes}
    assert bot_jids == {_BOT_JID}  # both tenants paired the same phone


# --------------------------------------------------------------------------
# 5. Same tenant, different bot_jid (re-paired with new phone) → new install
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_tenant_new_bot_jid_writes_new_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator re-pairs with a new phone → new install entry written.

    Models the runbook: ``creds.json`` rotation when a tenant changes
    its bot device. The adapter's cache key is
    ``(tenant_id, bot_jid)``, so a different jid registers as a fresh
    pairing — second install lands.
    """
    # Start with phone A.
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    fold = _FoldingInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=fold,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")
    assert len(fold.writes) == 1
    assert fold.writes[0]["bot_jid"] == _BOT_JID

    # Operator re-pairs with phone B (rotated env).
    await a.on_connection_drop()
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _OTHER_BOT_PHONE,
    )

    await a.on_connection_open(trigger="initial_connect")

    # Second install written for the new jid.
    assert len(fold.writes) == 2
    assert fold.writes[1]["bot_jid"] == _OTHER_BOT_JID

    # Both pairings cached.
    assert (_TENANT, _BOT_JID) in a.seen_installs
    assert (_TENANT, _OTHER_BOT_JID) in a.seen_installs


# --------------------------------------------------------------------------
# 6. Graceful failure: connection_open with no bot phone env → no install
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_open_without_bot_phone_does_not_install(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Bot phone env unset → graceful skip; warning logged; no emitter call.

    Without a resolvable bot jid, we can't write an Install entry whose
    ``bot_user_id`` is meaningful. The adapter logs a warning and
    continues without installing (the next ``connection_open`` after
    the operator sets the env will retry). State-machine transition
    is unaffected.
    """
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    emitter = _CaptureInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    import logging
    with caplog.at_level(logging.WARNING):
        await a.on_connection_open(trigger="initial_connect")

    # Emitter NOT called.
    assert emitter.calls == []
    # Cache NOT marked seen — next open will retry.
    assert a.seen_installs == set()
    # State-machine transition still happened.
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    # Warning surfaced about env config.
    assert any(
        "bot phone env unset" in rec.message
        for rec in caplog.records
    )


# --------------------------------------------------------------------------
# 7. No emitter wired → adapter remains backward-compatible
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_install_emitter_wired_is_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter constructed without ``install_emitter`` works byte-identical.

    The state-machine tests in test_whatsapp_sync_state_machine.py
    pre-date B3 and don't pass an install_emitter; B3 must not break
    them. Verifies no emitter wired → install detection is a silent
    no-op, the cache stays empty, and the state machine still flips
    IDLE → SYNC_IN_PROGRESS.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = WhatsAppChannelAdapter(
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )  # no install_emitter

    await a.on_connection_open(trigger="initial_connect")

    # Cache empty (no emitter to cache against).
    assert a.seen_installs == set()
    # State machine flipped normally.
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS


# --------------------------------------------------------------------------
# 8. Emitter raises → adapter does not mark seen, retries on next open
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emitter_failure_does_not_mark_seen(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """If the emitter raises, the cache is NOT updated → next open retries.

    Mirrors A2's "don't mark seen on failure" posture
    (WhatsAppLogCapture._ensure_default_policy in service.py).
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    fail_count = 0

    async def flaky_emitter(**_kwargs: Any) -> None:
        nonlocal fail_count
        fail_count += 1
        if fail_count == 1:
            raise RuntimeError("simulated ledger flake")

    a = WhatsAppChannelAdapter(
        install_emitter=flaky_emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    import logging
    with caplog.at_level(logging.WARNING):
        await a.on_connection_open(trigger="initial_connect")

    # First call raised → cache empty, retry possible.
    assert a.seen_installs == set()
    assert any(
        "install_emitter failed" in rec.message
        for rec in caplog.records
    )

    # State still flipped — install failure does NOT block the machine.
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    # Second open (after a drop) → emitter retried, succeeds, cache marked.
    await a.on_connection_drop()
    await a.on_connection_open(trigger="reconnect")

    assert (_TENANT, _BOT_JID) in a.seen_installs
    assert fail_count == 2  # second invocation succeeded


# --------------------------------------------------------------------------
# 9. Single-tenant fallback env works
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_env_fallback_resolves_bot_jid_for_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant-scoped env unset, global ``WORMBASE_WHATSAPP_BOT_PHONE`` set
    → install still fires with the correct bot_jid. Mirrors B1/B4
    fallback semantics.
    """
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _BOT_PHONE)

    emitter = _CaptureInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")

    assert len(emitter.calls) == 1
    assert emitter.calls[0]["bot_jid"] == _BOT_JID


# --------------------------------------------------------------------------
# 10. ``connection_open`` is idempotent within a single sync session
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_connection_open_in_sync_state_does_not_double_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated ``on_connection_open`` while SYNC_IN_PROGRESS → still 1 install.

    Phase 3's state-machine semantics: re-entering SYNC_IN_PROGRESS is
    a no-op. The B3 install path runs BEFORE the early-return, but its
    own LRU absorbs the duplicate.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    emitter = _CaptureInstallEmitter()
    a = WhatsAppChannelAdapter(
        install_emitter=emitter,
        install_id=_ACCOUNT_ID,
        tenant_id=_TENANT,
    )

    await a.on_connection_open(trigger="initial_connect")
    await a.on_connection_open(trigger="reconnect")  # still in SYNC

    assert len(emitter.calls) == 1
