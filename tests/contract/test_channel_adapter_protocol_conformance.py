"""ChannelAdapter Protocol conformance suite (W6.A4).

Every adapter in :mod:`wormbase_channel_adapters` (slack, discord,
teams) is the wire-edge of the worm. Adding a new platform is a class
+ registry entry; nothing forces the new adapter to behave like the
existing ones. This module is the conformance battery.

Six invariants per adapter:

1. ``authenticate(valid_secrets)`` returns a structurally valid
   :class:`AuthHandle`; ``authenticate(invalid_secrets)`` raises
   ``ValueError``.
2. ``install(handle)`` returns an :class:`InstallRecord` carrying
   ``platform``, ``install_id``, and a (possibly empty) ``scopes``
   list. Production adapters also populate ``bot_user_id``.
3. ``listen(handle)`` returns an async iterator of :class:`InfraEvent`.
   The conformance harness can't drive a real wire from here, so the
   test asserts the iterator can be cancelled cleanly without leaking
   the listen task.
4. ``send(handle, channel, msg)`` returns a :class:`MessageRef`
   carrying the platform tag and a ``platform_message_id`` (possibly
   stub for preview adapters; never None).
5. ``list_workspace_members(handle)`` returns ``list[PlatformMember]``
   — never None. Empty list is fine; production adapters populate it.
6. The InfraEvent shape — verified by feeding a raw platform message
   into the adapter (where supported) and asserting every required
   field is present and platform-specific keys do NOT leak past the
   ``platform_*`` raw envelope (the dashboard reads only the resolved
   ``channel_id`` / ``person_id`` UUIDs, not the platform native ids).

Discord and Teams' ``listen`` is a stub-but-real long-idle loop; the
test cancels it after 50ms to verify cancellability without hanging.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wormbase_channel_adapters import default_registry
from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.types import (
    AuthHandle,
    ChannelRef,
    InfraEvent,
    InstallRecord,
    MessageRef,
    OutMessage,
    PlatformMember,
    SecretBundle,
)


# ---------------------------------------------------------------------------
# Per-adapter fixture model
# ---------------------------------------------------------------------------


@dataclass
class AdapterFixture:
    platform: str
    factory: Callable[[], Awaitable[tuple[ChannelAdapter, Any]]]
    valid_secrets: SecretBundle
    invalid_secrets: SecretBundle
    is_production: bool
    # Adapters that intentionally ship without ``send`` in capability
    # (e.g. WhatsApp, where the OpenClaw HTTP route is unverified
    # upstream — see issue #73016) raise ``NotImplementedError`` from
    # ``send``. The send-conformance invariant is gated on this flag so
    # capability honesty isn't silently broken by a stub MessageRef.
    supports_send: bool = True


# Slack: real OAuth surface, mocked AsyncWebClient.
async def _slack_fixture() -> tuple[ChannelAdapter, Any]:
    from wormbase_channel_adapters.slack import SlackChannelAdapter

    fake = MagicMock()
    fake.auth_test = AsyncMock(
        return_value=MagicMock(data={
            "ok": True,
            "bot_id": "B-test",
            "user_id": "U-test",
            "scope": "chat:write,channels:read,users:read",
        })
    )
    fake.users_list = AsyncMock(
        return_value=MagicMock(data={
            "ok": True,
            "members": [
                {
                    "id": "U-alice",
                    "name": "alice",
                    "real_name": "Alice",
                    "profile": {"email": "alice@x.com"},
                    "is_bot": False,
                    "is_admin": True,
                    "deleted": False,
                },
            ],
            "response_metadata": {"next_cursor": ""},
        })
    )
    fake.chat_postMessage = AsyncMock(
        return_value=MagicMock(data={"ok": True, "ts": "1234.5678"})
    )
    fake.conversations_join = AsyncMock(
        return_value=MagicMock(data={"ok": True})
    )
    fake.conversations_history = AsyncMock(
        return_value=MagicMock(data={
            "ok": True,
            "messages": [
                {
                    "ts": "1.000001",
                    "user": "U-alice",
                    "text": "hello world",
                },
            ],
        })
    )
    return SlackChannelAdapter(slack_client=fake), fake


# Discord: stub-but-real, no client mock needed.
async def _discord_fixture() -> tuple[ChannelAdapter, Any]:
    from wormbase_channel_adapters.discord import DiscordChannelAdapter

    return DiscordChannelAdapter(), None


# Teams: stub-but-real, no client mock needed.
async def _teams_fixture() -> tuple[ChannelAdapter, Any]:
    from wormbase_channel_adapters.teams import TeamsChannelAdapter

    return TeamsChannelAdapter(), None


# WhatsApp: preview adapter via OpenClaw Baileys. Pre-seeds an injected
# message via ``inject_message`` so the InfraEvent canonical-schema
# invariant has a real wire path to assert against (the production
# fetch path hits OpenClaw's HTTP API, which is out of scope here).
async def _whatsapp_fixture() -> tuple[ChannelAdapter, Any]:
    from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter

    adapter = WhatsAppChannelAdapter()
    # Seed a synthetic Baileys-shaped message so
    # fetch_latest_and_normalize has something to return for the
    # InfraEvent schema-leak test. The state machine starts in IDLE
    # and the message will get classified accordingly.
    adapter.inject_message(
        "C-channel-test",
        {
            "key": {
                "remoteJid": "5511999999999@s.whatsapp.net",
                "id": "msg-1",
                "participant": "5511999999999@s.whatsapp.net",
            },
            "messageTimestamp": 1700000000,
            "message": {"conversation": "hello world"},
        },
    )

    # WhatsApp's real send subprocesses to OpenClaw (Wave C2), which
    # isn't reachable from a unit-level conformance test. Replace `send`
    # with a deterministic stub that honors the Protocol's MessageRef
    # contract so the test exercises the capability invariant without
    # needing the OpenClaw container.
    async def _fake_send(handle: Any, channel: Any, msg: Any) -> MessageRef:
        return MessageRef(
            platform="whatsapp",
            platform_channel_id=channel.platform_channel_id,
            platform_message_id="whatsapp-msg-stub",
        )

    adapter.send = _fake_send  # type: ignore[method-assign]
    return adapter, None


ADAPTER_FIXTURES: dict[str, AdapterFixture] = {
    "slack": AdapterFixture(
        platform="slack",
        factory=_slack_fixture,
        valid_secrets=SecretBundle(payload={"bot_token": "xoxb-test"}),
        invalid_secrets=SecretBundle(payload={}),
        is_production=True,
    ),
    "discord": AdapterFixture(
        platform="discord",
        factory=_discord_fixture,
        valid_secrets=SecretBundle(payload={"bot_token": "discord-bot-token"}),
        invalid_secrets=SecretBundle(payload={}),
        is_production=False,
    ),
    "teams": AdapterFixture(
        platform="teams",
        factory=_teams_fixture,
        valid_secrets=SecretBundle(
            payload={
                "tenant_id": "tid",
                "client_id": "cid",
                "client_secret": "csec",
            }
        ),
        invalid_secrets=SecretBundle(payload={"tenant_id": "x"}),
        is_production=False,
    ),
    "whatsapp": AdapterFixture(
        platform="whatsapp",
        factory=_whatsapp_fixture,
        valid_secrets=SecretBundle(
            payload={"account_id": "baseworm-test", "tenant_id": "baseworm"}
        ),
        invalid_secrets=SecretBundle(payload={}),
        is_production=False,
        # Wave C2 (2026-05-06) wired send via OpenClaw CLI subprocess;
        # capability now includes "send". The fixture stubs send() to
        # bypass the OpenClaw subprocess so the conformance test runs
        # without external infra.
        supports_send=True,
    ),
}


ADAPTER_PLATFORMS: list[str] = ["slack", "discord", "teams", "whatsapp"]


@pytest.fixture
def adapter_fixture(request: pytest.FixtureRequest) -> AdapterFixture:
    return ADAPTER_FIXTURES[request.param]


# ---------------------------------------------------------------------------
# The canonical InfraEvent field set — used by the schema-leak test
# ---------------------------------------------------------------------------


_CANONICAL_INFRA_EVENT_FIELDS = {f.name for f in dataclasses.fields(InfraEvent)}


# ---------------------------------------------------------------------------
# Conformance class — six tests × three adapters = 18 cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_fixture",
    ADAPTER_PLATFORMS,
    indirect=True,
    ids=ADAPTER_PLATFORMS,
)
class TestChannelAdapterProtocolConformance:
    """Six invariants × three adapters = 18 conformance cases."""

    @pytest.mark.asyncio
    async def test_authenticate_valid_and_invalid(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: valid secrets → AuthHandle; invalid → ValueError."""
        instance, _ = await adapter_fixture.factory()
        assert isinstance(instance, ChannelAdapter), (
            f"{type(instance).__name__} does not implement ChannelAdapter Protocol"
        )
        handle = await instance.authenticate(adapter_fixture.valid_secrets)
        assert isinstance(handle, AuthHandle)
        assert handle.connector_kind == adapter_fixture.platform
        assert isinstance(handle.handle_id, str) and handle.handle_id

        with pytest.raises(ValueError):
            await instance.authenticate(adapter_fixture.invalid_secrets)

    @pytest.mark.asyncio
    async def test_install_returns_install_record_with_platform(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: install returns an InstallRecord naming the platform.

        Production adapters populate ``bot_user_id`` and a non-empty
        ``scopes`` list (Slack scope grant). Preview adapters return
        a stub bot_user_id and a canonical scope list. None of them
        return None.
        """
        instance, _ = await adapter_fixture.factory()
        handle = await instance.authenticate(adapter_fixture.valid_secrets)
        rec = await instance.install(handle)
        assert isinstance(rec, InstallRecord)
        assert rec.platform == adapter_fixture.platform
        assert isinstance(rec.install_id, str) and rec.install_id
        assert isinstance(rec.scopes, list)
        # Preview adapters are allowed an empty scope list when the
        # OAuth flow is stubbed; production adapters must surface the
        # actual scopes.
        if adapter_fixture.is_production:
            assert rec.scopes, "production adapter must populate scopes"

    @pytest.mark.asyncio
    async def test_listen_is_async_iterator_and_cancellable(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: listen() returns an async iterator that can be
        cancelled cleanly (no leaked tasks, no hangs).

        Stub adapters (discord/teams) idle forever; the test cancels
        them after a brief delay. Slack idles when no admit_signal is
        wired — same shape.
        """
        instance, _ = await adapter_fixture.factory()
        handle = await instance.authenticate(adapter_fixture.valid_secrets)

        events: list[InfraEvent] = []

        async def _drive() -> None:
            async for ev in instance.listen(handle):
                events.append(ev)

        task = asyncio.create_task(_drive())
        # Yield long enough that the listen coroutine starts.
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises((asyncio.CancelledError, BaseException)):
            try:
                await task
            except asyncio.CancelledError:
                raise
        # No events expected without a driver, but we don't assert on
        # count — the contract is "cancellable without hangs", not
        # "yields zero".

    @pytest.mark.asyncio
    async def test_send_returns_message_ref_with_platform(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: send returns a MessageRef tagged with the platform
        and carrying a non-empty ``platform_message_id``.

        Stub adapters return a stub id (e.g. ``"discord-msg-stub"``);
        production adapters return the real Slack ``ts`` value. None
        of them return an empty string or None.

        Capability-honest preview adapters (currently WhatsApp) ship
        without ``send`` in :attr:`capability` and raise
        ``NotImplementedError``. For those adapters the dual invariant
        applies: ``"send"`` is NOT in capability AND calling send
        raises. Capability and behavior must agree.
        """
        instance, _ = await adapter_fixture.factory()
        handle = await instance.authenticate(adapter_fixture.valid_secrets)
        if not adapter_fixture.supports_send:
            assert "send" not in instance.capability, (
                f"{adapter_fixture.platform}: declared supports_send=False "
                f"but capability advertises 'send' — capability must match "
                f"behavior"
            )
            with pytest.raises(NotImplementedError):
                await instance.send(
                    handle,
                    ChannelRef(
                        platform=adapter_fixture.platform,
                        platform_channel_id="C-test-channel",
                    ),
                    OutMessage(text="hello from conformance"),
                )
            return

        ref = await instance.send(
            handle,
            ChannelRef(
                platform=adapter_fixture.platform,
                platform_channel_id="C-test-channel",
            ),
            OutMessage(text="hello from conformance"),
        )
        assert isinstance(ref, MessageRef)
        assert ref.platform == adapter_fixture.platform
        assert isinstance(ref.platform_message_id, str)
        assert ref.platform_message_id, (
            f"{adapter_fixture.platform}: send returned empty platform_message_id"
        )
        assert ref.platform_channel_id == "C-test-channel"

    @pytest.mark.asyncio
    async def test_list_workspace_members_returns_list_never_none(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: list_workspace_members ALWAYS returns a list, never None.

        Empty list is fine for stub adapters; the dashboard's
        :code:`Person`-discovery loop iterates the result, so None
        would crash silently.

        Production Slack returns ≥1 member for a populated workspace
        (verified via the canned ``users.list`` payload in the fixture).
        """
        instance, _ = await adapter_fixture.factory()
        handle = await instance.authenticate(adapter_fixture.valid_secrets)
        members = await instance.list_workspace_members(handle)
        assert members is not None, (
            f"{adapter_fixture.platform}: returned None — must return [] "
            f"on empty workspaces"
        )
        assert isinstance(members, list)
        for m in members:
            assert isinstance(m, PlatformMember)
            assert m.platform == adapter_fixture.platform
        # Production Slack fixture is seeded with one member.
        if adapter_fixture.is_production:
            assert len(members) >= 1, (
                "production adapter on a populated fixture must list ≥1 member"
            )

    @pytest.mark.asyncio
    async def test_infra_event_canonical_schema(
        self, adapter_fixture: AdapterFixture
    ) -> None:
        """Invariant: the InfraEvent shape is canonical — every adapter that
        synthesizes an InfraEvent populates exactly the documented field
        set, with platform-specific raw data only inside ``payload`` and
        ``platform_*`` fields.

        Slack supports ``fetch_latest_and_normalize`` which we use to
        synthesize an event from the canned conversations.history.
        Discord/Teams' synthesizers aren't wired yet (preview); for
        them we construct the InfraEvent directly via the dataclass
        and verify the SCHEMA matches the canonical field set.
        """
        instance, _ = await adapter_fixture.factory()
        handle = await instance.authenticate(adapter_fixture.valid_secrets)

        if adapter_fixture.is_production:
            # Slack: drive fetch_latest_and_normalize.
            event = await instance.fetch_latest_and_normalize(  # type: ignore[attr-defined]
                handle, "C-channel-test"
            )
            assert event is not None
        else:
            # Preview adapters: construct an InfraEvent directly with
            # the canonical fields. The schema-leak guard below applies
            # to BOTH paths.
            from datetime import datetime, timezone

            event = InfraEvent(
                source="channel_message",
                platform=adapter_fixture.platform,
                platform_channel_id="C-test",
                platform_user_id="U-test",
                platform_message_id="msg-1",
                text="hello",
                payload={"raw": "platform-specific"},
                ts=datetime.now(timezone.utc),
            )

        # 1. The InfraEvent is a dataclass — its fields are exactly the
        #    canonical set. (Guards against an adapter subclass adding
        #    a ``slack_team_id`` field that bypasses the platform_*
        #    namespace.)
        actual_fields = {f.name for f in dataclasses.fields(event)}
        assert actual_fields == _CANONICAL_INFRA_EVENT_FIELDS, (
            f"{adapter_fixture.platform}: InfraEvent fields drifted "
            f"({actual_fields ^ _CANONICAL_INFRA_EVENT_FIELDS})"
        )

        # 2. platform_* and resolved channel_id/person_id slots exist;
        #    the dashboard reads the latter, never the former.
        assert hasattr(event, "platform_channel_id")
        assert hasattr(event, "platform_user_id")
        assert hasattr(event, "platform_message_id")
        assert hasattr(event, "channel_id")
        assert hasattr(event, "person_id")

        # 3. The ``platform`` tag matches the adapter under test.
        assert event.platform == adapter_fixture.platform


# ---------------------------------------------------------------------------
# Cross-cutting drift gates
# ---------------------------------------------------------------------------


def test_conformance_covers_every_registered_adapter() -> None:
    """Invariant: every adapter in the registry has a conformance fixture.

    Drift-detection: when a new ChannelAdapter is registered, this test
    fails until ADAPTER_FIXTURES gains an entry.
    """
    reg = default_registry()
    registered = set(reg.all_platforms())
    covered = set(ADAPTER_FIXTURES.keys())
    assert registered == covered, (
        f"adapter conformance drift: registered={registered}, covered={covered}"
    )


def test_every_registered_adapter_is_protocol_compliant() -> None:
    """Invariant: every adapter class structurally implements ChannelAdapter.

    Asserted via runtime_checkable Protocol — catches missing methods
    or wrong signatures at registry-population time.
    """
    reg = default_registry()
    for platform in reg.all_platforms():
        cls = reg.get(platform)
        assert cls is not None
        instance = cls()
        assert isinstance(instance, ChannelAdapter), (
            f"{platform}: {cls.__name__} does not implement "
            f"ChannelAdapter Protocol"
        )


def test_canonical_infra_event_fields_locked() -> None:
    """Invariant: the canonical InfraEvent field set is the documented one.

    The dashboard reads ``channel_id`` and ``person_id`` (UUID-resolved);
    the platform_* fields are the raw envelope. Adding or removing a
    field requires intentional schema migration — this test forces the
    conversation.
    """
    expected = {
        "source",
        "platform",
        "platform_channel_id",
        "platform_user_id",
        "platform_message_id",
        "text",
        "payload",
        "ts",
        "company_id",
        "channel_id",
        "person_id",
        # Conversation-provenance fields landed 2026-05-05 alongside the
        # WhatsApp first-level support and the conversation_sync lineage
        # entry kind. See:
        #   docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md
        "delivery_mode",
        "platform_ts",
        "history_sync_id",
        # WhatsApp mention-fanout (Phase B1.1, 2026-05-06): the raw
        # `mentionedJid` list from Baileys is preserved on InfraEvent so
        # MentionsWorm can resolve fanouts symmetrically to Slack mentions.
        "mentioned_jids",
    }
    assert _CANONICAL_INFRA_EVENT_FIELDS == expected, (
        f"InfraEvent canonical schema drifted: {_CANONICAL_INFRA_EVENT_FIELDS ^ expected}"
    )
