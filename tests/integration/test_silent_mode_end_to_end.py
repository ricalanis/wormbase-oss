"""End-to-end: silent mode produces ZERO outbound side effects on any surface.

Exercises all five silent-mode chokepoints in one test file. If any gate
regresses — or a new outbound surface is added without going through
``is_silent_mode_enabled`` — this test should fail first.

Gates exercised:
  1. write_actions._pevr (covers ~30 MCP write tools)
  2. SilentModeChannelAdapter via the registry build_adapter factory
  3. dm.send_resource_conversation_dm
  4. voice-agent /webhook/elevenlabs handler

Tests are intentionally composition-level (InMemoryLedger + mocked
transports) rather than service-booting. The unit tests in each app's
own test suite cover internal behaviour; this file's job is to verify
the integration surface — that silent mode is honored from every entry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from wormbase_channel_adapter import dm
from wormbase_channel_adapters import registry as adapter_registry
from wormbase_channel_adapters.silent_mode import SilentModeChannelAdapter
from wormbase_core import silent_mode, write_actions
from wormbase_ledger import InMemoryLedger
from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore


WORMBASE_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.fixture
def company_id() -> UUID:
    return uuid5(WORMBASE_TENANT_NAMESPACE, "baseworm-silent-mode-e2e")


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _propose_targets(ledger: InMemoryLedger, company_id: UUID) -> list[str]:
    """Return all `target_kind` values from `propose` rows in the ledger."""
    rows = await ledger.fetch(company_id)
    return [r["payload"]["target_kind"] for r in rows if r["kind"] == "propose"]


class _FakeKimi:
    async def chat(self, messages, *, model=None, temperature=0.0):
        return "would-have-been-the-reply"


class _FakePlatformAdapter:
    """Concrete ChannelAdapter test double registered into the global registry."""

    platform = "e2e-silent-platform"
    capability: set = set()
    status = "preview"
    status_note = "e2e test adapter"

    def __init__(self) -> None:
        self.send_calls: list[tuple[Any, Any, Any]] = []

    async def authenticate(self, secrets: Any) -> Any:
        return "h"

    async def install(self, handle: Any) -> Any:
        return "i"

    def listen(self, handle: Any) -> Any:
        return iter([])

    async def send(self, handle: Any, channel: Any, msg: Any) -> Any:
        # If silent mode is leaking, this fires and the assertion below catches it.
        self.send_calls.append((handle, channel, msg))
        return "real-msg-ref"

    async def list_workspace_members(self, handle: Any) -> list:
        return []


@pytest.fixture
def fake_platform_class():
    """Register/unregister _FakePlatformAdapter for the test."""
    reg = adapter_registry.default_registry()
    reg.register(_FakePlatformAdapter)
    yield _FakePlatformAdapter
    reg.unregister(_FakePlatformAdapter.platform)


# ---------------------------------------------------------------------------
# Gate 1: write_actions._pevr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_write_gate_is_silent(
    monkeypatch: pytest.MonkeyPatch, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")

    class _Stub:
        def __init__(self, **_kw: Any) -> None: ...

    await write_actions._pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=uuid4(),
        reason="silent-e2e",
        proposed_by="test",
        tool="record_decision",
        args={"k": "v"},
        result_ref="ref",
        payload_cls=_Stub,
        rationale="silent-e2e",
    )

    targets = await _propose_targets(ledger, company_id)
    assert "reply_suppressed" in targets
    assert "decision_recorded" not in targets


# ---------------------------------------------------------------------------
# Gate 2 + 3: registry.build_adapter wraps + decorator suppresses send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_adapter_gate_is_silent(
    monkeypatch: pytest.MonkeyPatch,
    ledger: InMemoryLedger,
    company_id: UUID,
    fake_platform_class: type,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")

    adapter = adapter_registry.build_adapter(
        platform=fake_platform_class.platform,
        ledger=ledger,
        company_id=company_id,
    )
    assert isinstance(adapter, SilentModeChannelAdapter)

    result = await adapter.send(
        handle="h",
        channel={"platform_channel_id": "C_E2E"},
        msg={"text": "hello"},
    )
    assert getattr(result, "suppressed", False) is True

    # The inner platform adapter never saw the send.
    assert adapter._inner.send_calls == []

    targets = await _propose_targets(ledger, company_id)
    assert "reply_suppressed" in targets


# ---------------------------------------------------------------------------
# Gate 4: dm.send_resource_conversation_dm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_gate_is_silent(
    monkeypatch: pytest.MonkeyPatch, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    sender = AsyncMock()
    sender.open_dm = AsyncMock()
    sender.send_dm = AsyncMock()
    sender.platform = "slack"

    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U_E2E",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=ledger,
        company_id=company_id,
    )

    sender.open_dm.assert_not_called()
    sender.send_dm.assert_not_called()
    assert ref.platform_channel_id.startswith("suppressed:")

    targets = await _propose_targets(ledger, company_id)
    assert "reply_suppressed" in targets


# ---------------------------------------------------------------------------
# Gate 5: voice-agent /webhook/elevenlabs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_gate_is_silent(
    monkeypatch: pytest.MonkeyPatch, ledger: InMemoryLedger, company_id: UUID,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")

    state = VoiceAppState(
        ledger=ledger,
        kimi=_FakeKimi(),  # type: ignore[arg-type]
        audio_store=AudioStore("/tmp/voice-audio-silent-e2e"),
        tenant_slug="baseworm",
        company_id=company_id,
    )
    app = create_app(state=state)
    client = TestClient(app)

    payload = {
        "model": "kimi-k2.6:cloud",
        "conversation_id": "el-silent-e2e",
        "user_id": "+15551234567",
        "messages": [
            {"role": "system", "content": "voice agent system"},
            {"role": "user", "content": "What was Q3 net revenue?"},
        ],
    }
    resp = client.post("/webhook/elevenlabs", json=payload)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == ""

    targets = await _propose_targets(ledger, company_id)
    assert "reply_suppressed" in targets
    assert "chat_sent" not in targets


# ---------------------------------------------------------------------------
# Aggregate invariant: passthrough still works when silent mode is off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_gates_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
    ledger: InMemoryLedger,
    company_id: UUID,
    fake_platform_class: type,
) -> None:
    """When silent mode is off, none of the gates short-circuit."""
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)

    # 1) Adapter is unwrapped.
    adapter = adapter_registry.build_adapter(
        platform=fake_platform_class.platform,
        ledger=ledger,
        company_id=company_id,
    )
    assert not isinstance(adapter, SilentModeChannelAdapter)

    # 2) DM goes through.
    sender = AsyncMock()
    sender.open_dm = AsyncMock(return_value="D_REAL")
    sender.send_dm = AsyncMock(return_value="M_REAL")
    sender.platform = "slack"
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U_REAL",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "x", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=ledger,
        company_id=company_id,
    )
    assert ref.platform_channel_id == "D_REAL"

    # No reply_suppressed entries should have landed.
    targets = await _propose_targets(ledger, company_id)
    assert "reply_suppressed" not in targets
