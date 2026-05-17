"""Tests for WhatsAppChannelAdapter.send (Wave C2, 2026-05-06).

Covers the OpenClaw CLI subprocess wire path landed by Wave C2:
``docker exec <container> openclaw message send --channel whatsapp ...``.
The subprocess invocation is mocked at ``asyncio.create_subprocess_exec``
so tests are hermetic — they don't require a running OpenClaw or docker.

Round-trip + edge cases:

* Successful round-trip → ``MessageRef`` returned with the OpenClaw
  ``messageId`` parsed from the JSON stdout.
* ``msg.thread_ref`` set → warning logged, send still proceeds (WhatsApp
  is flat).
* ``msg.blocks`` set → warning logged, send still proceeds (Slack-only).
* ``msg.files`` non-empty → raises ``NotImplementedError`` (Wave D).
* Subprocess returncode != 0 with rate-limit-shaped stderr → raises
  ``RateLimitedError`` (the rate-limit decorator's retry hook).
* Subprocess returncode != 0 with arbitrary stderr → raises
  ``RuntimeError`` (hard error).
* Missing ``docker`` binary → raises ``RuntimeError`` with a clearer
  message than the bare ``FileNotFoundError``.
* The argv built by ``_do_send`` uses tenant + token + account env.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)
from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter
from wormbase_channel_adapters.whatsapp_rate_limit import (
    RateLimitedError,
    _LIMITER_REGISTRY,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeProc:
    """Minimal stand-in for ``asyncio.subprocess.Process``.

    Exposes ``communicate`` returning preset (stdout, stderr) bytes and
    ``returncode``. ``kill`` / ``wait`` are no-ops.
    """

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:  # pragma: no cover
        return None

    async def wait(self) -> int:  # pragma: no cover
        return self.returncode


@pytest.fixture(autouse=True)
def _reset_limiter_registry() -> Any:
    """Clear the module-level limiter registry between tests."""
    _LIMITER_REGISTRY.clear()
    yield
    _LIMITER_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_round_trips_via_openclaw_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful subprocess returns a populated ``MessageRef``.

    The CLI emits ``{"messageId": "...", "toJid": "..."}`` on success;
    the adapter parses it and returns ``MessageRef.platform_message_id``.
    """
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    captured_argv: list[list[str]] = []

    async def _fake_create_subprocess_exec(*args: str, **kwargs: Any) -> _FakeProc:
        captured_argv.append(list(args))
        return _FakeProc(
            stdout=b'{"messageId": "BAEABCD12345", "toJid": "5511999999999@s.whatsapp.net"}',
            stderr=b"",
            returncode=0,
        )

    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _fake_create_subprocess_exec,
    )

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "baseworm-wa", "tenant_id": "t1"})
    )
    channel = ChannelRef(
        platform="whatsapp",
        platform_channel_id="5511999999999@s.whatsapp.net",
    )
    ref = await a.send(handle, channel, OutMessage(text="Hello from C2"))

    assert ref.platform == "whatsapp"
    assert ref.platform_message_id == "BAEABCD12345"
    assert ref.platform_channel_id == "5511999999999@s.whatsapp.net"
    # Argv shape: docker exec <container> openclaw message send ...
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert argv[0] == "docker"
    assert argv[1] == "exec"
    # Default container.
    assert argv[2] == "wormbase-openclaw"
    assert argv[3] == "openclaw"
    assert argv[4] == "message"
    assert argv[5] == "send"
    assert "--channel" in argv and argv[argv.index("--channel") + 1] == "whatsapp"
    assert "--target" in argv and argv[argv.index("--target") + 1] == (
        "5511999999999@s.whatsapp.net"
    )
    assert "--message" in argv and argv[argv.index("--message") + 1] == "Hello from C2"
    assert "--json" in argv
    # Account from handle.extra
    assert "--account" in argv and argv[argv.index("--account") + 1] == "baseworm-wa"


