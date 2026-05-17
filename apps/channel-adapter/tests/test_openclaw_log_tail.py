"""Tests for OpenClawLogTailer.

Covers:
  * the tailer fires the callback once per matching ``<platform>: allow
    channel <id>`` line and ignores unrelated routing/inbound entries —
    parametrized across Slack channel ids and WhatsApp jids (DM and
    group), since :data:`_ALLOW_CHANNEL_RE` now captures both;
  * partial lines (no trailing newline) are buffered and only fire after
    the rest of the line lands;
  * non-JSON / garbled lines do not crash the tailer (best-effort);
  * the callback receives ``(platform, channel_id)`` and platform is
    propagated through unchanged for downstream dispatch.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wormbase_channel_adapter.openclaw_log_tail import OpenClawLogTailer


def _today_log(log_dir: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return log_dir / f"openclaw-{today}.log"


def _allow_line(
    channel_id: str = "C0B06MCSLQ1",
    *,
    platform: str = "slack",
) -> str:
    return (
        json.dumps(
            {
                "0": (
                    f"{platform}: allow channel {channel_id} "
                    "(matchKey=none matchSource=none)"
                ),
                "level": "info",
            }
        )
        + "\n"
    )


def _routing_line() -> str:
    return (
        json.dumps(
            {
                "0": "[routing] dispatch session=abcd to agent=main",
                "level": "debug",
            }
        )
        + "\n"
    )


def _slack_inbound_line() -> str:
    return (
        json.dumps(
            {
                "0": "slack inbound: text=hello channel=C0B06MCSLQ1",
                "level": "trace",
            }
        )
        + "\n"
    )


async def _drive_until(
    tailer: OpenClawLogTailer,
    *,
    predicate,
    timeout: float = 2.0,
) -> None:
    """Run the tailer until ``predicate()`` is true or timeout, then stop."""
    task = asyncio.create_task(tailer.run())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
    finally:
        tailer.stop()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (TimeoutError, Exception):  # noqa: BLE001
            task.cancel()


# Parametrize across Slack and WhatsApp ids so we cover both branches
# of the alternation in :data:`_ALLOW_CHANNEL_RE`. WhatsApp has two id
# shapes: DMs (``<phone>@s.whatsapp.net``) and groups (``<id>@g.us``).
# The ``\S+`` capture is permissive enough for both; the parametrization
# pins the contract explicitly.
_PLATFORM_CASES = [
    pytest.param("slack", "C0B06MCSLQ1", id="slack-channel"),
    pytest.param(
        "whatsapp",
        "5511999999999@s.whatsapp.net",
        id="whatsapp-dm",
    ),
    pytest.param(
        "whatsapp",
        "120363012345678901@g.us",
        id="whatsapp-group",
    ),
]


@pytest.mark.parametrize("platform,channel_id", _PLATFORM_CASES)
@pytest.mark.asyncio
async def test_callback_fires_for_matching_lines_and_skips_others(
    tmp_path: Path,
    platform: str,
    channel_id: str,
) -> None:
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    # Pre-create empty file so the tailer opens it (open-at-end).
    log_file.write_text("")

    seen: list[tuple[str, str]] = []

    async def on_event(p: str, cid: str) -> None:
        seen.append((p, cid))

    tailer = OpenClawLogTailer(log_dir, on_event, poll_interval_s=0.05)

    second_id = "C9XYZAAAAA" if platform == "slack" else "120363099999999999@g.us"

    async def append_after_open() -> None:
        # Wait briefly so the tailer opens at end-of-file BEFORE we
        # write — otherwise the open-at-end seek skips our writes.
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_routing_line())
            fh.write(_allow_line(channel_id, platform=platform))
            fh.write(_slack_inbound_line())  # noise — must not match
            fh.write(_allow_line(second_id, platform=platform))
            fh.flush()

    appender = asyncio.create_task(append_after_open())
    await _drive_until(tailer, predicate=lambda: len(seen) >= 2, timeout=3.0)
    await appender

    assert seen == [(platform, channel_id), (platform, second_id)]


@pytest.mark.asyncio
async def test_callback_dispatches_by_platform_when_lines_interleave(
    tmp_path: Path,
) -> None:
    """Slack and WhatsApp lines in the same log surface to the callback
    with the correct platform tag — the only state the dispatcher needs
    to route correctly."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    seen: list[tuple[str, str]] = []

    async def on_event(p: str, cid: str) -> None:
        seen.append((p, cid))

    tailer = OpenClawLogTailer(log_dir, on_event, poll_interval_s=0.05)

    async def append_mixed() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_allow_line("C0SLACKAA", platform="slack"))
            fh.write(_allow_line("5511999999999@s.whatsapp.net", platform="whatsapp"))
            fh.write(_allow_line("C0SLACKBB", platform="slack"))
            fh.write(_allow_line("120363012345678901@g.us", platform="whatsapp"))
            fh.flush()

    appender = asyncio.create_task(append_mixed())
    await _drive_until(tailer, predicate=lambda: len(seen) >= 4, timeout=3.0)
    await appender

    assert seen == [
        ("slack", "C0SLACKAA"),
        ("whatsapp", "5511999999999@s.whatsapp.net"),
        ("slack", "C0SLACKBB"),
        ("whatsapp", "120363012345678901@g.us"),
    ]


@pytest.mark.asyncio
async def test_partial_line_is_buffered_until_newline(tmp_path: Path) -> None:
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    seen: list[tuple[str, str]] = []

    async def on_event(p: str, cid: str) -> None:
        seen.append((p, cid))

    tailer = OpenClawLogTailer(log_dir, on_event, poll_interval_s=0.05)

    full = _allow_line("C0PARTIAL01")
    half = full[: len(full) // 2]
    rest = full[len(full) // 2 :]

    async def append_split() -> None:
        await asyncio.sleep(0.2)
        # First half — must NOT fire the callback.
        with log_file.open("a") as fh:
            fh.write(half)
            fh.flush()
        await asyncio.sleep(0.4)
        # Confirm: still no events because the line isn't terminated.
        assert seen == [], (
            f"callback fired on partial line: {seen!r}"
        )
        # Second half completes the newline.
        with log_file.open("a") as fh:
            fh.write(rest)
            fh.flush()

    appender = asyncio.create_task(append_split())
    await _drive_until(tailer, predicate=lambda: len(seen) >= 1, timeout=4.0)
    await appender

    assert seen == [("slack", "C0PARTIAL01")]


@pytest.mark.asyncio
async def test_garbled_json_does_not_crash_tailer(tmp_path: Path) -> None:
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    seen: list[tuple[str, str]] = []

    async def on_event(p: str, cid: str) -> None:
        seen.append((p, cid))

    tailer = OpenClawLogTailer(log_dir, on_event, poll_interval_s=0.05)

    async def append_garbage_then_real() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            # Truncated JSON ('{ "0":') — `json.loads` will raise
            # JSONDecodeError. The tailer's fallback treats the whole
            # line as a string and tries the regex on it, which won't
            # match. Either way: no crash, no callback.
            fh.write('{ "0": "this is not valid json,,, \n')
            # An entirely non-JSON line, terminated.
            fh.write("not json at all but ends with newline\n")
            # A real allow line afterward — must still be picked up.
            fh.write(_allow_line("C0AFTERGARB"))
            fh.flush()

    appender = asyncio.create_task(append_garbage_then_real())
    await _drive_until(tailer, predicate=lambda: len(seen) >= 1, timeout=3.0)
    await appender

    assert seen == [("slack", "C0AFTERGARB")]
