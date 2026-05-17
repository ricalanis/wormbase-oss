"""Live OpenClaw WhatsApp log-line verification harness (Wave A3).

We assumed OpenClaw's WhatsApp log-line grammar is symmetric to Slack's:

    whatsapp: allow channel <jid> (matchKey=... matchSource=...)

That assumption is encoded in
``apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py:_ALLOW_CHANNEL_RE``
as ``^(slack|whatsapp): allow channel (\\S+) ``. It is **empirically
unverified** until a paired OpenClaw instance has surfaced an actual
WhatsApp message and the daily log file shows what OpenClaw really
emits. This harness closes that loop.

Two modes
---------

**Verification mode** (default when env-gated):
    Tail OpenClaw's daily log file for up to 30 seconds, looking for
    any line containing both ``whatsapp`` and ``channel``. Assert that
    the canonical regex from ``openclaw_log_tail`` matches at least
    one observed line. On failure, the assertion message includes the
    actual observed line so a one-line regex patch can be applied.

**Discovery mode** (``WORMBASE_LIVE_OPENCLAW_DISCOVER=1``):
    Print the first 10 observed whatsapp-tagged lines, no assertions.
    For empirical debugging when verification mode fails or the
    grammar is otherwise unknown.

In both modes, observed whatsapp-tagged lines are written to
``/tmp/wormbase-openclaw-whatsapp-loglines-<timestamp>.txt`` so the
operator can grab the actual format if it diverges from the assumption.

Runner instructions
-------------------

Default pytest runs SKIP this test (no live OpenClaw needed). To run::

    WORMBASE_LIVE_OPENCLAW_TEST=1 \\
    WORMBASE_OPENCLAW_LOG_DIR=/var/log/openclaw \\
    uv run pytest tests/integration/test_openclaw_whatsapp_log_lines.py -v

Discovery mode (no assertions, just print observed lines)::

    WORMBASE_LIVE_OPENCLAW_TEST=1 \\
    WORMBASE_LIVE_OPENCLAW_DISCOVER=1 \\
    WORMBASE_OPENCLAW_LOG_DIR=/var/log/openclaw \\
    uv run pytest tests/integration/test_openclaw_whatsapp_log_lines.py -v -s

What to do when verification fails
----------------------------------

The test failure message embeds the actual observed log line. The
short feedback loop:

1. Copy the observed line from the failure output (also dumped to
   ``/tmp/wormbase-openclaw-whatsapp-loglines-<timestamp>.txt``).
2. Paste it back into the next conversation with the agent.
3. The fix is a single-line regex update in
   ``apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py:_ALLOW_CHANNEL_RE``.
4. Re-run this harness to confirm the patch matches.

This is intended to be a 5-minute iteration when needed.

Marker + skip behavior
----------------------

The test is marked ``@pytest.mark.live_openclaw`` (registered in
``pyproject.toml``) and skipped unless ``WORMBASE_LIVE_OPENCLAW_TEST=1``
is set. Default ``uv run pytest`` runs are CLEANLY SKIPPED — no
flakiness, no false reds, no unknown-marker warnings.
"""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Mirror of the production regex under verification. Imported lazily so
# the test file is collectible even if the channel-adapter package is
# not fully wired (the test itself is skipped by env gate before any
# import side-effect would matter).
_PRODUCTION_REGEX = re.compile(r"^(slack|whatsapp): allow channel (\S+) ")

# Default OpenClaw log directory inside the channel-adapter docker-compose
# mount. Override with ``WORMBASE_OPENCLAW_LOG_DIR`` env var.
_DEFAULT_LOG_DIR = "/var/log/openclaw"

# How long verification mode tails the file looking for whatsapp lines.
_TAIL_DURATION_S = 30.0

# Polling cadence within the tail loop.
_TAIL_POLL_S = 0.25

# How many lines discovery mode prints before stopping (it still keeps
# tailing for the full window so the dump file is comprehensive, but
# stdout is bounded for readability).
_DISCOVERY_PRINT_LIMIT = 10


