"""Audit semantics for voice turns.

Every voice turn must produce one ``chat_received`` and one
``chat_sent`` ledger entry (each via the canonical PEVR cycle), both
tagged with ``modality="voice"`` so JSONB queries can find the voice
exchange.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore
from wormbase_voice_agent.audit import (
    emit_chat_received,
    emit_chat_sent,
    voice_channel_id,
)


def _executes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["kind"] == "execute"]


@pytest.mark.asyncio
class TestEmitHelpers:
    async def test_emit_chat_received_writes_pevr_with_voice_modality(
        self, in_memory_ledger, baseworm_company_id: UUID,
    ) -> None:
        await emit_chat_received(
            in_memory_ledger,
            company_id=baseworm_company_id,
            session_id="sess-A",
            message_id="msg-in-1",
            text="What was Q3 net revenue?",
            caller_id="+15555550100",
            audio_ref="/tmp/voice-audio/msg-in-1.wav",
        )
        rows = await in_memory_ledger.fetch(baseworm_company_id)
        # PEVR = 4 entries.
        assert [r["kind"] for r in rows] == [
            "propose", "execute", "verify", "resolve",
        ]
        execute = _executes(rows)[0]
        # modality + audio_ref live at the execute payload's top level
        # alongside tool / args / result_ref.
        assert execute["payload"]["modality"] == "voice"
        assert execute["payload"]["audio_ref"] == "/tmp/voice-audio/msg-in-1.wav"
        assert execute["payload"]["tool"] == "voice_agent.emit_chat_received"
        # The args body validates as ChatReceivedPayload.
        from wormbase_ledger.entries import ChatReceivedPayload
        payload = ChatReceivedPayload.model_validate(execute["payload"]["args"])
        assert payload.channel_id == voice_channel_id("sess-A")
        assert payload.text == "What was Q3 net revenue?"

    async def test_emit_chat_sent_writes_pevr_with_voice_modality(
        self, in_memory_ledger, baseworm_company_id: UUID,
    ) -> None:
        await emit_chat_sent(
            in_memory_ledger,
            company_id=baseworm_company_id,
            session_id="sess-A",
            message_id="msg-out-1",
            text="Q3 net revenue was four point two million dollars.",
            in_reply_to="msg-in-1",
            audio_ref="/tmp/voice-audio/msg-out-1.wav",
        )
        rows = await in_memory_ledger.fetch(baseworm_company_id)
        execute = _executes(rows)[0]
        assert execute["payload"]["modality"] == "voice"
        assert execute["payload"]["audio_ref"] == "/tmp/voice-audio/msg-out-1.wav"
        from wormbase_ledger.entries import ChatSentPayload
        payload = ChatSentPayload.model_validate(execute["payload"]["args"])
        assert payload.channel_id == voice_channel_id("sess-A")
        assert payload.in_reply_to == "msg-in-1"
        assert payload.attribution["source"] == "voice-agent"

    async def test_voice_channel_id_format(self) -> None:
        assert voice_channel_id("abc123") == "voice:elevenlabs:abc123"


class TestWebhookEndToEndAudit:
    """Full webhook cycle: one turn → received + sent in the ledger."""

    def _client(
        self, ledger: Any, kimi: Any, company_id: UUID,
    ) -> TestClient:
        state = VoiceAppState(
            ledger=ledger,
            kimi=kimi,
            audio_store=AudioStore("/tmp/voice-audio-test"),
            tenant_slug="baseworm",
            company_id=company_id,
        )
        return TestClient(create_app(state=state))

    @pytest.mark.asyncio
    async def test_one_webhook_turn_yields_both_chat_kinds(
        self, in_memory_ledger, baseworm_company_id: UUID, fake_kimi,
    ) -> None:
        client = self._client(in_memory_ledger, fake_kimi, baseworm_company_id)
        r = client.post(
            "/webhook/elevenlabs",
            json={
                "model": "kimi-k2.6:cloud",
                "conversation_id": "sess-AUD-1",
                "user_id": "+15555550199",
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "How are we tracking on Q3?"},
                ],
            },
        )
        assert r.status_code == 200, r.text

        rows = await in_memory_ledger.fetch(baseworm_company_id)
        # Two PEVR groups (one per chat_received + chat_sent) = 8 entries.
        assert len(rows) == 8

        executes = _executes(rows)
        tools = [e["payload"]["tool"] for e in executes]
        assert "voice_agent.emit_chat_received" in tools
        assert "voice_agent.emit_chat_sent" in tools

        # BOTH entries carry modality=voice.
        for e in executes:
            assert e["payload"]["modality"] == "voice"

        # Hash chain stays intact across the 8-row run.
        report = await in_memory_ledger.verify(baseworm_company_id)
        assert report.ok is True
        assert report.entries_checked == 8

        # Channel id points at voice:elevenlabs:<session>.
        for e in executes:
            args = e["payload"]["args"]
            assert args["channel_id"] == voice_channel_id("sess-AUD-1")

    @pytest.mark.asyncio
    async def test_chat_sent_attribution_carries_received_chain(
        self, in_memory_ledger, baseworm_company_id: UUID, fake_kimi,
    ) -> None:
        client = self._client(in_memory_ledger, fake_kimi, baseworm_company_id)
        r = client.post(
            "/webhook/elevenlabs",
            json={
                "conversation_id": "sess-LINK",
                "messages": [
                    {"role": "user", "content": "Q3 number?"},
                ],
            },
        )
        assert r.status_code == 200

        rows = await in_memory_ledger.fetch(baseworm_company_id)
        sent_execute = next(
            e for e in _executes(rows)
            if e["payload"]["tool"] == "voice_agent.emit_chat_sent"
        )
        attr = sent_execute["payload"]["args"]["attribution"]
        # The reply records which received-cycle entry ids it answers.
        assert "received_chat_ids" in attr
        assert isinstance(attr["received_chat_ids"], list)
        assert len(attr["received_chat_ids"]) == 4  # PEVR ids of received cycle
