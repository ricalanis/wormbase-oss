"""Tests for :class:`WhatsAppInboundEnvelopeWatcher`.

Covers:

* the watcher caches envelopes for lines whose ``"0"`` carries the
  ``gateway/channels/whatsapp/inbound`` subsystem AND whose ``"1"`` /
  ``message`` matches the inbound envelope grammar;
* lines from other subsystems (Slack admit, gateway/reload, plugins)
  are ignored;
* the cache is bounded — past the cap, oldest envelopes are evicted;
* ``find_recent_envelope(target_ts)`` returns the most-recent envelope
  inside the window AND ``None`` when nothing matches; window symmetry
  is honored;
* sender_jid / bot_jid are reconstructed correctly from the
  ``+<E.164>`` log prose.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wormbase_channel_adapter.whatsapp_envelope_watcher import (
    WhatsAppInboundEnvelope,
    WhatsAppInboundEnvelopeWatcher,
)


def _today_log(log_dir: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return log_dir / f"openclaw-{today}.log"


def _envelope_line(
    *,
    sender_phone: str = "5218117649489",
    bot_phone: str = "5218114822051",
    chat_type: str = "direct",
    char_count: int | None = 62,
    ts_iso: str | None = None,
) -> str:
    """Build one canonical inbound-envelope log line."""
    if ts_iso is None:
        ts_iso = datetime.now(UTC).isoformat(timespec="milliseconds")
    char_part = f", {char_count} chars" if char_count is not None else ""
    msg = (
        f"Inbound message +{sender_phone} -> +{bot_phone} "
        f"({chat_type}{char_part})"
    )
    return (
        json.dumps(
            {
                "0": '{"subsystem":"gateway/channels/whatsapp/inbound"}',
                "1": msg,
                "_meta": {"date": ts_iso},
                "time": ts_iso,
                "message": msg,
            }
        )
        + "\n"
    )


def _slack_admit_line(channel_id: str = "C0B06MCSLQ1") -> str:
    """A Slack admit line — must NOT be cached as a WhatsApp envelope."""
    return (
        json.dumps(
            {
                "0": (
                    f"slack: allow channel {channel_id} "
                    "(matchKey=none matchSource=none)"
                ),
                "level": "info",
            }
        )
        + "\n"
    )


def _whatsapp_listening_line() -> str:
    """A whatsapp gateway-status line; subsystem matches the prefix but
    the body does NOT match the inbound regex. Must NOT be cached."""
    return (
        json.dumps(
            {
                "0": '{"subsystem":"gateway/channels/whatsapp"}',
                "1": "Listening for personal WhatsApp inbound messages.",
                "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "message": "Listening for personal WhatsApp inbound messages.",
            }
        )
        + "\n"
    )


async def _drive_until(
    watcher: WhatsAppInboundEnvelopeWatcher,
    *,
    predicate,
    timeout: float = 2.0,
) -> None:
    task = asyncio.create_task(watcher.run())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
    finally:
        watcher.stop()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (TimeoutError, Exception):  # noqa: BLE001
            task.cancel()


# ---------------------------------------------------------------------------
# Cache population
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_envelope_lines_cache(tmp_path: Path) -> None:
    """Canonical inbound envelope is cached with reconstructed jid."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)

    async def append() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_envelope_line())
            fh.flush()

    appender = asyncio.create_task(append())
    await _drive_until(
        watcher, predicate=lambda: len(watcher.envelopes) >= 1, timeout=3.0,
    )
    await appender

    assert len(watcher.envelopes) == 1
    env = watcher.envelopes[0]
    assert isinstance(env, WhatsAppInboundEnvelope)
    assert env.sender_jid == "5218117649489@s.whatsapp.net"
    assert env.bot_jid == "5218114822051@s.whatsapp.net"
    assert env.chat_type == "direct"
    assert env.char_count == 62


@pytest.mark.asyncio
async def test_non_inbound_lines_are_not_cached(tmp_path: Path) -> None:
    """Slack admit + whatsapp gateway-status + non-matching prose are dropped."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)

    async def append() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_slack_admit_line())
            fh.write(_whatsapp_listening_line())
            fh.write(
                json.dumps(
                    {
                        "0": '{"subsystem":"gateway/reload"}',
                        "1": "config change detected",
                        "time": datetime.now(UTC).isoformat(),
                    }
                )
                + "\n"
            )
            # And one real envelope, so we have a positive predicate.
            fh.write(_envelope_line(sender_phone="111111111"))
            fh.flush()

    appender = asyncio.create_task(append())
    await _drive_until(
        watcher, predicate=lambda: len(watcher.envelopes) >= 1, timeout=3.0,
    )
    await appender

    # Only the real envelope was cached.
    assert len(watcher.envelopes) == 1
    assert watcher.envelopes[0].sender_jid == "111111111@s.whatsapp.net"


@pytest.mark.asyncio
async def test_group_chat_envelope_is_cached(tmp_path: Path) -> None:
    """Group inbound envelopes are cached (forward-compat) but chat_type is preserved."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)

    async def append() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_envelope_line(chat_type="group", char_count=12))
            fh.flush()

    appender = asyncio.create_task(append())
    await _drive_until(
        watcher, predicate=lambda: len(watcher.envelopes) >= 1, timeout=3.0,
    )
    await appender

    assert watcher.envelopes[0].chat_type == "group"


