#!/usr/bin/env python3
"""OpenClaw watchdog (W7.A2 — optional).

Tails `docker compose logs openclaw` in follow mode, looks for a small
catalogue of stuck-state patterns, and emits an alert (stderr) +
optionally triggers `make openclaw-restart` after N consecutive matches.

Gated on ``WORMBASE_OPENCLAW_WATCHDOG=1`` — does NOT auto-start with
`make up`. Intended to be invoked manually during long demo runs:

    WORMBASE_OPENCLAW_WATCHDOG=1 python3 scripts/openclaw-watchdog.py

The Docker engine's healthcheck (configured in
``infra/docker-compose.yml``) is the canonical liveness signal. This
watchdog is a complementary layer that catches *log-pattern*
degradations (Slack reconnect storms, heap-OOM warnings, repeated
"CIAO PROBING CANCELLED" cycles) that don't crash the process but
indicate it is wedging.

Stuck-state patterns (extend as we learn):
    - "CIAO PROBING CANCELLED"  (mDNS bonjour wedge)
    - "Slack: socket disconnected"  (followed by no reconnect within 30s)
    - "ECONNREFUSED" * N   (ollama/upstream unreachable)
    - "FATAL"  (anything self-tagged FATAL by openclaw)

Behavior:
    - Default: emit alerts to stderr, do NOT restart.
    - Set ``WORMBASE_OPENCLAW_WATCHDOG_AUTORESTART=1`` to additionally
      invoke `make openclaw-restart` after N (default 3) hits within a
      window (default 60s). Restart attempts are themselves capped to
      avoid loops.

Read by humans, not by tests. Belongs alongside scripts/doctor.sh as
an operator tool.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

STUCK_PATTERNS = [
    re.compile(r"CIAO PROBING CANCELLED"),
    re.compile(r"socket disconnected"),
    re.compile(r"ECONNREFUSED"),
    re.compile(r"FATAL"),
    # OpenClaw's "ollama: stream timeout" repeated for the same agent
    # generally indicates a wedged upstream and benefits from a bounce.
    re.compile(r"ollama: stream timeout"),
]


def gated() -> bool:
    return os.environ.get("WORMBASE_OPENCLAW_WATCHDOG", "").strip() == "1"


def autorestart() -> bool:
    return (
        os.environ.get("WORMBASE_OPENCLAW_WATCHDOG_AUTORESTART", "").strip() == "1"
    )


def alert(msg: str) -> None:
    sys.stderr.write(f"[openclaw-watchdog] {msg}\n")
    sys.stderr.flush()


def stream_logs():
    """Yield log lines from `docker compose logs -f openclaw`."""
    cmd = (
        "docker compose --project-directory . "
        f"-f {REPO_ROOT / 'infra' / 'docker-compose.yml'} "
        "logs -f --tail=0 openclaw"
    )
    proc = subprocess.Popen(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(REPO_ROOT),
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.terminate()


def run() -> int:
    if not gated():
        alert(
            "WORMBASE_OPENCLAW_WATCHDOG not set — refusing to start. "
            "Re-run with WORMBASE_OPENCLAW_WATCHDOG=1 to opt in."
        )
        return 2

    alert("starting; tailing openclaw logs for stuck-state patterns")
    if autorestart():
        alert(
            "auto-restart ENABLED via WORMBASE_OPENCLAW_WATCHDOG_AUTORESTART=1; "
            "will run `make openclaw-restart` on threshold breach"
        )

    threshold = int(os.environ.get("WORMBASE_OPENCLAW_WATCHDOG_THRESHOLD", "3"))
    window_s = int(os.environ.get("WORMBASE_OPENCLAW_WATCHDOG_WINDOW", "60"))
    restart_cooldown_s = int(
        os.environ.get("WORMBASE_OPENCLAW_WATCHDOG_COOLDOWN", "300")
    )

    hits: deque[float] = deque(maxlen=threshold * 4)
    last_restart: float = 0.0

    for line in stream_logs():
        for pattern in STUCK_PATTERNS:
            if pattern.search(line):
                now = time.monotonic()
                hits.append(now)
                # Trim hits outside the rolling window.
                while hits and (now - hits[0]) > window_s:
                    hits.popleft()
                alert(f"pattern hit ({len(hits)}/{threshold}): {line[:120]}")
                if len(hits) >= threshold:
                    if not autorestart():
                        alert(
                            f"threshold reached ({len(hits)} hits in {window_s}s) "
                            f"— operator action required: `make openclaw-restart`"
                        )
                        hits.clear()
                    elif (now - last_restart) >= restart_cooldown_s:
                        alert(
                            f"threshold reached + cooldown OK; running "
                            f"`make openclaw-restart` (cooldown {restart_cooldown_s}s)"
                        )
                        result = subprocess.run(
                            ["make", "openclaw-restart"],
                            cwd=str(REPO_ROOT),
                            capture_output=True,
                            text=True,
                            timeout=180,
                        )
                        last_restart = now
                        hits.clear()
                        alert(
                            f"openclaw-restart exit={result.returncode} "
                            f"(see .openclaw-pre-restart.log for forensics)"
                        )
                    else:
                        alert(
                            f"threshold reached but cooldown active "
                            f"({int(now - last_restart)}s elapsed of "
                            f"{restart_cooldown_s}s) — skipping auto-restart"
                        )
                break  # only count one pattern per line
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        alert("interrupted; exiting")
        sys.exit(130)
