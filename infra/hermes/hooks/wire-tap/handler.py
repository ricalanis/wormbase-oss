"""Hermes wire-tap hook handler.

H1 spike — see docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md
§5 Phase 0 + §7 Risk 1 ("no external event-emit path is documented for
Hermes"). This handler is the smallest possible bridge from Hermes's
in-process hook system out to the channel-adapter, so we can measure
whether ``agent:start`` fires reliably for every inbound Slack message.

Contract (per gateway/hooks.py in NousResearch/hermes-agent v0.11.0):

    async def handle(event_type: str, context: dict) -> None | Any: ...

The registry tolerates both sync and async handlers and catches/logs
any exception so a broken hook never crashes the gateway. We make this
handler defensive on top of that: every IO step is try/except'd and
prints a single-line marker that the spike note can grep for.

POST shape (the channel-adapter's spike endpoint must accept this):

    {
      "received_at": "<iso8601 utc>",
      "event_type":  "agent:start",
      "tenant":      "<WORMBASE_HERMES_TENANT>",
      "context":     <verbatim hermes context dict>
    }

The endpoint URL is read from WORMBASE_HERMES_SPIKE_ENDPOINT in
~/.hermes/.env (rendered by entrypoint.sh from the container env).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


# Read once at import time — Hermes loads the hook module once per
# process, so this matches the gateway's lifetime. If the env var is
# missing, default to the spike sidecar's docker-compose service name
# (channel-adapter-hermes-spike, kept distinct from the production
# `channel-adapter` host which is owned by the OpenClaw consumer).
_ENDPOINT = os.environ.get(
    "WORMBASE_HERMES_SPIKE_ENDPOINT",
    "http://channel-adapter-hermes-spike:18790/hermes-spike",
)
_TENANT = os.environ.get("WORMBASE_HERMES_TENANT", "baseworm")
_TIMEOUT_S = float(os.environ.get("WORMBASE_HERMES_SPIKE_TIMEOUT_S", "2.0"))


def _log(msg: str) -> None:
    """Print a single-line marker with a stable prefix for grep gating."""
    print(f"[wormbase-wire-tap] {msg}", flush=True, file=sys.stderr)


async def handle(event_type: str, context: dict[str, Any]) -> None:
    """Forward the hook envelope to the channel-adapter spike endpoint.

    Async signature so Hermes's registry awaits us; the only IO inside
    is a synchronous urllib POST (we use stdlib to avoid pulling aiohttp
    into the hook surface — the spike endpoint accepts requests in
    under 2ms and we set a 2s timeout as a backstop).
    """
    payload = {
        "received_at": datetime.now(tz=timezone.utc).isoformat(),
        "event_type": event_type,
        "tenant": _TENANT,
        # context dicts from Hermes are JSON-serializable per the
        # emit() contract (gateway/run.py:4886 builds it from primitives).
        # Defensive `default=str` guards against any future enum/UUID.
        "context": context,
    }

    try:
        body = json.dumps(payload, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _log(f"json-encode-failed event={event_type} err={exc!r}")
        return

    req = urllib.request.Request(
        _ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            status = resp.status
        _log(f"posted event={event_type} status={status}")
    except urllib.error.URLError as exc:
        _log(f"post-failed event={event_type} endpoint={_ENDPOINT} err={exc!r}")
    except Exception as exc:  # noqa: BLE001 — defensive: hook MUST NOT raise
        _log(f"unexpected event={event_type} err={exc!r}")
