"""Audio storage + ledger linkage tests.

The demo build writes audio blobs as filesystem files under
``/tmp/voice-audio/<turn_id>.<ext>`` and stores the path string in the
ledger entry. We assert that:

- A blob written via :class:`AudioStore` lands at the expected path with
  the expected sha256.
- Storage failure does not break the ledger write — :func:`emit_chat_received`
  still produces a PEVR cycle, just with ``audio_ref = None``.
- The :class:`VoiceAgent` programmatic facade plumbs the audio path
  through the ledger.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from wormbase_voice_agent import VoiceAgent, VoiceAgentConfig, VoiceTurn
from wormbase_voice_agent.audio_store import AudioStore
from wormbase_voice_agent.audit import emit_chat_received


def _executes(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["kind"] == "execute"]


class TestAudioStore:
    def test_write_blob_creates_file_with_expected_hash(self, tmp_path: Path) -> None:
        store = AudioStore(tmp_path)
        blob = b"\x52\x49\x46\x46fake_wav_header_bytes_here"
        stored = store.write_blob("turn-001", blob, ext="wav")
        assert stored.path == str(tmp_path / "turn-001.wav")
        assert Path(stored.path).read_bytes() == blob
        assert stored.sha256 == hashlib.sha256(blob).hexdigest()
        assert stored.size_bytes == len(blob)

    def test_path_for_sanitizes_slashes(self, tmp_path: Path) -> None:
        store = AudioStore(tmp_path)
        # Caller can't escape the audio root: the path's parent must be
        # the configured root, regardless of slashes in the turn id.
        target = store.path_for("../../etc/passwd", ext="wav")
        assert target.parent == tmp_path
        # No path separators leaked into the file name.
        assert "/" not in target.name
        assert "\\" not in target.name

    def test_default_root_is_tmp_voice_audio(self) -> None:
        # AudioStore() with no args points at /tmp/voice-audio (the
        # production demo location).
        s = AudioStore()
        assert str(s.root) == "/tmp/voice-audio"


@pytest.mark.asyncio
class TestLedgerLinksAudioRef:
    async def test_audio_ref_path_lands_in_execute_payload(
        self, tmp_path: Path, in_memory_ledger, baseworm_company_id: UUID,
    ) -> None:
        store = AudioStore(tmp_path)
        stored = store.write_blob("phone-turn-007", b"opus_bytes", ext="mp3")
        # Confirm the file actually exists at /tmp/voice-audio-equivalent/<turn>.<ext>.
        assert Path(stored.path).is_file()

        await emit_chat_received(
            in_memory_ledger,
            company_id=baseworm_company_id,
            session_id="sess-AUDIO",
            message_id="msg-007",
            text="What's the runway?",
            caller_id="+15550000007",
            audio_ref=stored.path,
        )
        rows = await in_memory_ledger.fetch(baseworm_company_id)
        execute = _executes(rows)[0]
        # The path stored in the ledger matches the on-disk path.
        assert execute["payload"]["audio_ref"] == stored.path
        assert execute["payload"]["audio_ref"].startswith(str(tmp_path))

    async def test_storage_failure_does_not_block_ledger_write(
        self, in_memory_ledger, baseworm_company_id: UUID,
    ) -> None:
        # Caller passes audio_ref=None to simulate a storage outage. The
        # ledger entry must still write successfully; we lose only the
        # audio reference.
        await emit_chat_received(
            in_memory_ledger,
            company_id=baseworm_company_id,
            session_id="sess-NO-AUDIO",
            message_id="msg-008",
            text="What's our cash position?",
            caller_id="+15550000008",
            audio_ref=None,
        )
        rows = await in_memory_ledger.fetch(baseworm_company_id)
        assert len(rows) == 4  # PEVR
        execute = _executes(rows)[0]
        assert execute["payload"]["audio_ref"] is None
        # The chain is still valid — every byte hash-chainable.
        report = await in_memory_ledger.verify(baseworm_company_id)
        assert report.ok is True


@pytest.mark.asyncio
class TestVoiceAgentFacade:
    async def test_handle_turn_writes_two_chat_entries_via_facade(
        self, tmp_path: Path, in_memory_ledger, baseworm_company_id: UUID, fake_kimi,
    ) -> None:
        # The high-level facade carries an AudioRef through the ledger.
        from wormbase_voice_agent import AudioRef

        store = AudioStore(tmp_path)
        stored = store.write_blob("turn-IN", b"phone_bytes", ext="wav")

        config = VoiceAgentConfig(
            company_id=baseworm_company_id,
            voice_provider="elevenlabs",
            audio_bucket=str(tmp_path),
        )
        agent = VoiceAgent(config, ledger=in_memory_ledger, kimi=fake_kimi)

        turn = VoiceTurn(
            session_id="sess-FACADE",
            company_id=baseworm_company_id,
            transcript="What's the headcount?",
            audio_ref=AudioRef(
                storage_url=stored.path,
                sha256=stored.sha256,
                duration_ms=1500,
                transcript_method="elevenlabs-stt",
                speaker="caller",
            ),
            messages=[{"role": "user", "content": "What's the headcount?"}],
            caller_id="+15550000099",
        )
        reply = await agent.handle_turn(turn)
        assert reply.text == fake_kimi._reply

        rows = await in_memory_ledger.fetch(baseworm_company_id)
        assert len(rows) == 8  # two PEVR cycles

        executes = _executes(rows)
        # The inbound execute carries the storage path; the outbound is
        # None because TTS rendering happens upstream at ElevenLabs.
        received = next(
            e for e in executes
            if e["payload"]["tool"] == "voice_agent.emit_chat_received"
        )
        assert received["payload"]["audio_ref"] == stored.path
