"""Tests for the ElevenLabs custom-LLM webhook handler.

We exercise the FastAPI app with a stub ElevenLabs body and a mocked
Kimi client (no network), and assert:

- The webhook returns an OpenAI-shaped completion ElevenLabs can read.
- The reply text is exactly what Kimi returned.
- The system prompt + user message are propagated to Kimi.
- Missing-user-message bodies return a 400 (not 500).
- Health check returns 200.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore

from .conftest import FakeKimi


def _make_app(
    *,
    ledger: Any,
    kimi: FakeKimi,
    company_id: Any,
    audio_store: AudioStore | None = None,
) -> TestClient:
    state = VoiceAppState(
        ledger=ledger,
        kimi=kimi,  # type: ignore[arg-type]
        audio_store=audio_store or AudioStore("/tmp/voice-audio-test"),
        tenant_slug="baseworm",
        company_id=company_id,
    )
    app = create_app(state=state)
    return TestClient(app)


class TestHealthz:
    def test_healthz_returns_ok(self, in_memory_ledger, baseworm_company_id, fake_kimi) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["service"] == "wormbase-voice-agent"


class TestElevenLabsWebhook:
    def _stub_body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": "kimi-k2.6:cloud",
            "conversation_id": "el-conv-001",
            "user_id": "+15551234567",
            "messages": [
                {"role": "system", "content": "voice agent system"},
                {"role": "user", "content": "What was Q3 net revenue versus Q2?"},
            ],
            "stream": False,
        }
        body.update(overrides)
        return body

    def test_returns_openai_chat_completion_shape(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        r = client.post("/webhook/elevenlabs", json=self._stub_body())
        assert r.status_code == 200, r.text
        body = r.json()

        # OpenAI chat-completion contract.
        assert body["object"] == "chat.completion"
        assert isinstance(body["id"], str)
        assert "choices" in body and len(body["choices"]) == 1
        choice = body["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == fake_kimi._reply

    def test_kimi_receives_user_text(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        r = client.post("/webhook/elevenlabs", json=self._stub_body())
        assert r.status_code == 200

        # Kimi was called once; the system prompt is first; the user
        # text we sent is the LAST message.
        assert len(fake_kimi.calls) == 1
        prompt = fake_kimi.calls[0]
        assert prompt[0]["role"] == "system"
        assert prompt[-1]["role"] == "user"
        assert "Q3 net revenue" in prompt[-1]["content"]

    def test_missing_user_message_returns_400(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        body = self._stub_body(messages=[{"role": "system", "content": "x"}])
        r = client.post("/webhook/elevenlabs", json=body)
        assert r.status_code == 400
        # Kimi should NOT have been called; we bail before LLM.
        assert fake_kimi.calls == []

    def test_extra_fields_in_body_are_tolerated(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        # ElevenLabs sometimes sends fields we don't model. We must not 422.
        body = self._stub_body(
            call_sid="cs-mystery-99",
            customer_phone="+15550009999",
            extra={"future_field": True},
        )
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        r = client.post("/webhook/elevenlabs", json=body)
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
class TestSessionLifecycle:
    async def test_session_start_returns_ok_and_writes_ledger(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        r = client.post(
            "/webhook/elevenlabs/session-start",
            json={"conversation_id": "el-conv-X", "user_id": "+15550000001"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["session_id"] == "el-conv-X"

        rows = await in_memory_ledger.fetch(baseworm_company_id)
        # PEVR cycle for the session opener (4 entries).
        assert len(rows) == 4
        execute = next(r for r in rows if r["kind"] == "execute")
        assert execute["payload"]["tool"] == "voice_agent.session_started"

    async def test_session_end_writes_session_closed(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger, kimi=fake_kimi, company_id=baseworm_company_id,
        )
        client.post(
            "/webhook/elevenlabs/session-start",
            json={"conversation_id": "el-conv-Z"},
        )
        r = client.post(
            "/webhook/elevenlabs/session-end",
            json={
                "conversation_id": "el-conv-Z",
                "ended_at": "2026-04-25T22:00:00Z",
                "recording_url": "/tmp/voice-audio/el-conv-Z-full.wav",
                "transcript_url": "/tmp/voice-audio/el-conv-Z-transcript.json",
                "turn_count": 3,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

        rows = await in_memory_ledger.fetch(baseworm_company_id)
        executes = [r for r in rows if r["kind"] == "execute"]
        tools = [e["payload"]["tool"] for e in executes]
        assert "voice_agent.session_started" in tools
        assert "voice_agent.session_closed" in tools
