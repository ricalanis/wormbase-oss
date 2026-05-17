"""Tail OpenClaw's daily log for WhatsApp inbound envelope metadata.

Background — why this watcher exists:

OpenClaw 2026.5.6 routes WhatsApp inbound messages through the agent
session JSONL (where the parser sees a ``role=user`` frame containing the
raw message body — e.g. ``"sup yo"``) but does NOT emit a Slack-style
``whatsapp: allow channel <jid>`` admit signal in the daily log. As a
result, the WhatsApp branch of :class:`OpenClawLogTailer` never fires and
the WhatsApp dispatch handler in :func:`run_service` never runs, so
``WhatsAppLogCapture`` never gets a chance to write ``chat_received``.

What OpenClaw DOES emit is a separate per-message log entry with
subsystem ``gateway/channels/whatsapp/inbound`` carrying the envelope
metadata — sender phone, recipient (bot) phone, chat type — but no body.
The body is only in the session JSONL.

The fix this module enables: a small in-memory cache of recent inbound
envelopes that the session-JSONL parser can correlate against. When a
``role=user`` frame with no Slack envelope arrives, the parser asks this
watcher for the most-recent envelope within a tight time window
(default 30s); if there's a match, the parser emits a WhatsApp-shaped
``ChatReceivedEvent`` with the sender's jid attached.

Empirical log line shape (from /tmp/openclaw/openclaw-YYYY-MM-DD.log on
the user's stack, captured 2026-05-07T04:10):

    {
      "0": "{\"subsystem\":\"gateway/channels/whatsapp/inbound\"}",
      "1": "Inbound message +5218117649489 -> +5218114822051 (direct, 62 chars)",
      "_meta": {...},
      "time": "2026-05-07T04:10:49.849+00:00",
      "message": "Inbound message +5218117649489 -> +5218114822051 (direct, 62 chars)"
    }

Behavioral contract:

- We only consider lines whose ``"0"`` field carries the
  ``gateway/channels/whatsapp/inbound`` subsystem AND whose ``"1"`` /
  ``message`` field matches the inbound regex.
- Envelopes are cached in a bounded deque (default 256 entries); oldest
  evicted when full.
- ``find_recent_envelope(target_ts, window_s=30.0)`` returns the most
  recent envelope whose ``ts`` falls within ``[target_ts - window_s,
  target_ts + window_s]``. None when no match.
- The returned ``sender_jid`` is reconstructed by stripping the leading
  ``+`` from the captured E.164 phone and appending ``@s.whatsapp.net``
  so it matches B2's identity-discovery regex
  (``^\\d+@s\\.whatsapp\\.net$``).
- Group messages (``chat_type == "group"``) are still cached — the
  parser decides what to do with them. Today we only correlate DMs, but
  caching everything is forward-compatible and trivially cheap.

Failure mode: best-effort. JSON parse errors, regex misses, and
filesystem hiccups are logged-and-skipped, never raised. The
session-JSONL path stays Slack-byte-identical when this watcher is
absent (parser falls through to None).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Literal

log = logging.getLogger(__name__)


# Public contract — the inbound envelope grammar OpenClaw 2026.5.6 emits.
# Captures sender phone (E.164 digits, no leading +), bot phone, chat
# type, and an optional char count. Exactly anchored so a near-miss line
# (e.g. an outbound or status-update message with similar prose) can't
# spuriously match.
_INBOUND_ENVELOPE_RE = re.compile(
    r"^Inbound message \+(?P<sender>\d+) -> \+(?P<bot>\d+) "
    r"\((?P<chat_type>direct|group)(?:, (?P<char_count>\d+) chars)?\)$"
)

# Subsystem marker we filter on; must appear inside obj["0"] (which
# OpenClaw stringifies as JSON of ``{"subsystem": ...}``).
_INBOUND_SUBSYSTEM = "gateway/channels/whatsapp/inbound"

# Bound the recent-envelope cache. 256 covers a busy WhatsApp install's
# ~5min of inbound traffic (DM + small groups) at a generous burst rate;
# the lookup window is 30s by default, so anything older is irrelevant
# anyway. Memory cost is ~32KB at the cap — negligible.
_DEFAULT_CACHE_SIZE = 256

# Default correlation window for ``find_recent_envelope``. 30s comfortably
# absorbs OpenClaw's gateway → agent dispatch latency (typically <500ms)
# while staying tight enough that a separate inbound from a different
# sender can't spuriously match. Tunable per call.
_DEFAULT_WINDOW_S = 30.0


@dataclass(frozen=True)
class WhatsAppInboundEnvelope:
    """One inbound envelope observation from OpenClaw's daily log.

    The ``sender_jid`` and ``bot_jid`` fields are reconstructed from the
    log's ``+<E.164>`` phone-number prose so they match the canonical
    Baileys jid grammar (``<digits>@s.whatsapp.net`` for DMs); B2's
    identity-discovery regex consumes them directly.

    Group messages set ``chat_type == "group"`` but currently the log
    only carries the conversation phone in ``+<E.164>`` form, not a
    group jid. The watcher caches them for forward-compat but the
    parser path keys off ``chat_type == "direct"`` for correlation.
    """

    ts: datetime  # log line's ``time`` field, parsed to tz-aware UTC
    sender_jid: str  # f"{sender_phone}@s.whatsapp.net"
    bot_jid: str  # f"{bot_phone}@s.whatsapp.net"
    chat_type: Literal["direct", "group"]
    char_count: int | None


class WhatsAppInboundEnvelopeWatcher:
    """Tail OpenClaw's daily log; expose recent WhatsApp inbound envelopes.

    Mirrors the file-rotation + tail-from-end shape of
    :class:`OpenClawLogTailer` but consumes a different subset of log
    lines and exposes a lookup API instead of a callback.

    Lifecycle:

    - ``run()`` is the long-lived async loop; call it as a task.
    - ``stop()`` halts the loop on next tick.
    - ``find_recent_envelope(target_ts, window_s=30.0)`` is safe to call
      from any coroutine concurrently with ``run()``; the deque is
      append-only from the loop thread and reads are best-effort.

    Failure mode: bounded-best-effort. Filesystem errors and parse
    failures are logged-and-skipped; the watcher does NOT raise on
    transient I/O. The session-JSONL parser stays correct in absence of
    this watcher (no envelope match → return None).
    """

    def __init__(
        self,
        log_dir: str | Path,
        *,
        poll_interval_s: float = 0.25,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._poll = poll_interval_s
        self._stop = asyncio.Event()
        # Tracking the currently-open file lets us reopen on date rollover.
        self._current_path: Path | None = None
        self._fh: IO[bytes] | None = None
        # Bounded ring of recent envelopes; newest at right end.
        self._envelopes: deque[WhatsAppInboundEnvelope] = deque(
            maxlen=cache_size,
        )

    @property
    def envelopes(self) -> tuple[WhatsAppInboundEnvelope, ...]:
        """Snapshot of cached envelopes (test hook)."""
        return tuple(self._envelopes)

    def stop(self) -> None:
        self._stop.set()

    def find_recent_envelope(
        self,
        target_ts: datetime,
        window_s: float = _DEFAULT_WINDOW_S,
    ) -> WhatsAppInboundEnvelope | None:
        """Return the most-recent envelope within ``window_s`` of ``target_ts``.

        Walks the cache newest-to-oldest. The first envelope whose
        ``abs(env.ts - target_ts) <= window_s`` wins. Returns None when
        the cache is empty or no envelope is within the window.

        ``target_ts`` is typically the session-JSONL frame's timestamp
        (already tz-aware UTC). The window asymmetry doesn't matter
        much — agent processing introduces 100-2000ms of latency
        between OpenClaw logging the envelope and the session JSONL
        landing the user-role frame, so the parser's frame ts is
        always slightly AFTER the envelope ts. A 30s window absorbs
        unlikely worst-case stalls without crossing into "this is a
        different message" territory.
        """
        if not self._envelopes:
            return None
        if target_ts.tzinfo is None:
            # Defensive: callers should pass tz-aware. If naive, assume
            # UTC and warn — never raise.
            log.debug(
                "find_recent_envelope received naive ts=%s; assuming UTC",
                target_ts,
            )
            target_ts = target_ts.replace(tzinfo=UTC)
        delta = timedelta(seconds=window_s)
        # Iterate newest-first so we surface the most-recent within window.
        for env in reversed(self._envelopes):
            if abs(env.ts - target_ts) <= delta:
                return env
        return None

    # ------------------------------------------------------------------
    # Tail loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop. Runs until ``stop()`` is called."""
        log.info("whatsapp-envelope-watcher: watching %s", self._log_dir)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001
                log.exception(
                    "whatsapp-envelope-watcher: unexpected error in tick",
                )
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
            self._open_at_end(path)
        if self._fh is None:
            return
        try:
            st = path.stat()
        except FileNotFoundError:
            self._close()
            return
        if st.st_size < self._fh.tell():
            log.warning(
                "whatsapp-envelope-watcher: file shrank, resetting to start",
            )
            self._fh.seek(0)
        while True:
            line = self._fh.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                # Partial — rewind so we re-read complete next tick.
                self._fh.seek(-len(line), 1)
                return
            self._handle_line(line)

    def _handle_line(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8", errors="replace").rstrip("\n")
        except Exception:  # noqa: BLE001
            return
        if not text:
            return
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(obj, dict):
            return
        # Filter: subsystem marker must be in obj["0"]. OpenClaw stringifies
        # this as ``{"subsystem":"gateway/channels/whatsapp/inbound"}``, so
        # a substring match is sufficient and robust to trivial format
        # tweaks (whitespace, quote style).
        subsystem_field = obj.get("0")
        if not isinstance(subsystem_field, str):
            return
        if _INBOUND_SUBSYSTEM not in subsystem_field:
            return
        # The envelope text lives in obj["1"] AND obj["message"] (OpenClaw
        # writes both — whichever is present and matches wins).
        candidates: list[str] = []
        for key in ("1", "message"):
            v = obj.get(key)
            if isinstance(v, str):
                candidates.append(v)
        match: re.Match[str] | None = None
        envelope_text: str | None = None
        for c in candidates:
            m = _INBOUND_ENVELOPE_RE.match(c)
            if m is not None:
                match = m
                envelope_text = c
                break
        if match is None:
            return
        ts = self._parse_log_ts(obj)
        if ts is None:
            log.debug(
                "whatsapp-envelope-watcher: missing/invalid time on line; "
                "skipping (text=%r)",
                envelope_text,
            )
            return
        sender_phone = match.group("sender")
        bot_phone = match.group("bot")
        chat_type_raw = match.group("chat_type")
        if chat_type_raw not in ("direct", "group"):
            return
        char_count_raw = match.group("char_count")
        char_count: int | None
        if char_count_raw is None:
            char_count = None
        else:
            try:
                char_count = int(char_count_raw)
            except ValueError:
                char_count = None
        env = WhatsAppInboundEnvelope(
            ts=ts,
            sender_jid=f"{sender_phone}@s.whatsapp.net",
            bot_jid=f"{bot_phone}@s.whatsapp.net",
            chat_type=chat_type_raw,  # type: ignore[arg-type]
            char_count=char_count,
        )
        self._envelopes.append(env)
        log.debug(
            "whatsapp-envelope-watcher: cached envelope sender=%s "
            "chat_type=%s ts=%s",
            env.sender_jid, env.chat_type, env.ts.isoformat(),
        )

    @staticmethod
    def _parse_log_ts(obj: dict) -> datetime | None:
        """Extract a tz-aware UTC ts from the log object.

        OpenClaw writes ``time`` (top-level) AND ``_meta.date``. Both are
        ISO-8601 with offset; ``time`` is preferred (closer to the event)
        and is what the canonical line shape carries.
        """
        for key in ("time",):
            v = obj.get(key)
            if not isinstance(v, str):
                continue
            try:
                # Replace Z with explicit offset for older Python; 3.11+
                # parses Z natively but the string we see is "+00:00" form.
                ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return ts
        # Fallback: _meta.date
        meta = obj.get("_meta")
        if isinstance(meta, dict):
            date_v = meta.get("date")
            if isinstance(date_v, str):
                try:
                    ts = datetime.fromisoformat(date_v.replace("Z", "+00:00"))
                except ValueError:
                    return None
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                return ts
        return None

    # ------------------------------------------------------------------
    # File handling — mirrors OpenClawLogTailer's behavior
    # ------------------------------------------------------------------

    def _latest_log_path(self) -> Path | None:
        if not self._log_dir.exists():
            return None
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        candidate = self._log_dir / f"openclaw-{today}.log"
        if candidate.exists():
            return candidate
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
            log.warning(
                "whatsapp-envelope-watcher: cannot open %s: %s",
                path, exc,
            )
            return
        fh.seek(0, 2)
        self._fh = fh
        self._current_path = path
        log.info(
            "whatsapp-envelope-watcher: tailing %s from offset %d",
            path, fh.tell(),
        )

    def _close(self) -> None:
        fh = self._fh
        self._fh = None
        self._current_path = None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass


# Type alias for the lookup callable threaded into the parser. Defined
# here so the parser can import it without dragging the watcher's
# implementation into its module surface.
EnvelopeLookup = "Callable[[datetime, float], WhatsAppInboundEnvelope | None]"


__all__ = [
    "WhatsAppInboundEnvelope",
    "WhatsAppInboundEnvelopeWatcher",
]
