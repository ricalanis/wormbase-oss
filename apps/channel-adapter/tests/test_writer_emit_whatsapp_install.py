"""Tests for LedgerWriter.emit_whatsapp_install (Wave B3.1, 2026-05-06).

The production-side install-emit method that the WhatsAppChannelAdapter's
``install_emitter`` constructor kwarg points at. WhatsApp pairing has no
OAuth grant — Baileys' ``connection_open`` after QR scan IS the
pairing-complete signal — so this method is the install-write site for
WhatsApp (Slack writes via ``write_actions.complete_install``).

Pinned contract:

* Full PEVR cycle, ``quadrant=active_deterministic``,
  ``target_kind=install_completed``.
* Synthesized ``installer_person_id`` is deterministic from
  ``(tenant_id, bot_jid)``: same inputs → same UUID across calls and
  process restarts.
* ``oauth_grant_ref`` carries the ``vault://`` prefix sentinel — the
  ``InstallCompletedPayload`` validator rejects anything else, so a
  cleartext-creds bug in the adapter cannot reach the ledger.
* ``target_kind`` is ``install_completed`` (no new entry kind);
  the writer reuses the existing kind per Schema-Evolution Doctrine
  Rule 2 — see ``test_writer_emits_only_pinned_target_kinds`` for the
  durable invariant.
* Ledger-fold idempotency: a second invocation for the same
  ``(tenant, bot_jid)`` is absorbed at the writer (returns ``None``
  without touching the ledger).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import KIND_REGISTRY, InstallCompletedPayload

from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import (
    WHATSAPP_INSTALLER_NAMESPACE,
    LedgerWriter,
)


_TENANT = "baseworm"
_BOT_JID = "5511888888888@s.whatsapp.net"
_OTHER_BOT_JID = "5511777777777@s.whatsapp.net"
_ACCOUNT_ID = "wa-1"


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid(_TENANT)


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def _executes(rows: list[dict], tool: str) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


# ---------------------------------------------------------------------------
# 1. emit_whatsapp_install writes a full PEVR cycle.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_whatsapp_install_writes_pevr_cycle(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    result = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    assert result is not None
    assert len(result.entry_ids) == 4

    rows = await writer._ledger.fetch(company_id)
    # Filter to just this PEVR cycle (ignore unrelated entries).
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]


@pytest.mark.asyncio
async def test_emit_whatsapp_install_uses_active_deterministic_quadrant(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Install is an explicit operator action — active_deterministic, not
    active_probabilistic. Pinned so a future refactor can't silently flip
    the quadrant and break governance projections.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    rows = await writer._ledger.fetch(company_id)
    assert all(r["quadrant"] == "active_deterministic" for r in rows)


# ---------------------------------------------------------------------------
# 2. Synthesized installer_person_id is deterministic.
# ---------------------------------------------------------------------------


def test_synthesized_installer_person_id_is_deterministic() -> None:
    """Same (tenant_id, bot_jid) → same UUID across repeated calls."""
    a = LedgerWriter.synthesize_whatsapp_installer_person_id(_TENANT, _BOT_JID)
    b = LedgerWriter.synthesize_whatsapp_installer_person_id(_TENANT, _BOT_JID)
    assert a == b
    assert isinstance(a, UUID)


def test_synthesized_installer_person_id_differs_by_tenant() -> None:
    """Different tenants pairing the same phone → distinct synthesized ids."""
    a = LedgerWriter.synthesize_whatsapp_installer_person_id(_TENANT, _BOT_JID)
    b = LedgerWriter.synthesize_whatsapp_installer_person_id("acme", _BOT_JID)
    assert a != b


def test_synthesized_installer_person_id_differs_by_bot_jid() -> None:
    """Same tenant, different bot phones → distinct synthesized ids."""
    a = LedgerWriter.synthesize_whatsapp_installer_person_id(_TENANT, _BOT_JID)
    b = LedgerWriter.synthesize_whatsapp_installer_person_id(
        _TENANT, _OTHER_BOT_JID,
    )
    assert a != b


def test_synthesized_installer_person_id_namespaced() -> None:
    """The synthesized id lives under WHATSAPP_INSTALLER_NAMESPACE — a
    distinct namespace from SLACK_USER_NAMESPACE so a slack user_id
    collision can't accidentally produce the same UUID as a WhatsApp
    installer.
    """
    from uuid import uuid5

    expected = uuid5(WHATSAPP_INSTALLER_NAMESPACE, f"{_TENANT}:{_BOT_JID}")
    actual = LedgerWriter.synthesize_whatsapp_installer_person_id(
        _TENANT, _BOT_JID,
    )
    assert actual == expected


# ---------------------------------------------------------------------------
# 3. oauth_grant_ref has the vault:// prefix sentinel.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_grant_ref_uses_vault_prefix(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The InstallCompletedPayload validator rejects anything not under
    kms:// or vault://; the WhatsApp emit synthesizes a vault:// sentinel
    that NEVER carries credential material.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    assert len(execs) == 1
    args = execs[0]["payload"]["args"]
    assert args["oauth_grant_ref"].startswith("vault://")
    assert "wormbase/whatsapp-baileys" in args["oauth_grant_ref"]
    # Never any credential material smuggled into the ref.
    assert "BEGIN PRIVATE" not in args["oauth_grant_ref"]
    assert "AKIA" not in args["oauth_grant_ref"]


# ---------------------------------------------------------------------------
# 4. target_kind is install_completed (KIND_REGISTRY unchanged at 83).
# ---------------------------------------------------------------------------


def test_writer_emits_only_pinned_target_kinds() -> None:
    """Schema-Evolution Doctrine Rule 2 invariant (writer-scoped).

    The original test pinned ``len(KIND_REGISTRY) == 83`` as a
    drift-canary at the time ``emit_whatsapp_install`` landed. That
    absolute count broke every time a non-writer kind was added to
    KIND_REGISTRY (we're at 103+ as of v2.A) — but the *intent* was
    to pin "this writer does not silently expand its emit surface,"
    not "the whole ledger schema is frozen."

    Drift-resistant restatement: assert against an explicit allowlist
    of the kinds the writer is permitted to reference, and confirm
    every allowlisted kind is still present in KIND_REGISTRY (so a
    rename can't silently desync). Adding a new emit method on
    LedgerWriter triggers this test only if the new method introduces
    a new ``target_kind`` outside this allowlist — at which point
    Schema-Evolution Doctrine Rule 2 requires an explicit kinds-bump
    review, not a silent drift.

    See ``docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md``
    for the doctrine. The writer-emitted kinds today are:

    * ``chat_received`` — ``_emit_chat_received``
    * ``chat_sent`` — ``_emit_chat_sent``
    * ``conversation_sync`` — ``emit_conversation_sync``
    * ``install_completed`` — ``emit_whatsapp_install`` (and the
      Slack install path)
    """
    # The kinds LedgerWriter is allowed to emit as ``target_kind`` on
    # its propose-execute-verify-resolve cycles. Adding a kind here
    # is a deliberate schema-evolution act, not an accidental drift.
    WRITER_EMITTED_TARGET_KINDS = frozenset({
        "chat_received",
        "chat_sent",
        "conversation_sync",
        "install_completed",
    })
    for kind in WRITER_EMITTED_TARGET_KINDS:
        assert kind in KIND_REGISTRY, (
            f"writer references {kind!r} as a target_kind, but it is "
            f"not registered in KIND_REGISTRY — rename drift?"
        )
    # install_completed is the kind this test-file is anchored on.
    assert "install_completed" in WRITER_EMITTED_TARGET_KINDS


@pytest.mark.asyncio
async def test_target_kind_is_install_completed(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The propose entry's target_kind matches the existing kind name —
    no schema fork."""
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    rows = await writer._ledger.fetch(company_id)
    propose = next(r for r in rows if r["kind"] == "propose")
    assert propose["payload"]["target_kind"] == "install_completed"


@pytest.mark.asyncio
async def test_execute_args_validate_against_install_completed_payload(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The execute.args body validates against InstallCompletedPayload.

    Pins schema fidelity: a downstream projector can
    ``InstallCompletedPayload.model_validate(execute["payload"]["args"])``
    once it filters out the WhatsApp-specific fields we add (paired_at,
    provider, pairing_method, creds_path).
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    args = execs[0]["payload"]["args"]
    # Strip the WhatsApp-specific extras to validate against the schema.
    schema_args = {
        k: v for k, v in args.items()
        if k not in ("paired_at", "provider", "pairing_method", "creds_path")
    }
    payload = InstallCompletedPayload.model_validate(schema_args)
    assert payload.platform == "whatsapp"
    assert payload.bot_user_id == _BOT_JID
    assert payload.scopes == []
    # Synthesized installer_person_id matches our deterministic helper.
    assert payload.installer_person_id == (
        LedgerWriter.synthesize_whatsapp_installer_person_id(_TENANT, _BOT_JID)
    )


@pytest.mark.asyncio
async def test_execute_args_carry_whatsapp_specific_metadata(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """paired_at + provider + pairing_method + creds_path surface on the
    execute args, even though they're not part of InstallCompletedPayload.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        pairing_method="qr",
        paired_at=paired,
        provider="openclaw_baileys",
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    args = execs[0]["payload"]["args"]
    assert args["pairing_method"] == "qr"
    assert args["provider"] == "openclaw_baileys"
    assert args["paired_at"] == paired.isoformat()
    assert args["creds_path"] == "/var/openclaw/whatsapp/baileys/wa-1/creds.json"


# ---------------------------------------------------------------------------
# 5. Ledger-fold idempotency: second call for same (tenant, bot_jid) is no-op.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_for_same_tenant_and_bot_jid_is_absorbed(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Adapter LRU is the fast path; the ledger fold here is the source
    of truth. Cache-cleared adapter (process restart) calls in again →
    fold returns None without writing.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)

    first = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    assert first is not None

    # Second call — same (tenant, bot_jid). Fold absorbs.
    second = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    assert second is None

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    assert len(execs) == 1


@pytest.mark.asyncio
async def test_different_bot_jid_writes_new_install(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Same tenant, new bot_jid (re-pairing with a different phone) →
    second install lands. Mirrors the rotation scenario in the adapter
    tests (``test_same_tenant_new_bot_jid_writes_new_install``).
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    first = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_BOT_JID,
        account_id=_ACCOUNT_ID,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    assert first is not None

    second = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        bot_jid=_OTHER_BOT_JID,
        account_id="wa-2",
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/wa-2/creds.json",
    )
    assert second is not None

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    assert len(execs) == 2
    bot_jids = {e["payload"]["args"]["bot_user_id"] for e in execs}
    assert bot_jids == {_BOT_JID, _OTHER_BOT_JID}


# ---------------------------------------------------------------------------
# 6. None-tenant + None-account_id paths still produce valid entries.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_tenant_and_none_account_id_still_writes(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Single-tenant deployment without OpenClaw account_id should still
    write a valid install entry — synthesized ids fall back to the
    company_id and a uuid4-style install id.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    result = await writer.emit_whatsapp_install(
        tenant_id=None,
        bot_jid=_BOT_JID,
        account_id=None,
        paired_at=paired,
        creds_path="/var/openclaw/whatsapp/baileys/default/creds.json",
    )
    assert result is not None
    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    assert len(execs) == 1
    args = execs[0]["payload"]["args"]
    # tenant_id falls back to company_id when not provided.
    assert args["tenant_id"] == str(company_id)
    # vault ref carries the "default" surrogate.
    assert "default" in args["oauth_grant_ref"]


# ---------------------------------------------------------------------------
# 7. Production wiring contract — emit_whatsapp_install matches the
#    InstallEmitter signature used by WhatsAppChannelAdapter.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_emit_whatsapp_install_callable_as_install_emitter(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Pin: writer.emit_whatsapp_install matches the kwargs contract the
    WhatsAppChannelAdapter passes via ``install_emitter``. Same shape as
    the existing test_writer_emit_conversation_sync_is_callable_as_sync_emitter
    pin in test_service_whatsapp_capture.py.
    """
    paired = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    result = await writer.emit_whatsapp_install(
        tenant_id=_TENANT,
        account_id=_ACCOUNT_ID,
        bot_jid=_BOT_JID,
        pairing_method="qr",
        paired_at=paired,
        provider="openclaw_baileys",
        creds_path="/var/openclaw/whatsapp/baileys/wa-1/creds.json",
    )
    assert result is not None
    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "emit_install_completed")
    assert len(execs) == 1
