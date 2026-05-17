"""Integration tests for the tailer: file-based JSONL → ParsedEvent stream."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wormbase_channel_adapter.parser import ChatReceivedEvent, ChatSentEvent
from wormbase_channel_adapter.state import OffsetState
from wormbase_channel_adapter.tailer import Tailer, _is_relevant_jsonl, pump
from tests.conftest import (
    make_inbound_line,
    make_outbound_line,
    make_session_header_line,
    make_tool_call_line,
    make_tool_result_line,
)


class TestRelevantFileFilter:
    def test_jsonl_is_relevant(self, tmp_path: Path) -> None:
        f = tmp_path / "abc.jsonl"
        f.write_text("")
        assert _is_relevant_jsonl(f) is True

    def test_trajectory_jsonl_is_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "abc.trajectory.jsonl"
        f.write_text("")
        assert _is_relevant_jsonl(f) is False

    def test_trajectory_path_json_is_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "abc.trajectory-path.json"
        f.write_text("")
        assert _is_relevant_jsonl(f) is False


class TestTailerStream:
    @pytest.mark.asyncio
    async def test_yields_inbound_then_outbound(self, tmp_sessions_dir: Path) -> None:
        sess = tmp_sessions_dir / "sess-A.jsonl"
        sess.write_text(
            make_session_header_line()
            + make_inbound_line(event_id="in-1")
            + make_tool_call_line()
            + make_tool_result_line()
            + make_outbound_line(event_id="out-1", text="hi"),
            encoding="utf-8",
        )
        state = OffsetState(tmp_sessions_dir / "state.json")
        tailer = Tailer(tmp_sessions_dir, state, poll_interval_s=0.05)

        events = []
        async for event, _sid, _off in tailer.stream():
            events.append(event)
            if len(events) == 2:
                tailer.stop()
                break

        kinds = [type(e).__name__ for e in events]
        assert kinds == ["ChatReceivedEvent", "ChatSentEvent"]
        assert isinstance(events[0], ChatReceivedEvent)
        assert isinstance(events[1], ChatSentEvent)
        # in_reply_to is threaded through from the previous inbound.
        assert events[1].in_reply_to == events[0].message_id

    @pytest.mark.asyncio
    async def test_resumes_from_saved_offset(self, tmp_sessions_dir: Path) -> None:
        sess = tmp_sessions_dir / "sess-B.jsonl"
        first_chunk = make_session_header_line() + make_inbound_line(event_id="in-1")
        sess.write_text(first_chunk, encoding="utf-8")

        state = OffsetState(tmp_sessions_dir / "state.json")
        # Pre-seed the state as if we already processed the whole first chunk.
        state.set("sess-B", len(first_chunk.encode("utf-8")))
        state.save()

        # Append a new outbound line.
        with sess.open("a", encoding="utf-8") as fh:
            fh.write(make_outbound_line(event_id="out-1", text="resumed"))

        tailer = Tailer(tmp_sessions_dir, state, poll_interval_s=0.05)
        events = []
        async for event, sid, off in tailer.stream():
            events.append((event, sid, off))
            tailer.stop()
            break

        assert len(events) == 1
        evt, sid, _off = events[0]
        assert sid == "sess-B"
        # Note: in_reply_to is None because the inbound was BEFORE the
        # restart's start offset; we don't backfill the inbound cache.
        assert isinstance(evt, ChatSentEvent)
        assert evt.text == "resumed"

    @pytest.mark.asyncio
    async def test_partial_line_is_held_until_newline(self, tmp_sessions_dir: Path) -> None:
        sess = tmp_sessions_dir / "sess-C.jsonl"
        # Write an outbound line WITHOUT trailing newline.
        partial = make_outbound_line(event_id="out-1", text="partial").rstrip("\n")
        sess.write_text(partial, encoding="utf-8")

        state = OffsetState(tmp_sessions_dir / "state.json")
        tailer = Tailer(tmp_sessions_dir, state, poll_interval_s=0.05)

        async def reader() -> list:
            out = []
            async for event, sid, off in tailer.stream():
                out.append((event, sid, off))
                if len(out) == 1:
                    tailer.stop()
                    break
            return out

        # Without the newline, the tailer should NOT yield. We give it
        # 200ms then complete the line; only then should we see the event.
        task = asyncio.create_task(reader())
        await asyncio.sleep(0.2)
        with sess.open("a", encoding="utf-8") as fh:
            fh.write("\n")
        events = await asyncio.wait_for(task, timeout=1.0)
        assert len(events) == 1
        evt, _sid, _off = events[0]
        assert isinstance(evt, ChatSentEvent)


class TestPump:
    @pytest.mark.asyncio
    async def test_pump_advances_offset_only_after_handler_succeeds(
        self, tmp_sessions_dir: Path
    ) -> None:
        sess = tmp_sessions_dir / "sess-D.jsonl"
        sess.write_text(
            make_inbound_line(event_id="in-1") + make_outbound_line(event_id="out-1"),
            encoding="utf-8",
        )
        state = OffsetState(tmp_sessions_dir / "state.json")
        tailer = Tailer(tmp_sessions_dir, state, poll_interval_s=0.05)

        seen = 0

        async def handler(_event: object) -> None:
            nonlocal seen
            seen += 1
            if seen == 2:
                tailer.stop()

        await asyncio.wait_for(pump(tailer, state, handler), timeout=2.0)
        # Both events were handled.
        assert seen == 2
        # Offset advanced past both lines.
        assert state.get("sess-D") == sess.stat().st_size

    @pytest.mark.asyncio
    async def test_pump_does_not_advance_offset_on_handler_error(
        self, tmp_sessions_dir: Path
    ) -> None:
        sess = tmp_sessions_dir / "sess-E.jsonl"
        sess.write_text(make_inbound_line(event_id="in-1"), encoding="utf-8")
        state = OffsetState(tmp_sessions_dir / "state.json")
        tailer = Tailer(tmp_sessions_dir, state, poll_interval_s=0.05)

        async def boom(_event: object) -> None:
            tailer.stop()
            raise RuntimeError("downstream error")

        await asyncio.wait_for(pump(tailer, state, boom), timeout=2.0)
        # No offset advance because handler raised.
        assert state.get("sess-E") == 0
