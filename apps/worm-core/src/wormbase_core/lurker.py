"""Slack lurker — concurrent SocketMode listener writing chat_received entries.

The PRD's "Listen-for-ingest is always on" invariant requires that every
inbound channel/dm event becomes a chat_received ledger entry, regardless
of whether OpenClaw decides to invoke the agent. This module subscribes
to Slack events using slack_bolt's AsyncSocketModeHandler with the same
SLACK_APP_TOKEN_BASEWORM/SLACK_BOT_TOKEN_BASEWORM tokens. Slack supports
concurrent socket connections per app token, so this listener runs
alongside OpenClaw's listener without conflict.

The lurker also forwards each event into the ReactivityPipeline so that
infrastructure_trigger / semantic_trigger / relevance_decision entries
land in the ledger and the source-building flows can fire when relevant.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4, uuid5

from wormbase_core.reactivity import ReactivityPipeline
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import ChatReceivedPayload

logger = logging.getLogger("wormbase_core.lurker")


# Stable namespace so the same Slack user maps to the same UUID across runs.
SLACK_USER_NAMESPACE = uuid5(
    UUID("00000000-0000-0000-0000-000000000000"),
    "wormbase-slack-user",
)


def slack_user_to_person(slack_user_id: str | None) -> UUID:
    if not slack_user_id:
        return uuid5(SLACK_USER_NAMESPACE, "__unknown__")
    return uuid5(SLACK_USER_NAMESPACE, slack_user_id)


class SlackLurker:
    """Subscribes to Slack events; writes chat_received; runs reactivity."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        pipeline: ReactivityPipeline | None = None,
        *,
        app_token: str | None = None,
        bot_token: str | None = None,
        flow_dispatcher: Callable[[dict, Any], Awaitable[None]] | None = None,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._pipeline = pipeline
        # Prefer the dedicated Observer-app tokens (deterministic capture via
        # a separate Slack app, no SocketMode load-balancing with OpenClaw).
        # Fall back to the OpenClaw shared tokens for legacy / single-app
        # setups (tests, dev environments without a second app provisioned).
        self._app_token = (
            app_token
            or os.environ.get("SLACK_APP_TOKEN_OBSERVER_BASEWORM")
            or os.environ.get("SLACK_APP_TOKEN_BASEWORM")
        )
        self._bot_token = (
            bot_token
            or os.environ.get("SLACK_BOT_TOKEN_OBSERVER_BASEWORM")
            or os.environ.get("SLACK_BOT_TOKEN_BASEWORM")
        )
        self._flow_dispatcher = flow_dispatcher
        self._app: Any = None
        self._handler: Any = None

    def _build_app(self) -> Any:
        # Imported lazily so non-Slack consumers aren't forced to depend
        # on slack_bolt at import time.
        from slack_bolt.async_app import AsyncApp

        if not self._bot_token:
            raise RuntimeError(
                "SLACK_BOT_TOKEN_BASEWORM not set; cannot start lurker"
            )
        app = AsyncApp(token=self._bot_token, name="wormbase-lurker")

        @app.event("message")
        async def _on_message(event: dict, body: dict, logger=logger):
            await self._handle_event(event, body, kind="channel_message")

        @app.event("file_shared")
        async def _on_file_shared(event: dict, body: dict, logger=logger):
            await self._handle_event(event, body, kind="file_drop")

        @app.event("app_mention")
        async def _on_mention(event: dict, body: dict, logger=logger):
            await self._handle_event(event, body, kind="channel_message")

        return app

    async def _handle_event(
        self, event: dict, body: dict, *, kind: str
    ) -> None:
        # Skip bot's own messages.
        if event.get("subtype") == "bot_message" and event.get("bot_id"):
            return
        text = event.get("text", "") or ""
        channel_id = event.get("channel") or event.get("channel_id")
        user_id = event.get("user")
        ts = event.get("event_ts") or event.get("ts") or "0"
        # Always write chat_received first (the lurker invariant).
        await self._write_chat_received(text, channel_id, user_id, ts)
        if self._pipeline is None:
            return
        # Forward the event into the reactivity pipeline.
        try:
            decision = await self._pipeline.process(
                {
                    "type": kind,
                    "ts": float(ts),
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "text": text,
                    "message_id": event.get("client_msg_id") or ts,
                    "company_id": str(self._company_id),
                    "payload": event,
                }
            )
            if self._flow_dispatcher and decision and decision.should_react:
                await self._flow_dispatcher(event, decision)
        except Exception as exc:  # noqa: BLE001
            logger.error("lurker reactivity failed: %s", exc)

    async def _write_chat_received(
        self, text: str, channel_id: str | None, user_id: str | None,
        ts: str,
    ) -> None:
        sender_person = slack_user_to_person(user_id)
        try:
            payload = ChatReceivedPayload(
                channel_id=channel_id or "unknown",
                message_id=str(ts),
                sender_person=sender_person,
                text=text,
                classification="internal",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("lurker payload validation failed: %s", exc)
            return
        ref = uuid4()
        try:
            await self._ledger.write(
                company_id=self._company_id,
                propose={
                    "target_kind": "chat_received",
                    "ref_id": str(ref),
                    "reason": f"lurker observed inbound from {user_id or '?'}",
                    "proposed_by": "lurker",
                },
                execute_fn=lambda: {
                    "tool": "emit_chat_received",
                    "args": payload.model_dump(mode="json"),
                    "result_ref": str(ts),
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": "lurker captured inbound",
                },
                quadrant="passive_probabilistic",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("lurker ledger write failed: %s", exc)

    async def start(self) -> None:
        from slack_bolt.adapter.socket_mode.async_handler import (
            AsyncSocketModeHandler,
        )

        if not self._app_token:
            raise RuntimeError(
                "SLACK_APP_TOKEN_BASEWORM not set; lurker cannot start"
            )
        self._app = self._build_app()
        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        logger.info("lurker starting via SocketMode")
        await self._handler.start_async()

    async def stop(self) -> None:
        if self._handler is not None:
            try:
                await self._handler.close_async()
            except Exception:  # noqa: BLE001, S110
                pass


__all__ = ["SlackLurker", "slack_user_to_person"]