@pytest.mark.asyncio
async def test_envelope_without_char_count_is_cached(tmp_path: Path) -> None:
    """The ``, N chars`` suffix is optional in the regex."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    watcher = WhatsAppInboundEnvelopeWatcher(log_dir, poll_interval_s=0.05)

    async def append() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            fh.write(_envelope_line(char_count=None))
            fh.flush()

    appender = asyncio.create_task(append())
    await _drive_until(
        watcher, predicate=lambda: len(watcher.envelopes) >= 1, timeout=3.0,
    )
    await appender

    assert watcher.envelopes[0].char_count is None


# ---------------------------------------------------------------------------
# Bounded cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_evicts_oldest_at_cap(tmp_path: Path) -> None:
    """Past the cache cap, oldest envelopes are evicted (deque behavior)."""
    log_dir = tmp_path / "openclaw"
    log_dir.mkdir()
    log_file = _today_log(log_dir)
    log_file.write_text("")

    cap = 3
    watcher = WhatsAppInboundEnvelopeWatcher(
        log_dir, poll_interval_s=0.05, cache_size=cap,
    )

    async def append() -> None:
        await asyncio.sleep(0.2)
        with log_file.open("a") as fh:
            for i in range(cap + 2):  # 5 envelopes total with cap=3
                fh.write(_envelope_line(sender_phone=f"55{i:09d}"))
            fh.flush()

    appender = asyncio.create_task(append())
    await _drive_until(
        watcher,
        predicate=lambda: len(watcher.envelopes) >= cap,
        timeout=3.0,
    )
    # Give the watcher a beat to also drain any extras and overflow.
    await asyncio.sleep(0.3)
    await appender
    watcher.stop()

    # At cap; first two were evicted.
    envs = watcher.envelopes
    assert len(envs) <= cap
    sender_phones = [e.sender_jid.split("@")[0] for e in envs]
    # Newest entries kept; entry "55000000000" should NOT be present.
    assert "55000000000" not in sender_phones
    assert "55000000004" in sender_phones


# ---------------------------------------------------------------------------
# Lookup window
# ---------------------------------------------------------------------------


def _push(
    watcher: WhatsAppInboundEnvelopeWatcher,
    env: WhatsAppInboundEnvelope,
) -> None:
    """Test hook: append directly to the deque without going through I/O."""
    watcher._envelopes.append(env)


def test_find_recent_envelope_returns_match_within_window(tmp_path: Path) -> None:
    watcher = WhatsAppInboundEnvelopeWatcher(tmp_path, poll_interval_s=0.05)

    base = datetime(2026, 5, 7, 4, 10, 49, tzinfo=UTC)
    env = WhatsAppInboundEnvelope(
        ts=base,
        sender_jid="5218117649489@s.whatsapp.net",
        bot_jid="5218114822051@s.whatsapp.net",
        chat_type="direct",
        char_count=62,
    )
    _push(watcher, env)

    # Frame ts arrives 1s after envelope; within 30s window.
    target = base + timedelta(seconds=1)
    hit = watcher.find_recent_envelope(target, window_s=30.0)
    assert hit is env


def test_find_recent_envelope_returns_none_outside_window(tmp_path: Path) -> None:
    watcher = WhatsAppInboundEnvelopeWatcher(tmp_path, poll_interval_s=0.05)
    base = datetime(2026, 5, 7, 4, 10, 49, tzinfo=UTC)
    env = WhatsAppInboundEnvelope(
        ts=base,
        sender_jid="5218117649489@s.whatsapp.net",
        bot_jid="5218114822051@s.whatsapp.net",
        chat_type="direct",
        char_count=62,
    )
    _push(watcher, env)

    target = base + timedelta(seconds=120)  # well past 30s
    assert watcher.find_recent_envelope(target, window_s=30.0) is None


def test_find_recent_envelope_returns_most_recent(tmp_path: Path) -> None:
    """Multiple envelopes within the window — the latest one wins."""
    watcher = WhatsAppInboundEnvelopeWatcher(tmp_path, poll_interval_s=0.05)
    base = datetime(2026, 5, 7, 4, 10, 49, tzinfo=UTC)
    # Two distinct senders, both within 30s of target.
    older = WhatsAppInboundEnvelope(
        ts=base,
        sender_jid="111@s.whatsapp.net",
        bot_jid="999@s.whatsapp.net",
        chat_type="direct",
        char_count=10,
    )
    newer = WhatsAppInboundEnvelope(
        ts=base + timedelta(seconds=5),
        sender_jid="222@s.whatsapp.net",
        bot_jid="999@s.whatsapp.net",
        chat_type="direct",
        char_count=15,
    )
    _push(watcher, older)
    _push(watcher, newer)

    target = base + timedelta(seconds=6)
    hit = watcher.find_recent_envelope(target, window_s=30.0)
    assert hit is newer


def test_find_recent_envelope_empty_cache(tmp_path: Path) -> None:
    watcher = WhatsAppInboundEnvelopeWatcher(tmp_path, poll_interval_s=0.05)
    target = datetime.now(UTC)
    assert watcher.find_recent_envelope(target) is None


def test_find_recent_envelope_handles_naive_ts(tmp_path: Path) -> None:
    """Naive ts gets assumed-UTC; never raises."""
    watcher = WhatsAppInboundEnvelopeWatcher(tmp_path, poll_interval_s=0.05)
    base = datetime(2026, 5, 7, 4, 10, 49, tzinfo=UTC)
    env = WhatsAppInboundEnvelope(
        ts=base,
        sender_jid="111@s.whatsapp.net",
        bot_jid="999@s.whatsapp.net",
        chat_type="direct",
        char_count=10,
    )
    _push(watcher, env)
    naive = base.replace(tzinfo=None)
    hit = watcher.find_recent_envelope(naive, window_s=30.0)
    assert hit is env
