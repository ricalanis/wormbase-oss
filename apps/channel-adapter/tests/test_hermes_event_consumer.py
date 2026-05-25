"""Tests for the Hermes wire-tap HTTP consumer (Phase 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from wormbase_channel_adapter.hermes_event_consumer import (
    DEFAULT_PATH,
    HermesEventConsumer,
    _TranslateError,
)
from wormbase_channel_adapter.parser import ChatReceivedEvent


# ---------------------------------------------------------------------------
# Helpers — build a consumer that we can drive synchronously for tests
# ---------------------------------------------------------------------------


def _make_consumer_with_app() -> tuple[HermesEventConsumer, web.Application, AsyncMock]:
    """Build a HermesEventConsumer + an aiohttp Application whose routes
    point at the consumer's handlers. Returns the mock writer so tests
    can inspect emit() calls.
    """
    mock_writer = AsyncMock()
    consumer = HermesEventConsumer(writer=mock_writer)
    app = web.Application()
    app.router.add_post(DEFAULT_PATH, consumer._handle_post)
    app.router.add_get("/healthz", consumer._handle_healthz)
    return consumer, app, mock_writer


def _minimal_agent_start_payload(**overrides: Any) -> dict[str, Any]:
    """Build the smallest well-formed wire-tap payload for agent:start."""
    payload: dict[str, Any] = {
        "received_at": "2026-05-21T18:00:00.000+00:00",
        "event_type": "agent:start",
        "tenant": "altis",
        "context": {
            "platform": "slack",
            "user_id": "U0AV4C8TTEZ",
            "session_id": "5d8efadc-1234-4abc-9def-0123456789ab",
            "message": "hola from slack",
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


async def test_healthz_returns_ok() -> None:
    _, app, _ = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/healthz")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"ok": True, "service": "hermes-event-consumer"}


# ---------------------------------------------------------------------------
# agent:start happy path
# ---------------------------------------------------------------------------


async def test_agent_start_emits_chat_received() -> None:
    _, app, mock_writer = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            DEFAULT_PATH,
            json=_minimal_agent_start_payload(),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
        assert "message_id" in body

    # The writer.emit() was called exactly once with a ChatReceivedEvent.
    assert mock_writer.emit.await_count == 1
    event = mock_writer.emit.await_args.args[0]
    assert isinstance(event, ChatReceivedEvent)
    assert event.text == "hola from slack"
    assert event.sender_id == "U0AV4C8TTEZ"
    assert event.sender_label == "U0AV4C8TTEZ"
    # No channel_id in the payload → sentinel
    assert event.channel_id == (
        "hermes-session:5d8efadc-1234-4abc-9def-0123456789ab"
    )
    assert event.message_id.startswith("hermes:slack:")
    assert event.session_id == "hermes:5d8efadc-1234-4abc-9def-0123456789ab"
    assert event.delivery_mode == "push"


async def test_agent_start_uses_richer_context_when_present() -> None:
    """When the wire-tap hook is extended to include channel_id +
    message_ts, the consumer uses them instead of synthetic sentinels."""
    _, app, mock_writer = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            DEFAULT_PATH,
            json=_minimal_agent_start_payload(
                context={
                    "platform": "slack",
                    "user_id": "U0AV4C8TTEZ",
                    "session_id": "abc",
                    "message": "richer",
                    "channel_id": "C0B06MCSLQ1",
                    "message_ts": "1779388595.682",
                },
            ),
        )
        assert resp.status == 200

    event = mock_writer.emit.await_args.args[0]
    assert event.channel_id == "C0B06MCSLQ1"
    assert event.message_id == "1779388595.682"


async def test_empty_message_is_skipped_not_errored() -> None:
    """A reaction-only / placeholder event with empty text returns 200
    `skipped` and does NOT call the writer."""
    _, app, mock_writer = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            DEFAULT_PATH,
            json=_minimal_agent_start_payload(
                context={
                    "platform": "slack",
                    "user_id": "U0AV4C8TTEZ",
                    "session_id": "abc",
                    "message": "   ",
                },
            ),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body == {"ok": True, "skipped": "empty_text"}
    mock_writer.emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# session:start / session:end no-ops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ["session:start", "session:end"])
async def test_session_events_skipped(event_type: str) -> None:
    _, app, mock_writer = _make_consumer_with_app()
    payload = _minimal_agent_start_payload(event_type=event_type)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=payload)
        assert resp.status == 200
        body = await resp.json()
        assert body == {"ok": True, "skipped": event_type}
    mock_writer.emit.assert_not_awaited()


async def test_unknown_event_type_skipped() -> None:
    _, app, mock_writer = _make_consumer_with_app()
    payload = _minimal_agent_start_payload(event_type="agent:step")
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=payload)
        assert resp.status == 200
        body = await resp.json()
        assert body == {"ok": True, "skipped": "agent:step"}
    mock_writer.emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Malformed payloads return 400 without crashing the loop
# ---------------------------------------------------------------------------


async def test_non_object_payload_returns_400() -> None:
    _, app, mock_writer = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=["not", "an", "object"])
        assert resp.status == 400
        body = await resp.json()
        assert body["ok"] is False
    mock_writer.emit.assert_not_awaited()


async def test_missing_event_type_returns_400() -> None:
    _, app, mock_writer = _make_consumer_with_app()
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json={"context": {}})
        assert resp.status == 400
        body = await resp.json()
        assert body == {"ok": False, "error": "missing_event_type"}
    mock_writer.emit.assert_not_awaited()


@pytest.mark.parametrize(
    "missing_field",
    ["user_id", "session_id", "message"],
)
async def test_missing_required_context_field_returns_400(missing_field: str) -> None:
    _, app, mock_writer = _make_consumer_with_app()
    payload = _minimal_agent_start_payload()
    payload["context"].pop(missing_field)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=payload)
        assert resp.status == 400
        body = await resp.json()
        assert body["ok"] is False
        assert missing_field in body["error"]
    mock_writer.emit.assert_not_awaited()


async def test_writer_failure_returns_500_but_does_not_crash() -> None:
    _, app, mock_writer = _make_consumer_with_app()
    mock_writer.emit.side_effect = RuntimeError("ledger unavailable")
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            DEFAULT_PATH,
            json=_minimal_agent_start_payload(),
        )
        assert resp.status == 500
        body = await resp.json()
        assert body["ok"] is False
        assert body["error"] == "writer_failed"
        assert "ledger unavailable" in body["detail"]


# ---------------------------------------------------------------------------
# Translation helper edge cases (unit-level, no HTTP)
# ---------------------------------------------------------------------------


def test_translate_synthesizes_stable_message_id() -> None:
    """Two identical payloads → identical synthetic message_ids
    (so the writer's dedup absorbs replays)."""
    mock_writer = AsyncMock()
    consumer = HermesEventConsumer(writer=mock_writer)
    payload = _minimal_agent_start_payload()
    a = consumer._translate_agent_start(payload)
    b = consumer._translate_agent_start(payload)
    assert a is not None and b is not None
    assert a.message_id == b.message_id


def test_translate_received_at_falls_back_to_now_on_garbage() -> None:
    mock_writer = AsyncMock()
    consumer = HermesEventConsumer(writer=mock_writer)
    payload = _minimal_agent_start_payload(received_at="not-an-iso8601")
    event = consumer._translate_agent_start(payload)
    assert event is not None
    # Should fall back to now() — within 5s of test start.
    delta = abs((event.ts - datetime.now(tz=UTC)).total_seconds())
    assert delta < 5.0


def test_translate_raises_on_missing_context() -> None:
    mock_writer = AsyncMock()
    consumer = HermesEventConsumer(writer=mock_writer)
    payload = _minimal_agent_start_payload()
    payload["context"] = "not a dict"  # type: ignore[assignment]
    with pytest.raises(_TranslateError, match="missing_context"):
        consumer._translate_agent_start(payload)
