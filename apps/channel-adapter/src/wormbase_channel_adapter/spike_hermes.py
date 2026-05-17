"""Hermes H1 spike endpoint — ``hermes-spike`` subcommand.

Per ``docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md``
§5 Phase 0 (the GO/NO-GO gate). This module is intentionally *isolated*
from the production ``run`` command:

* It does not touch the ledger.
* It does not import ``service.py`` / ``tailer.py`` / ``state.py``.
* It does not subscribe to the OpenClaw seam in any way.

Its sole job is to receive POSTs from the Hermes wire-tap hook
(``infra/hermes/hooks/wire-tap/handler.py``) and append each envelope as
one line of JSONL to ``/var/log/wormbase/hermes-spike.jsonl``. The note
at ``docs/notes/2026-04-27-hermes-h1-spike.md`` then diffs that file
against the OpenClaw global log to compute the spike's GO/NO-GO call.

When H2 lands (`HermesEventConsumer` in
``apps/channel-adapter/src/wormbase_channel_adapter/hermes_event_consumer.py``),
this module is deleted alongside the ``hermes-spike`` CLI subcommand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import web

log = logging.getLogger(__name__)


# Default JSONL sink — mounted volume in docker-compose so the file
# survives container restarts and is reachable from the host for the
# spike note's diff scripts.
DEFAULT_SINK = "/var/log/wormbase/hermes-spike.jsonl"

# Default bind. The container exposes 18790 (distinct from the production
# OpenClaw seam ports). Host-mode binding is intentional for spike-only
# convenience; H2 will move this to a dedicated docker-compose service.
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 — container-private port, behind compose network
DEFAULT_PORT = 18790


class SpikeRecorder:
    """Append-only JSONL recorder used by the ``/hermes-spike`` route.

    A single instance owns the sink file handle for the process lifetime.
    Thread/coroutine safety is provided by an asyncio.Lock around writes —
    the route handler is async, but multiple concurrent requests can race
    the write side and JSONL atomicity matters for the spike diff.
    """

    def __init__(self, sink_path: str | Path) -> None:
        self._path = Path(sink_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append-binary mode so we control the line terminator
        # and so re-opening across container restarts preserves history.
        self._fh = self._path.open("ab")
        self._lock = asyncio.Lock()
        self._count = 0

    async def record(self, envelope: dict[str, object]) -> int:
        """Persist one envelope; return the post-write count."""
        # Stamp arrival on the channel-adapter side too so we can compute
        # hook-fire → spike-receive latency from the JSONL alone.
        envelope = {
            **envelope,
            "spike_received_at": datetime.now(tz=UTC).isoformat(),
        }
        line = (
            json.dumps(envelope, default=str, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        async with self._lock:
            self._fh.write(line)
            self._fh.flush()
            self._count += 1
            return self._count

    @property
    def count(self) -> int:
        return self._count

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            log.exception("spike_hermes: error closing sink")


def make_app(recorder: SpikeRecorder) -> web.Application:
    """Build the aiohttp app. Two routes only.

    * ``POST /hermes-spike``  — record an envelope.
    * ``GET  /healthz``        — liveness probe used by the spike harness.
    """
    app = web.Application()

    async def spike_handler(request: web.Request) -> web.Response:
        try:
            envelope = await request.json()
        except json.JSONDecodeError as exc:
            log.warning("spike_hermes: bad JSON body: %s", exc)
            # Be permissive — return 400 but include enough info for the
            # hook to log a single-line marker. We don't want to panic
            # the gateway over a body shape regression.
            return web.json_response(
                {"ok": False, "error": "bad-json", "detail": str(exc)},
                status=400,
            )

        if not isinstance(envelope, dict):
            return web.json_response(
                {"ok": False, "error": "envelope-must-be-object"},
                status=400,
            )

        seq = await recorder.record(envelope)
        return web.json_response({"ok": True, "seq": seq}, status=200)

    async def healthz(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "count": recorder.count,
                "sink": str(recorder.path),
            },
        )

    app.router.add_post("/hermes-spike", spike_handler)
    app.router.add_get("/healthz", healthz)
    return app


@asynccontextmanager
async def _run_app(
    app: web.Application, host: str, port: int,
) -> AsyncIterator[None]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("spike_hermes: listening on http://%s:%d", host, port)
    try:
        yield
    finally:
        await runner.cleanup()


async def run_spike(
    *,
    sink_path: str = DEFAULT_SINK,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Run the spike endpoint until SIGINT/SIGTERM."""
    recorder = SpikeRecorder(sink_path)
    app = make_app(recorder)

    stop_event = asyncio.Event()

    def _handle_sig(signame: str) -> None:
        log.info("spike_hermes: received %s — shutting down", signame)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_sig, sig.name)
        except NotImplementedError:
            # add_signal_handler is unavailable on Windows; the spike is
            # Linux-container-only so this branch is mostly defensive.
            pass

    try:
        async with _run_app(app, host, port):
            await stop_event.wait()
    finally:
        recorder.close()


def cli_entry(
    *,
    sink_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Synchronous wrapper for the click subcommand."""
    sink_path = sink_path or os.environ.get(
        "WORMBASE_HERMES_SPIKE_SINK", DEFAULT_SINK,
    )
    host = host or os.environ.get(
        "WORMBASE_HERMES_SPIKE_HOST", DEFAULT_HOST,
    )
    port = port or int(
        os.environ.get("WORMBASE_HERMES_SPIKE_PORT", DEFAULT_PORT),
    )
    asyncio.run(run_spike(sink_path=sink_path, host=host, port=port))