@pytest.mark.asyncio
async def test_send_uses_env_overrides_for_container_token_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env overrides flow into the argv."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")
    monkeypatch.setenv(
        "WORMBASE_WHATSAPP_OPENCLAW_CONTAINER", "custom-openclaw",
    )
    monkeypatch.setenv(
        "WORMBASE_WHATSAPP_OPENCLAW_TOKEN", "test-master-token-123",
    )
    monkeypatch.setenv(
        "WORMBASE_WHATSAPP_OPENCLAW_ACCOUNT", "tenant-special",
    )

    captured_argv: list[list[str]] = []

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        captured_argv.append(list(args))
        return _FakeProc(stdout=b'{"messageId":"X1"}', returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "ignored", "tenant_id": "t1"})
    )
    await a.send(
        handle,
        ChannelRef(
            platform="whatsapp",
            platform_channel_id="5511777777777@s.whatsapp.net",
        ),
        OutMessage(text="hi"),
    )
    argv = captured_argv[0]
    assert argv[2] == "custom-openclaw"
    # Token threaded as --token <value>
    assert "--token" in argv
    assert argv[argv.index("--token") + 1] == "test-master-token-123"
    # Env-account overrides handle account
    assert argv[argv.index("--account") + 1] == "tenant-special"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_with_thread_ref_logs_warning_but_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``msg.thread_ref`` set → warning logged, send still proceeds."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        return _FakeProc(stdout=b'{"messageId":"X2"}', returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )

    import logging
    with caplog.at_level(logging.WARNING):
        ref = await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi", thread_ref="1234.5678"),
        )

    assert ref.platform_message_id == "X2"
    assert any("thread_ref" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_with_blocks_logs_warning_but_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``msg.blocks`` set → warning logged, send still proceeds with text."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    captured_argv: list[list[str]] = []

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        captured_argv.append(list(args))
        return _FakeProc(stdout=b'{"messageId":"X3"}', returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )

    import logging
    with caplog.at_level(logging.WARNING):
        ref = await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(
                text="text body",
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}],
            ),
        )

    assert ref.platform_message_id == "X3"
    assert any("blocks" in r.message.lower() for r in caplog.records)
    # Argv carries the text only — no Block Kit encoding leaked.
    argv = captured_argv[0]
    assert argv[argv.index("--message") + 1] == "text body"


@pytest.mark.asyncio
async def test_send_with_files_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``msg.files`` non-empty → NotImplementedError (Wave D scope)."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )
    with pytest.raises(NotImplementedError, match="file_upload"):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="caption", files=[b"fake-image-bytes"]),
        )


@pytest.mark.asyncio
async def test_send_kill_switch_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_WHATSAPP_SEND_DISABLE=1`` → NotImplementedError, no subprocess."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")

    invoked = []

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        invoked.append(args)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )
    with pytest.raises(NotImplementedError, match="disabled"):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi"),
        )
    # Ensure no subprocess was launched.
    assert invoked == []


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_rate_limited_stderr_raises_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stderr containing rate-limit markers → RateLimitedError."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        return _FakeProc(
            stdout=b"",
            stderr=b"WhatsApp rate limit exceeded; retry-after 60s",
            returncode=1,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )
    # The rate-limit decorator wraps with backoff (max_retries=3 default).
    # Each retry will see the same RateLimitedError, so the final raise
    # is RateLimitedError after exhaustion.
    with pytest.raises(RateLimitedError):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi"),
        )


@pytest.mark.asyncio
async def test_send_arbitrary_stderr_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-rate-limit stderr → RuntimeError (hard fail)."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        return _FakeProc(
            stdout=b"",
            stderr=b"unauthorized: scope upgrade pending approval",
            returncode=1,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )
    with pytest.raises(RuntimeError, match="openclaw message send failed"):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi"),
        )


@pytest.mark.asyncio
async def test_send_docker_missing_raises_clear_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ``docker`` binary → RuntimeError with a guidance message."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        raise FileNotFoundError(2, "No such file or directory: 'docker'")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa", "tenant_id": "t1"})
    )
    with pytest.raises(RuntimeError, match="docker"):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi"),
        )


# ---------------------------------------------------------------------------
# Multi-tenant smoke (briefly re-pin E2's tenant isolation contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_two_tenants_use_separate_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tenants posting via send don't share a rate-limit bucket.

    Re-pins E2's contract through the actual subprocess wire (E2's tests
    use the kill-switch; this one mocks the subprocess to exercise the
    full path including the rate-limit acquire and the inner _do_send).
    """
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_TA", "5511111111111")
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_TB", "5512222222222")

    async def _fake(*args: str, **kwargs: Any) -> _FakeProc:
        return _FakeProc(stdout=b'{"messageId":"M"}', returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)

    a_a = WhatsAppChannelAdapter()
    a_b = WhatsAppChannelAdapter()

    handle_a = await a_a.authenticate(
        SecretBundle(payload={"account_id": "wa-a", "tenant_id": "ta"})
    )
    handle_b = await a_b.authenticate(
        SecretBundle(payload={"account_id": "wa-b", "tenant_id": "tb"})
    )

    channel = ChannelRef(
        platform="whatsapp",
        platform_channel_id="5511999999999@s.whatsapp.net",
    )

    ref_a = await a_a.send(handle_a, channel, OutMessage(text="from A"))
    ref_b = await a_b.send(handle_b, channel, OutMessage(text="from B"))

    assert ref_a.platform_message_id == "M"
    assert ref_b.platform_message_id == "M"
    # Bucket separation — registry has at least two distinct keys.
    keys_seen: set[str] = set()
    for limiter in _LIMITER_REGISTRY.values():
        keys_seen.update(limiter._buckets.keys())
    assert "ta:5511111111111" in keys_seen
    assert "tb:5512222222222" in keys_seen
