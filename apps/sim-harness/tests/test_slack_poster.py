"""Tests for SlackPoster — verify chat.postMessage + files_upload_v2 calls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wormbase_sim_harness.personas import Persona
from wormbase_sim_harness.slack_poster import SlackPoster


def _persona() -> Persona:
    return Persona(
        id="alice",
        display_name="Alice Chen",
        icon_emoji=":woman_office_worker:",
        role="Marketing",
        voice_hint="friendly",
    )


def _poster_with_mock() -> tuple[SlackPoster, AsyncMock]:
    fake = AsyncMock()
    poster = SlackPoster("xoxb-test", client=fake)
    return poster, fake


def _resp(data: dict) -> SimpleNamespace:
    return SimpleNamespace(data=data)


@pytest.mark.asyncio
async def test_post_as_includes_username_and_icon() -> None:
    poster, fake = _poster_with_mock()
    fake.chat_postMessage = AsyncMock(return_value=_resp({"ok": True, "ts": "1.0"}))
    out = await poster.post_as(_persona(), "#general", "hello world")
    fake.chat_postMessage.assert_awaited_once_with(
        channel="#general",
        text="hello world",
        username="Alice Chen",
        icon_emoji=":woman_office_worker:",
    )
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_post_as_logs_on_not_ok(caplog: pytest.LogCaptureFixture) -> None:
    poster, fake = _poster_with_mock()
    fake.chat_postMessage = AsyncMock(
        return_value=_resp({"ok": False, "error": "channel_not_found"})
    )
    caplog.set_level("WARNING", logger="wormbase_sim_harness.slack_poster")
    await poster.post_as(_persona(), "#bad", "hi")
    assert any("not-ok" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_upload_as_calls_files_upload_v2(tmp_path: Path) -> None:
    fpath = tmp_path / "data.csv"
    fpath.write_text("a,b\n1,2\n", encoding="utf-8")

    poster, fake = _poster_with_mock()
    fake.files_upload_v2 = AsyncMock(return_value=_resp({"ok": True}))

    # Pass a literal channel id (starts with C) so SlackPoster skips the
    # name→id resolver (which would hit conversations_list — exercised
    # separately in the channel-resolution tests).
    await poster.upload_as(_persona(), "C0B06MCSLQ1", fpath, caption="here it is")
    fake.files_upload_v2.assert_awaited_once()
    kw = fake.files_upload_v2.await_args.kwargs
    assert kw["channel"] == "C0B06MCSLQ1"
    assert kw["file"] == str(fpath)
    assert kw["filename"] == "data.csv"
    assert kw["initial_comment"] == "here it is"


@pytest.mark.asyncio
async def test_upload_as_falls_back_to_files_upload(tmp_path: Path) -> None:
    fpath = tmp_path / "x.csv"
    fpath.write_text("a\n1\n", encoding="utf-8")

    fake = AsyncMock(spec=["files_upload", "chat_postMessage"])
    # Important: spec'd mock raises AttributeError for files_upload_v2,
    # mirroring an old slack-sdk where v2 isn't on the client.
    poster = SlackPoster("xoxb-test", client=fake)
    fake.files_upload = AsyncMock(return_value=_resp({"ok": True}))

    # Literal channel id — bypass the resolver path.
    await poster.upload_as(_persona(), "C0B06MCSLQ1", fpath)
    fake.files_upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_as_raises_on_missing_file(tmp_path: Path) -> None:
    poster, _ = _poster_with_mock()
    with pytest.raises(FileNotFoundError):
        await poster.upload_as(_persona(), "#x", tmp_path / "no-such.csv")
