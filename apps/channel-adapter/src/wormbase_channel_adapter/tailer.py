"""Filesystem-tailing of OpenClaw session JSONL files.

We poll the sessions directory at ``poll_interval_s`` (default 0.5s) and
for each ``*.jsonl`` file (excluding ``*.trajectory.jsonl`` — that's
OpenClaw's internal model trace, not the channel-relevant log):

* If we have not seen the file before, start at offset 0.
* If we have seen it, ``seek`` to the saved offset and read forward.
* For every newline-terminated line, hand the raw text + the last-known
  inbound ``message_id`` to ``parse_session_line``.
* Persist the new offset *after* the parse callback completes — so a
  crash mid-write leaves the offset behind, and the line will be re-read
  on next start. Re-read is safe: the writer's only side effect is the
  ledger insert, which is idempotent only at the propose-args level
  (i.e. duplicates ARE possible on crash; downstream consumers dedup at
  the ``message_id`` level via the lurker poller's seq tracking).

Why poll instead of inotify/watchdog: container portability. macOS,
Linux, and the docker-for-mac VM all behave identically with stat-based
polling. inotify on a bind-mounted volume is unreliable on macOS, and
the watchdog package adds a ~200ms latency floor anyway.

We expose ``Tailer`` as an async iterator so the service layer can drive
it in a single ``async for`` loop without owning poll-loop scheduling.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    ParsedEvent,
    WhatsAppEnvelopeLookup,
    parse_session_line,
)
from wormbase_channel_adapter.state import OffsetState

log = logging.getLogger(__name__)

# We deliberately skip the trajectory file (model thinking traces) and
# the sessions index — they're not chat traffic.
_SKIP_SUFFIXES = (".trajectory.jsonl", ".trajectory-path.json")


class Tailer:
    """Tail JSONL files in a directory, yielding ParsedEvents."""

    def __init__(
        self,
        sessions_path: str | os.PathLike[str],
        state: OffsetState,
        poll_interval_s: float = 0.5,
        *,
        whatsapp_envelope_lookup: WhatsAppEnvelopeLookup | None = None,
    ) -> None:
        self._dir = Path(sessions_path)
        self._state = state
        self._poll = poll_interval_s
        # session_id -> last seen inbound slack message_id (for in_reply_to)
        self._last_inbound: dict[str, str] = {}
        self._stop = asyncio.Event()
        # Optional envelope-lookup callable threaded into parser. When
        # ``None``, Slack-only behavior is byte-identical with the
        # pre-WhatsApp wire.
        self._whatsapp_envelope_lookup = whatsapp_envelope_lookup

    def stop(self) -> None:
        self._stop.set()

    async def stream(self) -> AsyncIterator[tuple[ParsedEvent, str, int]]:
        """Yield ``(event, session_id, new_offset)`` tuples.

        The caller is responsible for calling ``state.set(...)`` and
        ``state.save()`` after a successful downstream side effect; this
        keeps the at-least-once semantic crash-safe. Tailer mutates only
        its in-memory ``_last_inbound`` dict, never the on-disk state.
        """
        if not self._dir.exists():
            log.warning("sessions dir does not exist yet: %s", self._dir)
        while not self._stop.is_set():
            try:
                async for event, session_id, new_offset in self._scan_once():
                    yield event, session_id, new_offset
            except FileNotFoundError as e:
                log.debug("scan: file vanished mid-read: %s", e)
            except Exception:
                log.exception("scan: unexpected error; backing off")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
                return  # stop was set
            except TimeoutError:
                continue

    async def _scan_once(self) -> AsyncIterator[tuple[ParsedEvent, str, int]]:
        if not self._dir.exists():
            return
        files = sorted(p for p in self._dir.iterdir() if _is_relevant_jsonl(p))
        for path in files:
            session_id = path.stem  # "<uuid>"
            offset = self._state.get(session_id)
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            if size <= offset:
                continue
            async for event, new_offset in self._read_from(path, session_id, offset):
                yield event, session_id, new_offset

    async def _read_from(
        self, path: Path, session_id: str, start_offset: int
    ) -> AsyncIterator[tuple[ParsedEvent, int]]:
        # We open in binary so byte offsets are exact regardless of any
        # multi-byte chars (Slack messages frequently contain emoji).
        with path.open("rb") as fh:
            fh.seek(start_offset)
            buffered_offset = start_offset
            while True:
                line = fh.readline()
                if not line:
                    return
                buffered_offset += len(line)
                # Skip incomplete trailing line (no newline yet — writer
                # is still flushing). We'll pick it up next poll.
                if not line.endswith(b"\n"):
                    return
                try:
                    text = line.decode("utf-8")
                except UnicodeDecodeError:
                    log.warning("non-utf8 line in %s; skipping", path)
                    continue
                last_inbound = self._last_inbound.get(session_id)
                event = parse_session_line(
                    text,
                    session_id=session_id,
                    last_inbound_message_id=last_inbound,
                    whatsapp_envelope_lookup=self._whatsapp_envelope_lookup,
                )
                if event is None:
                    continue
                if isinstance(event, ChatReceivedEvent):
                    self._last_inbound[session_id] = event.message_id
                yield event, buffered_offset


# ---------------------------------------------------------------------------
# Top-level pump: tail + emit, sequentially per file (preserves chain order).
# ---------------------------------------------------------------------------


async def pump(
    tailer: Tailer,
    state: OffsetState,
    handler: Callable[[ParsedEvent], Awaitable[None]],
) -> None:
    """Drive ``tailer`` and call ``handler`` on each event.

    On successful handler return, persist the new offset. On handler
    error, log + skip the offset advance so we'll retry next loop.
    """
    async for event, session_id, new_offset in tailer.stream():
        try:
            await handler(event)
        except Exception:
            log.exception("handler failed for %s/%s; will retry", session_id, event.event_id)
            continue
        state.set(session_id, new_offset)
        try:
            state.save()
        except OSError:
            log.exception("offset save failed; continuing in-memory")


def _is_relevant_jsonl(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name
    if not name.endswith(".jsonl"):
        return False
    return not any(name.endswith(suf) for suf in _SKIP_SUFFIXES)
