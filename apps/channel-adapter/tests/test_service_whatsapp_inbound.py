"""End-to-end test for the WhatsApp inbound chat_received wire-fix.

Synthesizes both streams concurrently:

* the OpenClaw daily log carries the inbound envelope
  (subsystem=``gateway/channels/whatsapp/inbound``, prose
  ``Inbound message +<sender> -> +<bot> (direct, N chars)``);
* the per-session JSONL carries a bare ``role=user`` frame with the
  raw body (no Slack envelope).

The wire-fix correlates them via the
:class:`WhatsAppInboundEnvelopeWatcher` cache so the parser emits a
WhatsApp-shaped :class:`ChatReceivedEvent` and the
:class:`LedgerWriter` lands a ``chat_received`` PEVR cycle in the
ledger.

This is the production proof: the same code path the deployed
channel-adapter runs exercises both files. If the fix regresses, this
test catches it before live verification.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_channel_adapter.parser import parse_session_line
from wormbase_channel_adapter.state import OffsetState
from wormbase_channel_adapter.tailer import Tailer, pump
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.whatsapp_envelope_watcher import (
    WhatsAppInboundEnvelopeWatcher,
)
from wormbase_channel_adapter.writer import LedgerWriter


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def _today_log(log_dir: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return log_dir / f"openclaw-{today}.log"


def _envelope_log_line(
    *,
    sender_phone: str = "5218117649489",
    bot_phone: str = "5218114822051",
    body_chars: int = 12,
    ts: datetime | None = None,
) -> str:
    if ts is None:
        ts = datetime.now(UTC)
    ts_iso = ts.isoformat(timespec="milliseconds")
    msg = (
        f"Inbound message +{sender_phone} -> +{bot_phone} "
        f"(direct, {body_chars} chars)"
    )
    return (
        json.dumps(
            {
                "0": '{"subsystem":"gateway/channels/whatsapp/inbound"}',
                "1": msg,
                "_meta": {"date": ts_iso},
                "time": ts_iso,
                "message": msg,
            }
        )
        + "\n"
    )


def _session_user_frame(
    *,
    body: str,
    event_id: str = "wa-evt-1",
    ts: datetime | None = None,
) -> str:
    if ts is None:
        ts = datetime.now(UTC)
    return (
        json.dumps(
            {
                "type": "message",
                "id": event_id,
                "timestamp": ts.isoformat(timespec="milliseconds"),
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": body}],
                },
            }
        )
        + "\n"
    )


def _executes(rows: list[dict], tool: str) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == tool
    ]


# ---------------------------------------------------------------------------
# E2E: synthetic streams in parallel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_envelope_correlates_to_session_frame(
    tmp_path: Path,
    writer: LedgerWriter,
    company_id: UUID,
) -> None:
    """The wire-fix end-to-end: envelope + session frame land
    chat_received in the ledger."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_id = "11111111-2222-3333-4444-555555555555"
    session_file = sessions_dir / f"{session_id}.jsonl"
    session_file.write_text("")

    state = OffsetState(str(tmp_path / "state.json"))

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)
    tailer = Tailer(
        sessions_dir,
        state,
        poll_interval_s=0.1,
        whatsapp_envelope_lookup=watcher.find_recent_envelope,
    )

    # Drive the watcher in background.
    watcher_task = asyncio.create_task(watcher.run())

    # Compose handler that just writes through the writer (mirrors
    # service.run_service's handler shape).
    async def handler(event) -> None:
        await writer.emit(event)

    pump_task = asyncio.create_task(pump(tailer, state, handler))

    try:
        # Give the watcher a beat to open the (empty) log file at end,
        # so the next append is observed.
        await asyncio.sleep(0.2)

        # 1. Drop the envelope into the daily log.
        ts_envelope = datetime.now(UTC)
        with log_file.open("a") as fh:
            fh.write(
                _envelope_log_line(
                    sender_phone="5218117649489",
                    bot_phone="5218114822051",
                    body_chars=6,
                    ts=ts_envelope,
                )
            )
            fh.flush()

        # Wait until the watcher caches it.
        deadline = asyncio.get_running_loop().time() + 3.0
        while asyncio.get_running_loop().time() < deadline:
            if len(watcher.envelopes) >= 1:
                break
            await asyncio.sleep(0.05)
        assert len(watcher.envelopes) >= 1, "watcher did not cache envelope"

        # 2. Drop the session-JSONL bare body. Body has no Slack envelope.
        with session_file.open("a") as fh:
            fh.write(
                _session_user_frame(
                    body="sup yo",
                    event_id="wa-evt-1",
                    ts=ts_envelope,
                )
            )
            fh.flush()

        # 3. Wait for the writer to land a chat_received PEVR cycle.
        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            rows = await writer._ledger.fetch(company_id)
            if _executes(rows, "channel_adapter.emit_chat_received"):
                break
            await asyncio.sleep(0.1)
    finally:
        watcher.stop()
        tailer.stop()
        for t in (watcher_task, pump_task):
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (TimeoutError, Exception):  # noqa: BLE001
                t.cancel()

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_executes) == 1, (
        f"expected 1 chat_received, got {len(chat_executes)}"
    )
    args = chat_executes[0]["payload"]["args"]
    assert args["channel_id"] == "5218117649489@s.whatsapp.net"
    assert args["message_id"] == "wa-evt-1"
    assert args["text"] == "sup yo"
    assert args["delivery_mode"] == "push"
    # Provenance carries the envelope's ts.
    assert args["platform_ts"] is not None


