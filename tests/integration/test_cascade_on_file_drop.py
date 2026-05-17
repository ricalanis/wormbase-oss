"""Block D — O-B1 cascade-on-file-drop regression pin.

Wave B's chat-worm extraction (2026-05-03) replaced
``make_flow_dispatcher_with_proactivity`` (which composed
``make_flow_dispatcher_with_cascade``) with ``make_chat_dispatcher`` from
the chat-presence package. The new dispatcher routes ``file_drop`` to
``DropAndProfileFlow.on_file_drop`` but does NOT chain into
``cascade_after_propose``. Bronze/silver/gold no longer materialize on
file_drop in the chat pipeline.

This test pins the regression: a file_drop routed through the chat
dispatcher must produce ``emit_source_bronzed`` + ``emit_source_silvered``
ledger entries (gold is conditional on the profile, so we don't hard
require it). On a clean main this test FAILS — the dispatcher's existing
shape only yields the four propose/confirm/connect/profile entries, no
cascade.

After D.2, the chat dispatcher accepts a ``cascade`` callable kwarg that
fires after ``drop_and_profile.on_file_drop``. The test then passes.

D.3 adds the no-double-fire smoke (single bronze/silver chain).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest


pytestmark = pytest.mark.asyncio


def _file_drop_event(channel: str = "C-DROP", user: str = "U-HUMAN") -> dict[str, Any]:
    """Slack-shaped file_share event, as the chat_received poller emits."""
    return {
        "type": "file_share",
        "channel": channel,
        "user": user,
        "event_ts": "1777152782.000099",
        "client_msg_id": "m-cascade-1",
        "text": "subscriptions.csv",
        "payload": {
            "filename": "subscriptions.csv",
            "mimetype": "text/csv",
            "bytes_url": "file:///tmp/subscriptions.csv",
        },
    }


def _decision(should_react: bool = True, sf: str = "drop_and_profile"):
    """Minimal RelevanceDecision duck — dispatcher reads two attrs."""
    class _D:
        should_react = True
        suggested_flow = sf
    d = _D()
    d.should_react = should_react
    d.suggested_flow = sf
    return d


def _kind_count(rows: list[dict], tool: str) -> int:
    return sum(
        1 for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    )


async def test_file_drop_via_chat_dispatcher_triggers_cascade(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    """RED: file_drop through chat dispatcher must materialize bronze + silver.

    Pre-D.2: dispatcher only fires drop_and_profile; cascade never runs;
    bronze/silver counts are zero. Post-D.2: cascade fires once and
    bronze/silver land.
    """
    from wormbase_chat_presence.dispatcher import make_chat_dispatcher
    from wormbase_core.flows import cascade_after_propose
    from wormbase_core.medallion import MedallionCascade

    worm = worm_core_integration

    cascade = MedallionCascade(integration_ledger)

    async def _cascade_adapter(infra, correlation_id):
        # Mirrors the production wiring in cli.py — drop_and_profile's
        # SourceBuilder is the canonical correlation_id → source_id map.
        payload = infra.payload or {}
        uri = (
            payload.get("bytes_url")
            or payload.get("url")
            or f"file://{payload.get('filename', 'unknown')}"
        )
        mime = payload.get("mimetype") or None
        await cascade_after_propose(
            worm.drop_and_profile.builder,
            cascade,
            correlation_id=str(correlation_id),
            company_id=integration_company_id,
            uri=uri,
            mime=mime,
        )

    dispatcher = make_chat_dispatcher(
        drop_and_profile=worm.drop_and_profile,
        credential_in_dm=worm.credential_in_dm,
        mentioned_in_conversation=worm.mentioned_in_conversation,
        company_id=integration_company_id,
        cascade=_cascade_adapter,
    )

    await dispatcher(_file_drop_event(), _decision())

    rows = await integration_ledger.fetch(integration_company_id)

    # The base flow must fire (sanity, not the regression check).
    assert _kind_count(rows, "emit_source_proposed") >= 1, (
        "drop_and_profile.on_file_drop did not fire — chat dispatcher is "
        "broken at a level deeper than the cascade regression."
    )

    # The regression: cascade must materialize bronze + silver. Pre-D.2
    # this assert fails with bronze=0, silver=0.
    assert _kind_count(rows, "emit_source_bronzed") >= 1, (
        "regression: emit_source_bronzed missing — chat dispatcher does "
        "not chain into cascade_after_propose. "
        f"All execute tools: {sorted({r['payload'].get('tool') for r in rows if r['kind'] == 'execute'})}"
    )
    assert _kind_count(rows, "emit_source_silvered") >= 1, (
        "regression: emit_source_silvered missing — silver layer didn't "
        "follow bronze."
    )


async def test_file_drop_chat_dispatcher_no_double_cascade(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    """D.3 — exactly one bronze/silver chain per file_drop, never two.

    Guards against a future refactor that wires the cascade in two places
    (e.g. dispatcher AND a Reactivity). Production must produce one chain
    per drop.
    """
    from wormbase_chat_presence.dispatcher import make_chat_dispatcher
    from wormbase_core.flows import cascade_after_propose
    from wormbase_core.medallion import MedallionCascade

    worm = worm_core_integration

    cascade = MedallionCascade(integration_ledger)
    cascade_calls: list[str] = []

    async def _cascade_adapter(infra, correlation_id):
        cascade_calls.append(str(correlation_id))
        payload = infra.payload or {}
        uri = (
            payload.get("bytes_url")
            or payload.get("url")
            or f"file://{payload.get('filename', 'unknown')}"
        )
        mime = payload.get("mimetype") or None
        await cascade_after_propose(
            worm.drop_and_profile.builder,
            cascade,
            correlation_id=str(correlation_id),
            company_id=integration_company_id,
            uri=uri,
            mime=mime,
        )

    dispatcher = make_chat_dispatcher(
        drop_and_profile=worm.drop_and_profile,
        credential_in_dm=worm.credential_in_dm,
        mentioned_in_conversation=worm.mentioned_in_conversation,
        company_id=integration_company_id,
        cascade=_cascade_adapter,
    )

    await dispatcher(_file_drop_event(), _decision())

    rows = await integration_ledger.fetch(integration_company_id)
    assert len(cascade_calls) == 1, (
        f"cascade adapter fired {len(cascade_calls)} times; expected exactly 1"
    )
    assert _kind_count(rows, "emit_source_bronzed") == 1, (
        "exactly one bronze entry per drop — got "
        f"{_kind_count(rows, 'emit_source_bronzed')}"
    )
    assert _kind_count(rows, "emit_source_silvered") == 1, (
        "exactly one silver entry per drop — got "
        f"{_kind_count(rows, 'emit_source_silvered')}"
    )
