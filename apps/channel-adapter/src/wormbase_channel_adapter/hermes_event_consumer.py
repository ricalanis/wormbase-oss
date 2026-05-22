"""Hermes-side inbound consumer — the Phase 1 replacement for OpenClaw's log tailer.

Per `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md` §6
Phase 1 + Option A (default): the NousResearch Hermes Agent gateway runs
the `wire-tap` hook (under ``~/.hermes/hooks/wire-tap/``) which POSTs
every inbound event envelope to a channel-adapter HTTP endpoint. This
module is that endpoint.

Why HTTP and not a tail-able JSONL like OpenClaw's daily log:

* Hermes does NOT document an external event-emit path (spec §2
  "showstopper"). The hook system is in-process Python. We design
  around it via shell-hook POST — option A in the spec — because that
  preserves the existing "gateway as separate process" architectural
  commitment without coupling the channel-adapter to Hermes's internals.
* HTTP has known delivery semantics (request-response with status code)
  and bounded latency that's easier to reason about than file-tail
  polling. The hook gets back-pressure via HTTP timeouts; the consumer
  gets explicit error returns instead of silently dropping malformed
  log lines.
* No process supervision dependency — the consumer is owned by the
  channel-adapter container's existing asyncio loop. No extra sidecar.

Wire shape (from `infra/hermes/hooks/wire-tap/handler.py`, this repo):

    {
      "received_at": "2026-05-21T18:00:00.000+00:00",
      "event_type":  "agent:start" | "session:start" | "session:end",
      "tenant":      "baseworm",
      "context": {
        "platform":   "slack" | "whatsapp" | ...,
        "user_id":    "U0AV4C8TTEZ",
        "session_id": "5d8e...",
        "message":    "first 500 chars of the body",
        // Optional richer fields if the hook is extended:
        "channel_id":   "C0B06MCSLQ1",
        "message_ts":   "1779388595.682",
      }
    }

Only ``agent:start`` produces a ledger write today; ``session:start`` /
``session:end`` are dropped as no-ops (logged at debug). When the
optional richer fields are absent we synthesize a stable message_id
from ``(session_id, received_at)`` so dedup-on-replay still works; the
event still flows downstream but ``channel_id`` falls back to a
``hermes-session:<session_id>`` sentinel that the dashboard renders as
"unknown channel" rather than crashing.

The consumer integrates with the existing :class:`LedgerWriter` —
events are pushed through ``writer.emit()`` just like the WhatsApp
envelope-watcher's direct-emission path (added 2026-05-21). The
writer's per-process (channel_id, message_id) dedup absorbs retries
and replays from any source.

Failure mode: bounded-best-effort. Malformed payloads return HTTP 400
with a JSON error body and never crash the loop. The consumer logs
unexpected exceptions but always returns a response so Hermes's hook
doesn't see a connection error and back off.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from wormbase_channel_adapter.parser import ChatReceivedEvent
    from wormbase_channel_adapter.writer import LedgerWriter

log = logging.getLogger(__name__)


# Default HTTP port for the consumer's spike endpoint. Matches the
# default WORMBASE_HERMES_SPIKE_ENDPOINT in the wire-tap hook
# (`http://channel-adapter:18790/hermes-spike`).
DEFAULT_PORT = 18790
DEFAULT_PATH = "/hermes-spike"

# Hook events we translate into ledger writes. Others are recorded at
# debug level only — they're useful for connection-health observability
# but don't produce chat_received.
_AGENT_INBOUND_EVENT = "agent:start"
_SESSION_EVENTS = frozenset({"session:start", "session:end"})


class HermesEventConsumer:
    """HTTP endpoint that turns Hermes wire-tap POSTs into ledger writes.

    Lifecycle:

    - :meth:`run` starts the aiohttp server and blocks until :meth:`stop`
      is called. Designed to live alongside :class:`OpenClawLogTailer` in
      :mod:`wormbase_channel_adapter.service` and be selected by the
      ``WORMBASE_GATEWAY=hermes`` env var (Phase 2).
    - Concurrent inbound requests are processed via the aiohttp default
      ThreadPoolExecutor; each request's translation + writer.emit is
      awaited inline so back-pressure flows back to the hook caller.

    Construction takes a :class:`LedgerWriter` instance and (optionally)
    a host / port. The writer is responsible for ledger writes + dedup
    — the consumer is just the inbound transport.
    """

    def __init__(
        self,
        writer: "LedgerWriter",
        *,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        path: str = DEFAULT_PATH,
    ) -> None:
        self._writer = writer
        self._host = host
        self._port = port
        self._path = path
        self._runner: web.AppRunner | None = None
        self._site: web.BaseSite | None = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        app = web.Application()
        app.router.add_post(self._path, self._handle_post)
        app.router.add_get("/healthz", self._handle_healthz)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        log.info(
            "hermes-event-consumer: listening on http://%s:%d%s",
            self._host, self._port, self._path,
        )
        try:
            await self._stop_event.wait()
        finally:
            await self._cleanup()

    def stop(self) -> None:
        self._stop_event.set()

    async def _cleanup(self) -> None:
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception:  # noqa: BLE001
                log.exception("hermes-event-consumer: site stop failed")
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:  # noqa: BLE001
                log.exception("hermes-event-consumer: runner cleanup failed")
        self._site = None
        self._runner = None

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    @staticmethod
    async def _handle_healthz(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "hermes-event-consumer"})

    async def _handle_post(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except (ValueError, web.HTTPException) as exc:
            log.warning("hermes-event-consumer: bad JSON: %s", exc)
            return web.json_response(
                {"ok": False, "error": "invalid_json"}, status=400,
            )
        if not isinstance(payload, dict):
            return web.json_response(
                {"ok": False, "error": "payload_must_be_object"}, status=400,
            )
        event_type = payload.get("event_type")
        if not isinstance(event_type, str):
            return web.json_response(
                {"ok": False, "error": "missing_event_type"}, status=400,
            )
        if event_type in _SESSION_EVENTS:
            # session:start / session:end are useful as observability
            # signals but don't produce chat_received. Record at debug
            # so an operator looking at the channel-adapter log can see
            # the wire-tap is firing, but skip the ledger path.
            log.debug(
                "hermes-event-consumer: %s (no ledger write)", event_type,
            )
            return web.json_response({"ok": True, "skipped": event_type})
        if event_type != _AGENT_INBOUND_EVENT:
            log.debug(
                "hermes-event-consumer: unknown event_type %r — ignored",
                event_type,
            )
            return web.json_response({"ok": True, "skipped": event_type})
        try:
            event = self._translate_agent_start(payload)
        except _TranslateError as exc:
            log.warning(
                "hermes-event-consumer: translate failed: %s (payload=%r)",
                exc, payload,
            )
            return web.json_response(
                {"ok": False, "error": str(exc)}, status=400,
            )
        if event is None:
            return web.json_response({"ok": True, "skipped": "empty_text"})
        try:
            await self._writer.emit(event)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "hermes-event-consumer: writer.emit failed (event=%s)",
                event.message_id,
            )
            return web.json_response(
                {"ok": False, "error": "writer_failed", "detail": repr(exc)},
                status=500,
            )
        return web.json_response(
            {"ok": True, "message_id": event.message_id},
        )

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def _translate_agent_start(
        self, payload: dict[str, Any],
    ) -> "ChatReceivedEvent | None":
        """Translate the wire-tap envelope into a ChatReceivedEvent.

        Returns None when the payload is well-formed but doesn't carry
        a non-empty text body — we treat that as a no-op rather than
        an error (e.g., a reaction-only event that Hermes routes
        through agent:start with empty message).
        """
        # Lazy import to dodge the parser ↔ consumer cycle at module-load.
        from wormbase_channel_adapter.parser import ChatReceivedEvent

        context = payload.get("context")
        if not isinstance(context, dict):
            raise _TranslateError("missing_context")
        user_id = context.get("user_id")
        session_id = context.get("session_id")
        message = context.get("message")
        platform = context.get("platform", "unknown")
        if not isinstance(user_id, str) or not user_id:
            raise _TranslateError("missing_user_id")
        if not isinstance(session_id, str) or not session_id:
            raise _TranslateError("missing_session_id")
        if not isinstance(message, str):
            raise _TranslateError("missing_message")
        cleaned_text = message.strip()
        if not cleaned_text:
            return None
        ts = self._parse_received_at(payload)
        # Optional richer fields if the hook is extended to capture them;
        # fall back to sentinels otherwise (so the event still flows
        # downstream rather than failing here).
        channel_id_raw = context.get("channel_id")
        if isinstance(channel_id_raw, str) and channel_id_raw:
            channel_id = channel_id_raw
        else:
            channel_id = f"hermes-session:{session_id}"
        message_ts_raw = context.get("message_ts")
        if isinstance(message_ts_raw, str) and message_ts_raw:
            message_id = message_ts_raw
        else:
            # Deterministic synthetic id so re-deliveries of the same
            # (session, ts) collapse via the writer's dedup. SHA256 of
            # canonical fields; first 16 hex chars is plenty of entropy
            # for per-session uniqueness.
            digest = hashlib.sha256(
                f"{session_id}|{ts.isoformat()}|{cleaned_text}".encode("utf-8"),
            ).hexdigest()[:16]
            message_id = f"hermes:{platform}:{digest}"
        return ChatReceivedEvent(
            kind="chat_received",
            session_id=f"hermes:{session_id}",
            event_id=message_id,
            ts=ts,
            channel_id=channel_id,
            message_id=message_id,
            sender_id=user_id,
            sender_label=user_id,
            text=cleaned_text,
            conversation_label="",
            delivery_mode="push",
            platform_ts=ts,
            history_sync_id=None,
            mentioned_jids=None,
        )

    @staticmethod
    def _parse_received_at(payload: dict[str, Any]) -> datetime:
        """Pull ISO-8601 ``received_at`` and return tz-aware UTC.

        Defensive fallback to ``now()`` if the field is missing or
        malformed — losing the exact server-side ts of the event is
        recoverable; refusing the entire event isn't.
        """
        raw = payload.get("received_at")
        if isinstance(raw, str):
            try:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                return ts
            except ValueError:
                log.warning(
                    "hermes-event-consumer: bad received_at %r — using now()",
                    raw,
                )
        return datetime.now(tz=UTC)


class _TranslateError(ValueError):
    """Raised when a payload is well-formed JSON but missing required fields."""


__all__ = [
    "DEFAULT_PATH",
    "DEFAULT_PORT",
    "HermesEventConsumer",
]