@pytest.mark.asyncio
async def test_session_frame_without_envelope_drops_silently(
    tmp_path: Path,
    writer: LedgerWriter,
    company_id: UUID,
) -> None:
    """No envelope hit → no chat_received write. Capability honesty."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_id = "deadbeef-2222-3333-4444-555555555555"
    session_file = sessions_dir / f"{session_id}.jsonl"
    session_file.write_text("")

    state = OffsetState(str(tmp_path / "state.json"))

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)
    tailer = Tailer(
        sessions_dir,
        state,
        poll_interval_s=0.1,
        whatsapp_envelope_lookup=watcher.find_recent_envelope,
    )

    watcher_task = asyncio.create_task(watcher.run())

    async def handler(event) -> None:
        await writer.emit(event)

    pump_task = asyncio.create_task(pump(tailer, state, handler))

    try:
        await asyncio.sleep(0.2)
        # Drop a session frame WITHOUT a matching envelope.
        with session_file.open("a") as fh:
            fh.write(_session_user_frame(body="orphan body"))
            fh.flush()
        await asyncio.sleep(0.6)
    finally:
        watcher.stop()
        tailer.stop()
        for t in (watcher_task, pump_task):
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (TimeoutError, Exception):  # noqa: BLE001
                t.cancel()

    rows = await writer._ledger.fetch(company_id)
    assert _executes(rows, "channel_adapter.emit_chat_received") == []


@pytest.mark.asyncio
async def test_run_service_wires_envelope_watcher_when_log_dir_set(
    tmp_path: Path,
) -> None:
    """Pin the wire contract: when ``openclaw_log_dir`` is provided to
    ``run_service`` (regardless of slack_bot_token), the construction
    path includes the envelope watcher.

    We don't run ``run_service`` end-to-end here — that needs a real
    ledger DSN — but inspect the source for the expected keyword
    threading. The integration coverage above proves the parts compose."""
    import inspect

    from wormbase_channel_adapter.service import run_service

    src = inspect.getsource(run_service)
    assert "WhatsAppInboundEnvelopeWatcher" in src, (
        "run_service must construct WhatsAppInboundEnvelopeWatcher"
    )
    assert "whatsapp_envelope_lookup" in src, (
        "run_service must thread whatsapp_envelope_lookup into Tailer"
    )


# ---------------------------------------------------------------------------
# Direct parser+writer pair: prove the chat_received emission shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parser_event_round_trips_through_writer(
    writer: LedgerWriter,
    company_id: UUID,
) -> None:
    """The synthetic parser path → writer.emit → ledger PEVR cycle.

    Tighter than the e2e integration: pins the writer-side shape
    independent of the file-tail timing dance.
    """
    body = "yo, what's up?"
    ts = datetime(2026, 5, 7, 4, 10, 50, tzinfo=UTC)
    envelope = type("E", (), {})()  # cheap stand-in
    # Use the watcher's WhatsAppInboundEnvelope so types stay honest.
    from wormbase_channel_adapter.whatsapp_envelope_watcher import (
        WhatsAppInboundEnvelope,
    )
    envelope = WhatsAppInboundEnvelope(
        ts=ts,
        sender_jid="5218117649489@s.whatsapp.net",
        bot_jid="5218114822051@s.whatsapp.net",
        chat_type="direct",
        char_count=len(body),
    )

    line = _session_user_frame(body=body, event_id="rt-evt-1", ts=ts)
    event = parse_session_line(
        line,
        session_id="sess-rt",
        whatsapp_envelope_lookup=lambda _ts, _w: envelope,
    )
    assert event is not None
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_executes) == 1
    args = chat_executes[0]["payload"]["args"]
    assert args["text"] == body
    assert args["channel_id"] == "5218117649489@s.whatsapp.net"
    assert args["message_id"] == "rt-evt-1"
