"""Tail OpenClaw's global log file for ``<platform>: allow channel <CID>`` events.

OpenClaw writes one JSON object per line to ``openclaw-YYYY-MM-DD.log`` in
its log directory. For *every* inbound platform event — silent, mention,
file share, edit — across Slack, WhatsApp, and (eventually) other adapters,
it emits an entry whose ``"0"`` field starts with::

    <platform>: allow channel <CHANNEL_ID> (matchKey=... matchSource=...)

This is OpenClaw's own gate decision: the event was admitted to the agent
routing layer regardless of whether the agent ultimately spoke. Tailing
this log gives the channel-adapter a deterministic per-event signal that
is independent of session JSONL writes (which only happen when the agent
actually engages).

**Public contract — adding a platform.** :data:`_ALLOW_CHANNEL_RE` is the
public contract for which platforms this tailer surfaces. To add a platform,
extend the alternation on group(1) (e.g. ``(slack|whatsapp|discord)``) and
register a corresponding adapter at the dispatch boundary in ``service.py``.
The regex captures ``platform`` as group(1) and ``channel_id`` as group(2);
the callback receives ``(platform, channel_id)``.

WhatsApp's grammar (``whatsapp: allow channel <jid>``) is **assumed
symmetric to Slack pending empirical verification** against a running
OpenClaw instance with the WhatsApp adapter enabled. JIDs may include
``@s.whatsapp.net`` (DM) and ``@g.us`` (group); the ``\\S+`` capture in
group(2) is permissive enough to admit either.

Why a custom tailer (not watchdog or aiofiles): we need three behaviors
together — (a) start at end-of-file on first open (don't replay yesterday),
(b) follow the file like ``tail -f`` across appends, (c) re-open when the
date rolls over and OpenClaw rotates to a new ``-YYYY-MM-DD.log`` filename.
A handful of stdlib calls covers it; pulling watchdog into the wheel is
overkill.

Failure mode: best-effort. JSON parse errors, filesystem hiccups, and
missing files are logged and skipped — never raised. The agent-reply path
through OpenClaw is unaffected if this tailer wedges.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)


# Public contract: matches OpenClaw's ``<platform>: allow channel <CID>``
# log line. Group(1) is the platform name (added to the alternation when
# new platforms are wired in); group(2) is the channel id, kept as a
# permissive ``\S+`` so Slack channel ids (``C0123ABC``), WhatsApp DM
# jids (``5511999999999@s.whatsapp.net``), and WhatsApp group jids
# (``120363012345678901@g.us``) all admit. The downstream adapter decides
# whether the id resolves.
#
# Adding a platform = extending the alternation here AND registering an
# adapter in ``service.py`` — those are the only edits required.
_ALLOW_CHANNEL_RE = re.compile(r"^(slack|whatsapp): allow channel (\S+) ")

# Read this many bytes per poll; bounded so a slow consumer can't allocate
# unbounded memory if the log writer outpaces us briefly.
_READ_CHUNK_BYTES = 65536


class OpenClawLogTailer:
    """Follow OpenClaw's daily log file and surface channel admit events."""

    def __init__(
        self,
        log_dir: str | Path,
        on_event: Callable[[str, str], Awaitable[None]],
        *,
        poll_interval_s: float = 0.25,
    ) -> None:
        """Construct the tailer.

        ``on_event`` is called with ``(platform, channel_id)`` for each
        admitted line. Callers are responsible for dispatching to a
        platform-specific handler (or logging-and-dropping when no handler
        is registered).
        """
        self._log_dir = Path(log_dir)
        self._on_event = on_event
        self._poll = poll_interval_s
        self._stop = asyncio.Event()
        # Tracking the currently-open file lets us reopen on date rollover.
        self._current_path: Path | None = None
        self._fh: IO[bytes] | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Main loop. Runs until ``stop()`` is called."""
        log.info("openclaw-log-tail: watching %s", self._log_dir)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001
                log.exception("openclaw-log-tail: unexpected error in tick")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
                break
            except TimeoutError:
                continue
        self._close()

    async def _tick(self) -> None:
        path = self._latest_log_path()
        if path is None:
            return
        if self._current_path != path:
            # First open or rotation. Reset position to end-of-file so we
            # never replay yesterday's events on cold start.
            self._open_at_end(path)
        if self._fh is None:
            return
        # Detect truncation (e.g. logrotate copy-truncate). If size shrank
        # below our position, reset to start of the new content.
        try:
            st = path.stat()
        except FileNotFoundError:
            self._close()
            return
        if st.st_size < self._fh.tell():
            log.warning("openclaw-log-tail: file shrank, resetting to start")
            self._fh.seek(0)
        # Drain any pending lines.
        while True:
            line = self._fh.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                # Partial line — rewind so we re-read it complete next tick.
                self._fh.seek(-len(line), 1)
                return
            await self._handle_line(line)

    async def _handle_line(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8", errors="replace").rstrip("\n")
        except Exception:  # noqa: BLE001
            return
        if not text:
            return
        # OpenClaw emits one JSON object per line; the human-readable
        # message is keyed under "0" (a positional argument from the
        # logger's printf-style invocation). Older format may be a bare
        # string — handle both.
        msg: str | None = None
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                # Field "0" is the canonical message slot.
                candidate = obj.get("0")
                if isinstance(candidate, str):
                    msg = candidate
                else:
                    # Some entries put the message under "msg" or "message".
                    for key in ("msg", "message"):
                        v = obj.get(key)
                        if isinstance(v, str):
                            msg = v
                            break
            elif isinstance(obj, str):
                msg = obj
        except json.JSONDecodeError:
            # Plain-text line — match against it directly.
            msg = text

        if not msg:
            return
        m = _ALLOW_CHANNEL_RE.match(msg)
        if m is None:
            return
        platform = m.group(1)
        channel_id = m.group(2)
        try:
            await self._on_event(platform, channel_id)
        except Exception:  # noqa: BLE001
            log.exception(
                "openclaw-log-tail: on_event handler failed for %s/%s",
                platform,
                channel_id,
            )

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _latest_log_path(self) -> Path | None:
        """Return today's log file if present, else the most recent one."""
        if not self._log_dir.exists():
            return None
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        candidate = self._log_dir / f"openclaw-{today}.log"
        if candidate.exists():
            return candidate
        # Fall back to the lexicographically-newest matching file (date
        # rollover hasn't occurred yet today, or clock skew vs container).
        try:
            files = sorted(
                self._log_dir.glob("openclaw-*.log"),
                key=lambda p: p.name,
            )
        except OSError:
            return None
        return files[-1] if files else None

    def _open_at_end(self, path: Path) -> None:
        self._close()
        try:
            fh = path.open("rb")
        except OSError as exc:
            log.warning("openclaw-log-tail: cannot open %s: %s", path, exc)
            return
        fh.seek(0, 2)  # end
        self._fh = fh
        self._current_path = path
        log.info("openclaw-log-tail: tailing %s from offset %d", path, fh.tell())

    def _close(self) -> None:
        fh = self._fh
        self._fh = None
        self._current_path = None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass


__all__ = ["OpenClawLogTailer"]
