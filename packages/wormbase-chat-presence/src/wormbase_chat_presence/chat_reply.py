# > AUTHORED 2026-05-03: Block H2 of the chat-worm extraction plan replaces
# > the G2 stub body with the full PEVR-cycle impl. The dataclass field
# > shape stays frozen so all G2 callers continue to construct unchanged.
"""_LedgerChatReply — concrete ChatReply impl over the ledger.

speak() writes a canonical PEVR cycle (4 entries: propose, execute, verify,
resolve). Each canonical envelope carries a chat_reply_* payload-shape kind:
  - propose.target_kind = "chat_reply_proposed"
  - execute.tool        = "emit_chat_reply_executed"
  - verify.checks       = [{"name": "channel_adapter_send_ok", "ok": <bool>}]
  - resolve.outcome     = "keep" | "discard" + rationale that names chat_reply

The actual ChannelAdapter.send happens BEFORE the ledger.write call so that
verify_fn / resolve_fn can read its outcome (timing, message_ref, error).
The execute envelope's payload records the timing and identifiers; the
verify envelope captures send success as authoritative state.

When channel_adapter=None (degrade path): the cycle still writes, but
verify.passed=False with check_name="channel_adapter_unavailable", resolve
outcome="discard", rationale="adapter unavailable". The audit trail
records "we tried to speak but had no adapter".

Mirrors the lake-maintainer _emit_signal pattern shape
(packages/lake-maintainer/src/wormbase_lake_maintainer/reactivities.py:61-100)
but ALSO includes a real send (vs observation-only) — the verify step
captures send success as authoritative state. NB: the canonical PEVR
contract requires verify.passed=True for the cycle to commit (False raises
VerifyFailed and rolls back). On send failure, we therefore treat the
cycle as "the worm tried and the channel rejected": we still want the
audit trail to land, so verify.passed must be True even on send failure.
The resolve.outcome carries the keep/discard signal instead. The check
name encodes the failure mode for the trace UI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_chat_presence.types import ConversationContext, MessageRef, SpeechAct
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger(__name__)


@dataclass
class _LedgerChatReply:
    """Ledger-backed ChatReply.

    Writes a 4-entry canonical PEVR cycle for every speak call. The cycle's
    payloads carry chat_reply_* domain-kind tags so the projection builder
    + trace UI can render the lifecycle.

    `channel_adapter` + `channel_adapter_handle` are the runtime path. When
    None, the cycle still writes but verify check is
    "channel_adapter_unavailable" and resolve outcome is "discard"
    (audit trail of "we tried to speak but had no adapter").

    Field shape is frozen as of G2 — no constructor changes in H2.
    """

    ledger: Ledger | InMemoryLedger
    company_id: UUID
    channel_adapter: Any  # ChannelAdapter Protocol — typed Any to keep import lean
    channel_adapter_handle: Any

    async def speak(
        self,
        ctx: ConversationContext,
        text: str,
        *,
        speech_act: SpeechAct,
        in_reply_to: str | None = None,
    ) -> MessageRef | None:
        chat_reply_id = uuid4()
        channel_id = ctx.channel_id or ""
        platform = _platform_from_adapter(self.channel_adapter)

        # Closure state — populated by _try_send before ledger.write so the
        # verify_fn / resolve_fn closures can read the outcome inline.
        sent_state: dict[str, Any] = {
            "started_at": None,
            "ended_at": None,
            "message_ref": None,
            "error": None,
        }

        # Run the send FIRST so verify_fn / resolve_fn can read its result.
        await _try_send(
            adapter=self.channel_adapter,
            handle=self.channel_adapter_handle,
            channel_id=channel_id,
            text=text,
            speech_act=speech_act,
            in_reply_to=in_reply_to,
            sent_state=sent_state,
        )

        propose_payload = {
            "target_kind": "chat_reply_proposed",
            "ref_id": str(chat_reply_id),
            "reason": (
                f"chat-worm speak: speech_act={speech_act} "
                f"channel={channel_id}"
            ),
            "proposed_by": "chat-worm",
        }

        def _execute() -> dict[str, Any]:
            started = sent_state.get("started_at") or datetime.now(UTC)
            ended = sent_state.get("ended_at") or started
            return {
                "tool": "emit_chat_reply_executed",
                "args": {
                    "chat_reply_id": str(chat_reply_id),
                    "channel_id": channel_id,
                    "platform": platform,
                    "adapter_call_started_at": started.isoformat(),
                    "adapter_call_ended_at": ended.isoformat(),
                },
                "result_ref": str(chat_reply_id),
            }

        await self.ledger.write(
            company_id=self.company_id,
            propose=propose_payload,
            execute_fn=_execute,
            verify_fn=_make_verify_fn(sent_state),
            resolve_fn=_make_resolve_fn(sent_state),
            timestamp=datetime.now(UTC),
            quadrant="active_probabilistic",
        )

        return sent_state.get("message_ref")


async def _try_send(
    *,
    adapter: Any,
    handle: Any,
    channel_id: str,
    text: str,
    speech_act: SpeechAct,
    in_reply_to: str | None,
    sent_state: dict[str, Any],
) -> None:
    """Issue the ChannelAdapter.send and record outcome into sent_state.

    Catches all exceptions so the PEVR cycle still writes (the failure is
    captured in verify.checks + resolve.outcome). When adapter is None we
    short-circuit with "channel_adapter_unavailable" — same audit shape.
    """
    sent_state["started_at"] = datetime.now(UTC)
    if adapter is None:
        sent_state["error"] = "channel_adapter_unavailable"
        sent_state["ended_at"] = datetime.now(UTC)
        logger.debug(
            "chat_reply.speak degraded: channel_adapter=None "
            "(channel_id=%s speech_act=%s)",
            channel_id, speech_act,
        )
        return
    try:
        msg = _make_out_message(text, speech_act, in_reply_to)
        ref = await adapter.send(handle, channel_id, msg)
        sent_state["message_ref"] = ref
    except Exception as exc:  # noqa: BLE001
        sent_state["error"] = str(exc) or exc.__class__.__name__
        logger.warning(
            "chat_reply.speak adapter.send failed (channel=%s): %s",
            channel_id, exc,
        )
    finally:
        sent_state["ended_at"] = datetime.now(UTC)


def _make_verify_fn(sent_state: dict[str, Any]):
    """Build the verify_fn closure that reads sent_state.

    The PEVR contract requires verify.passed=True for the cycle to commit
    (False raises VerifyFailed and rolls back the entries). For chat reply
    we always want the audit trail to land — even on send failure — so we
    always return passed=True. The check name encodes the success/failure
    mode so the trace UI + downstream projections can distinguish.
    """
    def _verify(_e: dict[str, Any]) -> dict[str, Any]:
        ok = (
            sent_state.get("error") is None
            and sent_state.get("message_ref") is not None
        )
        if ok:
            check_name = "channel_adapter_send_ok"
        elif sent_state.get("error") == "channel_adapter_unavailable":
            check_name = "channel_adapter_unavailable"
        else:
            check_name = (
                f"channel_adapter_send_failed:"
                f"{sent_state.get('error') or 'unknown'}"
            )
        return {
            "checks": [{"name": check_name, "ok": ok}],
            "passed": True,
        }
    return _verify


def _make_resolve_fn(sent_state: dict[str, Any]):
    def _resolve(_v: dict[str, Any]) -> dict[str, Any]:
        ok = (
            sent_state.get("error") is None
            and sent_state.get("message_ref") is not None
        )
        if ok:
            return {
                "outcome": "keep",
                "rationale": (
                    f"chat_reply resolved: sent message_ref="
                    f"{sent_state.get('message_ref')}"
                ),
            }
        return {
            "outcome": "discard",
            "rationale": (
                f"chat_reply discarded: send failed "
                f"(error={sent_state.get('error') or 'unknown'})"
            ),
        }
    return _resolve


def _make_out_message(
    text: str, speech_act: SpeechAct, in_reply_to: str | None,
) -> Any:
    """Build a minimal OutMessage for the channel adapter.

    Lazy-imported so chat-presence doesn't hard-depend on
    wormbase_channel_adapters when the adapter is None. Falls back to a
    plain dict when the import fails. `in_reply_to` maps to OutMessage's
    `thread_ref` field (the platform-native id of the parent message).
    """
    try:
        from wormbase_channel_adapters.types import OutMessage
        return OutMessage(text=text, blocks=[], thread_ref=in_reply_to)
    except Exception:  # noqa: BLE001
        return {
            "text": text,
            "speech_act": speech_act,
            "in_reply_to": in_reply_to,
            "thread_ref": in_reply_to,
        }


def _platform_from_adapter(adapter: Any) -> str:
    if adapter is None:
        return "unknown"
    return str(getattr(adapter, "platform", "unknown"))


__all__ = ["_LedgerChatReply"]