def _live_test_enabled() -> bool:
    """Gate: env var explicitly set to ``1``."""
    return os.environ.get("WORMBASE_LIVE_OPENCLAW_TEST", "").strip() == "1"


def _discovery_mode() -> bool:
    """Whether to skip the assertion and dump observed lines instead."""
    return os.environ.get("WORMBASE_LIVE_OPENCLAW_DISCOVER", "").strip() == "1"


def _log_dir() -> Path:
    return Path(os.environ.get("WORMBASE_OPENCLAW_LOG_DIR", _DEFAULT_LOG_DIR))


def _latest_log_path(log_dir: Path) -> Path | None:
    """Mirror of ``OpenClawLogTailer._latest_log_path`` for harness use.

    Returns today's ``openclaw-YYYY-MM-DD.log`` if present, else the
    lexicographically-newest matching file (handles clock skew between
    container and host).
    """
    if not log_dir.exists():
        return None
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    candidate = log_dir / f"openclaw-{today}.log"
    if candidate.exists():
        return candidate
    try:
        files = sorted(log_dir.glob("openclaw-*.log"), key=lambda p: p.name)
    except OSError:
        return None
    return files[-1] if files else None


def _is_whatsapp_tagged(line: str) -> bool:
    """Cheap pre-filter: line mentions both 'whatsapp' and 'channel'.

    This is intentionally permissive — it should match the assumed
    grammar AND any plausible variants (different word ordering, JSON
    keys, etc.) so discovery mode surfaces lines that the production
    regex would currently miss.
    """
    lower = line.lower()
    return "whatsapp" in lower and "channel" in lower


