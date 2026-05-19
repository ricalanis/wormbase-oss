"""POST /webhook/elevenlabs returns a silent response under silent mode.

The LLM call still runs (presence-equivalent decisions stay on), but the
outbound `chat_sent` ledger entry is replaced by a `reply_suppressed`
entry and the response to ElevenLabs carries empty `content` so no
audio is synthesized.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from wormbase_core import silent_mode
from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


def _make_app(*, ledger: Any, kimi: Any, company_id: Any) -> TestClient:
    state = VoiceAppState(
        ledger=ledger,
        kimi=kimi,  # type: ignore[arg-type]
        audio_store=AudioStore("/tmp/voice-audio-test"),
        tenant_slug="baseworm",
        company_id=company_id,
    )
    app = create_app(state=state)
    return TestClient(app)


def _llm_payload() -> dict[str, Any]:
    """A minimally valid LLMWebhookRequest body."""
    return {
        "model": "kimi-k2.6:cloud",
        "conversation_id": "el-conv-silent-001",
        "user_id": "+15551234567",
        "messages": [
            {"role": "system", "content": "voice agent system"},
            {"role": "user", "content": "What was Q3 net revenue?"},
        ],
    }


@pytest.mark.asyncio
async def test_elevenlabs_webhook_silent_returns_empty_completion(
    monkeypatch: pytest.MonkeyPatch,
    in_memory_ledger,
    fake_kimi,
    baseworm_company_id,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    client = _make_app(
        ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
    )
    resp = client.post("/webhook/elevenlabs", json=_llm_payload())
    assert resp.status_code == 200
    body = resp.json()
    # OpenAI chat-completion shape, but content is empty so ElevenLabs synthesises no audio.
    assert body["choices"][0]["message"]["content"] == ""

    # Inspect ledger rows: reply_suppressed propose row must exist; chat_sent propose must not.
    rows = await in_memory_ledger.fetch(baseworm_company_id)
    propose_target_kinds = [
        r["payload"]["target_kind"]
        for r in rows
        if r["kind"] == "propose"
    ]
    assert "reply_suppressed" in propose_target_kinds
    assert "chat_sent" not in propose_target_kinds


@pytest.mark.asyncio
async def test_elevenlabs_webhook_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
    in_memory_ledger,
    fake_kimi,
    baseworm_company_id,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    client = _make_app(
        ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
    )
    resp = client.post("/webhook/elevenlabs", json=_llm_payload())
    assert resp.status_code == 200
    body = resp.json()
    # Non-empty content from the fake Kimi.
    assert body["choices"][0]["message"]["content"]

    rows = await in_memory_ledger.fetch(baseworm_company_id)
    propose_target_kinds = [
        r["payload"]["target_kind"]
        for r in rows
        if r["kind"] == "propose"
    ]
    assert "chat_sent" in propose_target_kinds
    assert "reply_suppressed" not in propose_target_kinds
