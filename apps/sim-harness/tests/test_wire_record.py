"""Tests for WireRecorder."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload

from wormbase_sim_harness.wire_record import RECORD_TOOLS, WireRecorder


pytestmark = pytest.mark.asyncio


async def _emit_chat_received(
    ledger: InMemoryLedger, company_id, *, text: str, channel: str, ts: str,
) -> None:
    payload = ChatReceivedPayload(
        channel_id=channel,
        message_id=ts,
        sender_person=uuid4(),
        text=text,
        classification="internal",
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "test_wire_record",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": payload.model_dump(mode="json"),
            "result_ref": ts,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        quadrant="active_probabilistic",
    )


async def test_recorder_writes_jsonl_for_chat_received(tmp_path: Path) -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    out = tmp_path / "wire.jsonl"
    rec = WireRecorder(ledger=ledger, company_id=company_id, out_path=out)

    await _emit_chat_received(
        ledger, company_id, text="hi worm", channel="C0X", ts="111.000001",
    )

    n = await rec.run_once()
    assert n == 1
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool"] == "channel_adapter.emit_chat_received"
    assert record["args"]["text"] == "hi worm"
    assert record["args"]["channel_id"] == "C0X"
    assert record["seq"] > 0


async def test_recorder_skips_non_wire_tools(tmp_path: Path) -> None:
    """Worm-internal entries (emit_source_proposed etc.) must NOT be recorded.
    Only the wire-input toolset goes into the JSONL."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    out = tmp_path / "wire.jsonl"
    rec = WireRecorder(ledger=ledger, company_id=company_id, out_path=out)

    # A non-wire entry: this is the kind of thing wire-replay should regenerate
    # by re-running the worm against the wire input, not replay verbatim.
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(uuid4()),
            "reason": "noise",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_memory_written",
            "args": {"memory_id": str(uuid4()), "content": "noise", "tags": []},
            "result_ref": "x",
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        quadrant="passive_deterministic",
    )

    n = await rec.run_once()
    assert n == 0
    assert out.read_text() == ""


async def test_recorder_advances_last_seq(tmp_path: Path) -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    out = tmp_path / "wire.jsonl"
    rec = WireRecorder(ledger=ledger, company_id=company_id, out_path=out)

    await _emit_chat_received(
        ledger, company_id, text="one", channel="C0", ts="1.0",
    )
    n = await rec.run_once()
    assert n == 1

    # Second call: nothing new — last_seq has advanced.
    n2 = await rec.run_once()
    assert n2 == 0
    assert len(out.read_text().splitlines()) == 1

    # Add a new event: only the new one is recorded.
    await _emit_chat_received(
        ledger, company_id, text="two", channel="C0", ts="2.0",
    )
    n3 = await rec.run_once()
    assert n3 == 1
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["args"]["text"] == "two"


async def test_recorder_constant_record_tools_matches_default() -> None:
    """The exposed RECORD_TOOLS constant matches the default WireRecorder tuple."""
    rec = WireRecorder(
        ledger=InMemoryLedger(), company_id=uuid4(),
        out_path=Path("/tmp/_wire_record_tools_check.jsonl"),
    )
    assert rec._record_tools == RECORD_TOOLS  # noqa: SLF001
    assert "channel_adapter.emit_chat_received" in RECORD_TOOLS
    assert "channel_adapter.emit_chat_sent" in RECORD_TOOLS
    assert "channel_adapter.emit_file_received" in RECORD_TOOLS
