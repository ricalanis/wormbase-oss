"""make_chat_dispatcher — replaces make_flow_dispatcher_with_proactivity.

The dispatcher's call signature is preserved from
apps/worm-core/src/wormbase_core/service.py:632-684:

    async def dispatcher(event: dict, decision: RelevanceDecision) -> None: ...

Implementation routes by `decision.suggested_flow`:
  - "drop_and_profile"          → DropAndProfileFlow.on_file_drop(infra)
                                  → cascade(infra, correlation_id) if wired
  - "credential_offered_in_dm"  → CredentialInDmFlow.on_dm(infra)
  - "mentioned_in_conversation" → MentionedInConversationFlow.on_proactive_mention(infra)
  - other                       → no-op (logged for trace)

Note: ChatReply.speak is NOT called here — the four Reactivities
(F1-F4) own the speech path. The dispatcher only routes flows. This is a
v1 transitional surface; future waves collapse flow routing into per-flow
Reactivities, eliminating the dispatcher entirely.

O-B1 (deferred-backlog Block D, 2026-05-04): the optional ``cascade``
kwarg restores the bronze→silver→gold chain that regressed when Wave B
extracted chat-worm out of make_flow_dispatcher_with_proactivity. The
adapter signature is ``async (infra, correlation_id) -> None`` — the
correlation_id from on_file_drop is required to resolve the source_id
through SourceBuilder's stash (see cascade_after_propose in
apps/worm-core/src/wormbase_core/flows.py:352).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# Pinned mirror of wormbase_core.service._FILE_DROP_TYPES — see
# docs/superpowers/specs/2026-05-04-helper-duplications-register.md (O-B5).
_FILE_DROP_TYPES = ("file_share", "file_shared", "file_drop")


def _event_to_infra(event: dict, company_id: UUID):
    from datetime import UTC, datetime as _dt

    from wormbase_core.reactivity import InfraEvent
    ts_raw = event.get("event_ts") or event.get("ts") or 0
    if isinstance(ts_raw, _dt):
        ts_dt = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
    else:
        ts_num = float(ts_raw or 0)
        ts_dt = _dt.fromtimestamp(ts_num, tz=UTC) if ts_num else _dt.now(UTC)
    # Flows (DropAndProfileFlow.on_file_drop, etc.) read trigger-specific
    # fields off InfraEvent.payload directly (e.g. payload.get("filename")).
    # The synthesized event from the ledger-poller wraps those fields in
    # an inner `payload` dict — pass the inner dict through so flow code
    # finds them at the top level. Falls back to the whole event for the
    # legacy lurker shape, which inlined the Slack event object.
    inner_payload = event.get("payload")
    flow_payload = (
        inner_payload if isinstance(inner_payload, dict) else event
    )
    etype = event.get("type")
    if etype == "dm":
        source = "dm"
    elif etype in _FILE_DROP_TYPES:
        source = "file_drop"
    else:
        source = "channel_message"

    # Provenance fields propagate to the InfraEvent's is_live derivation
    # downstream. Caller's responsibility to thread platform_ts as a
    # datetime (or None) — we don't parse strings here.
    delivery_mode = event.get("delivery_mode") or "push"
    if delivery_mode not in ("push", "history_sync"):
        delivery_mode = "push"
    platform_ts = event.get("platform_ts")
    history_sync_id = event.get("history_sync_id")

    return InfraEvent(
        source=source,
        payload=flow_payload,
        ts=ts_dt,
        company_id=company_id,
        channel_id=event.get("channel") or event.get("channel_id"),
        person_id=event.get("user") or event.get("user_id"),
        message_id=event.get("client_msg_id") or event.get("message_id") or str(ts_raw),
        text=event.get("text", "") or "",
        delivery_mode=delivery_mode,
        platform_ts=platform_ts,
        history_sync_id=history_sync_id,
    )


def make_chat_dispatcher(
    *,
    drop_and_profile: Any,
    credential_in_dm: Any,
    mentioned_in_conversation: Any,
    company_id: UUID,
    cascade: Any | None = None,
):
    """Build the chat-worm flow dispatcher.

    The four chat-driven flows are passed in by name (not via the install
    obj) so wire_chat_for_install can use the existing worm-core
    SourceBuilder + governance gate wiring without forcing chat-worm to
    own those constructions.

    ``cascade`` is an optional callable
    ``async (infra: InfraEvent, correlation_id: UUID | str) -> None``.
    When supplied, it fires after a successful
    ``drop_and_profile.on_file_drop`` so the medallion bronze/silver/gold
    chain materializes on every file_drop. When ``None`` (legacy posture),
    the dispatcher behaves as before — propose only, no cascade. Wired
    in production by ``cli.py`` against ``cascade_after_propose`` (see
    O-B1, deferred-backlog Block D).
    """

    async def _dispatch(event: dict[str, Any], decision: Any) -> None:
        sf = getattr(decision, "suggested_flow", None)
        if not getattr(decision, "should_react", False):
            return

        infra = _event_to_infra(event, company_id)

        try:
            if sf == "drop_and_profile" or event.get("type") == "file_drop":
                correlation_id = await drop_and_profile.on_file_drop(infra)
                if cascade is not None and correlation_id is not None:
                    try:
                        await cascade(infra, correlation_id)
                    except Exception as exc:  # noqa: BLE001
                        # Cascade failure must not poison the propose; log
                        # and move on so the four base lifecycle entries
                        # still complete.
                        logger.warning(
                            "chat-worm dispatcher cascade failed (cid=%s): %s",
                            correlation_id, exc,
                        )
            elif sf == "credential_offered_in_dm":
                await credential_in_dm.on_dm(infra)
            elif sf == "mentioned_in_conversation":
                await mentioned_in_conversation.on_proactive_mention(infra)
            else:
                logger.debug(
                    "chat-worm dispatcher: no-op for suggested_flow=%s type=%s",
                    sf, event.get("type"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chat-worm dispatcher failed (sf=%s type=%s): %s",
                sf, event.get("type"), exc,
            )

    return _dispatch


__all__ = ["make_chat_dispatcher"]