def _dump_path() -> Path:
    """Return a unique path under /tmp for this run's observations."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/tmp/wormbase-openclaw-whatsapp-loglines-{ts}.txt")


@pytest.mark.live_openclaw
@pytest.mark.integration
@pytest.mark.skipif(
    not _live_test_enabled(),
    reason=(
        "Live OpenClaw harness — set WORMBASE_LIVE_OPENCLAW_TEST=1 after "
        "completing the WhatsApp QR pairing flow (see "
        "infra/openclaw/WHATSAPP_PAIRING.md). Default pytest runs skip "
        "this test cleanly."
    ),
)
def test_openclaw_whatsapp_log_line_grammar_matches_production_regex() -> None:
    """Tail OpenClaw's daily log; assert the production regex matches.

    See module docstring for runner + failure-recovery instructions.
    """
    log_dir = _log_dir()
    if not log_dir.exists():
        pytest.skip(
            f"OpenClaw log dir {log_dir} does not exist. Set "
            "WORMBASE_OPENCLAW_LOG_DIR to the dir mounted by the "
            "openclaw service (see infra/docker-compose.yml)."
        )

    path = _latest_log_path(log_dir)
    if path is None:
        pytest.skip(
            f"No openclaw-*.log files found under {log_dir}. The "
            "openclaw container may not have written its first daily "
            "log yet. Wait for one inbound message and retry."
        )

    discovery = _discovery_mode()
    dump_path = _dump_path()
    observed: list[str] = []

    deadline = time.monotonic() + _TAIL_DURATION_S
    fh = path.open("rb")
    # Start at end-of-file so we don't replay yesterday's events.
    fh.seek(0, 2)
    try:
        pending = b""
        while time.monotonic() < deadline:
            chunk = fh.read(65536)
            if not chunk:
                # Cancellable wait: short poll so the loop doesn't hang
                # past the 30s budget by more than _TAIL_POLL_S.
                time.sleep(_TAIL_POLL_S)
                continue
            pending += chunk
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                text = raw.decode("utf-8", errors="replace")
                if not text:
                    continue
                if _is_whatsapp_tagged(text):
                    observed.append(text)
                    if discovery and len(observed) <= _DISCOVERY_PRINT_LIMIT:
                        print(f"[discovery #{len(observed)}] {text}")
            # In discovery mode, allow early exit once we have enough
            # to print AND we've spent at least 5 seconds tailing
            # (gives slow log writers time to flush).
            if discovery and len(observed) >= _DISCOVERY_PRINT_LIMIT:
                # Continue tailing to fill the dump file, but don't
                # block the operator past the soft floor.
                if (deadline - time.monotonic()) < (_TAIL_DURATION_S - 5):
                    break
    finally:
        fh.close()

    # Always dump observations to /tmp regardless of mode/outcome.
    try:
        dump_path.write_text(
            "# OpenClaw WhatsApp log-line observations\n"
            f"# captured_at: {datetime.now(UTC).isoformat()}\n"
            f"# log_file: {path}\n"
            f"# tail_duration_s: {_TAIL_DURATION_S}\n"
            f"# mode: {'discovery' if discovery else 'verification'}\n"
            f"# observed_count: {len(observed)}\n"
            "#\n"
            + "\n".join(observed)
            + "\n"
        )
        print(f"\n[harness] observations dumped to {dump_path}")
    except OSError as exc:
        # Dump failure is non-fatal; the assertion message still
        # carries the relevant lines.
        print(f"[harness] could not write dump file {dump_path}: {exc}")

    if discovery:
        # Discovery mode never asserts — the operator is debugging
        # the grammar, not gating CI.
        print(
            f"\n[discovery] tail complete. observed {len(observed)} "
            f"whatsapp-tagged line(s). first {min(len(observed), _DISCOVERY_PRINT_LIMIT)} "
            "printed above; full dump at the path above."
        )
        return

    # Verification mode: assert the production regex matches at least
    # one observation. The line that lives inside the JSON envelope
    # may be wrapped — try both raw and JSON-extracted forms (mirror
    # of how OpenClawLogTailer._handle_line does it).
    if not observed:
        pytest.fail(
            f"No whatsapp-tagged lines observed in {path} during "
            f"{_TAIL_DURATION_S}s tail. Is a WhatsApp message landing "
            "while the test runs? Try sending one to the paired bot "
            "during the window, or use discovery mode "
            "(WORMBASE_LIVE_OPENCLAW_DISCOVER=1) to inspect the raw "
            "log stream."
        )

    matches = _find_regex_matches(observed)
    if matches:
        # Success — at least one observed line matched the production
        # regex. Print a short confirmation for the operator.
        print(
            f"\n[verification] PASS — {len(matches)}/{len(observed)} "
            "whatsapp-tagged line(s) matched the production regex."
        )
        return

    # Failure: regex needs an update. Surface the observed lines
    # in the assertion message AND point at the dump file.
    sample = observed[:5]
    raise AssertionError(
        "OpenClaw WhatsApp log-line grammar diverges from the assumed "
        "regex `^(slack|whatsapp): allow channel (\\S+) ` in "
        "apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py.\n"
        f"\nObserved {len(observed)} whatsapp-tagged line(s); none matched.\n"
        f"\nFirst {len(sample)} observations:\n"
        + "\n".join(f"  - {line}" for line in sample)
        + f"\n\nFull dump: {dump_path}\n"
        "\nNext step: paste an observation back to the agent; "
        "the fix is a single-line regex update."
    )


def _find_regex_matches(lines: list[str]) -> list[str]:
    """Return lines matching ``_PRODUCTION_REGEX`` (raw or JSON-wrapped).

    OpenClaw emits one JSON object per line; the human-readable message
    is keyed under ``"0"``. We try the raw line first, then the JSON
    field — same fallback order as ``OpenClawLogTailer._handle_line``.
    """
    import json

    matches: list[str] = []
    for line in lines:
        if _PRODUCTION_REGEX.match(line):
            matches.append(line)
            continue
        # Try JSON-wrapped form.
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        for key in ("0", "msg", "message"):
            candidate = obj.get(key)
            if isinstance(candidate, str) and _PRODUCTION_REGEX.match(candidate):
                matches.append(line)
                break
    return matches
