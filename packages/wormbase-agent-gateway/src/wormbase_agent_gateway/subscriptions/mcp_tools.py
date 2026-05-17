"""MCP tools — agent.subscriptions.create / list / revoke / stream (v2.A Task 4).

Four tools the calling agent uses to manage its own subscriptions:

  * ``agent.subscriptions.create`` — register interest; returns subscription_id.
  * ``agent.subscriptions.list``   — list active subscriptions for an agent.
  * ``agent.subscriptions.revoke`` — revoke a subscription.
  * ``agent.subscriptions.stream`` — SSE-style long-poll yielding events.

Authentication: every tool resolves the calling AgentID via the existing
``deps.agent_id_resolver`` and rejects any operation where the supplied
``agent_id`` (or, for revoke/stream, the subscription owner) does not match
the calling agent. Admins can override via dashboard (v2.A Task 7) — that
path uses an HTTP write surface, not these MCP tools.

The tools write their lifecycle entries via the worm-core ``write_actions``
pattern (``Ledger.write(propose=, execute_fn=, verify_fn=, resolve_fn=)``)
so every operation is a PEVR cycle and replays deterministically.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from wormbase_inference import AgentID

from wormbase_agent_gateway.subscriptions.dispatcher import SubscriptionReader
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.stream_transport import (
    ListModeTransport,
    StreamTransport,
)

logger = logging.getLogger("wormbase_agent_gateway.subscriptions.mcp_tools")


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class SubscriptionCreateResponse(BaseModel):
    """Returned by ``agent.subscriptions.create``."""

    subscription_id: str
    agent_id: str
    transport: Literal["mcp_stream", "webhook"]


class SubscriptionListResponse(BaseModel):
    """Returned by ``agent.subscriptions.list``."""

    subscriptions: list[dict[str, Any]] = Field(default_factory=list)


class SubscriptionRevokeResponse(BaseModel):
    """Returned by ``agent.subscriptions.revoke``."""

    revoked: bool
    subscription_id: str


class SubscriptionDeniedResponse(BaseModel):
    """Returned when the calling agent is not the subscription owner.

    Mirrors the shape of the global :class:`DeniedResponse` so MCP
    clients can branch on ``status="denied"`` uniformly.
    """

    status: Literal["denied"] = "denied"
    reason: str
    subscription_id: str | None = None


# ---------------------------------------------------------------------------
# Deps bundle
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionToolDeps:
    """Per-tool deps for the 4 subscription tools.

    ``subscription_reader`` is the same reader the dispatcher consumes —
    sharing the implementation keeps "create returns subscription_id"
    and "list shows it" consistent (no read-your-writes lag).

    ``stream_transport`` selects how the stream tool materializes the
    async-generator events (Path 3, 2026-05-21). Default is
    :class:`ListModeTransport` — byte-identical to the pre-Path-3
    inline wrapper. ``SseStreamTransport`` is opt-in via the env knob
    ``WORMBASE_MCP_SSE_TRANSPORT``; see
    :mod:`wormbase_agent_gateway.subscriptions.stream_transport`.
    """

    ledger: Any
    company_id: UUID
    subscription_reader: SubscriptionReader
    stream_registry: StreamRegistry
    stream_transport: StreamTransport | None = None

    def __post_init__(self) -> None:
        # Default the transport to ListModeTransport when callers don't
        # provide one. Keeps construction sites that predate Path 3
        # (tests, existing wiring) byte-identical without forcing each
        # one to import the transport module.
        if self.stream_transport is None:
            self.stream_transport = ListModeTransport()


# ---------------------------------------------------------------------------
# Tool implementations (callable directly + via FastMCP wrappers)
# ---------------------------------------------------------------------------


async def create_subscription(
    *,
    agent_id: str,
    filter: dict[str, Any],
    transport: str,
    webhook_url: str | None = None,
    webhook_secret_ref: str | None = None,
    description: str | None = None,
    deps: SubscriptionToolDeps,
    calling_agent_id: AgentID,
) -> SubscriptionCreateResponse | SubscriptionDeniedResponse:
    """Create a subscription. Agent must register subscriptions for itself.

    Cross-agent registration (agent A registering for agent B) is denied
    at this layer — admin-driven cross-grants are a v2.A Task 7 dashboard
    concern, not an MCP-tool concern.
    """
    if calling_agent_id.value != agent_id:
        return SubscriptionDeniedResponse(
            reason=(
                f"calling agent {calling_agent_id.value!r} may not create "
                f"subscriptions on behalf of {agent_id!r}; admin-grant flow "
                f"is dashboard-only"
            ),
        )
    if transport not in ("mcp_stream", "webhook"):
        return SubscriptionDeniedResponse(
            reason=f"unknown transport {transport!r}; expected 'mcp_stream' or 'webhook'",
        )
    if transport == "webhook":
        if not webhook_url or not webhook_secret_ref:
            return SubscriptionDeniedResponse(
                reason=(
                    "webhook transport requires both webhook_url and "
                    "webhook_secret_ref"
                ),
            )

    subscription_id = str(uuid4())
    args: dict[str, Any] = {
        "subscription_id": subscription_id,
        "agent_id": agent_id,
        "filter": dict(filter or {}),
        "transport": transport,
        "webhook_url": webhook_url,
        "webhook_secret_ref": webhook_secret_ref,
        "description": description,
    }

    await deps.ledger.write(
        company_id=deps.company_id,
        propose={
            "target_kind": "agent_subscription_created",
            "ref_id": subscription_id,
            "agent_id": agent_id,
            "transport": transport,
        },
        execute_fn=lambda: {
            "tool": "emit_agent_subscription_created",
            "args": dict(args),
            "result_ref": subscription_id,
        },
        verify_fn=lambda _e: {
            "checks": [
                {"name": "agent_subscription_created_recorded", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": (
                f"agent {agent_id!r} subscribed via {transport!r}"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )

    return SubscriptionCreateResponse(
        subscription_id=subscription_id,
        agent_id=agent_id,
        transport=transport,  # type: ignore[arg-type]
    )


async def list_subscriptions(
    *,
    agent_id: str,
    deps: SubscriptionToolDeps,
    calling_agent_id: AgentID,
) -> SubscriptionListResponse | SubscriptionDeniedResponse:
    """List active subscriptions owned by ``agent_id``.

    Agents may only list their own subscriptions via this tool. Admin
    cross-agent listing lives in the dashboard (v2.A Task 7).
    """
    if calling_agent_id.value != agent_id:
        return SubscriptionDeniedResponse(
            reason=(
                f"calling agent {calling_agent_id.value!r} may not list "
                f"subscriptions on behalf of {agent_id!r}"
            ),
        )
    active = await deps.subscription_reader.active_subscriptions(
        deps.company_id,
    )
    mine = [
        _serialize_subscription_row(row)
        for row in active
        if str(row.get("agent_id") or "") == agent_id
    ]
    return SubscriptionListResponse(subscriptions=mine)


async def revoke_subscription(
    *,
    subscription_id: str,
    reason: str = "agent_request",
    deps: SubscriptionToolDeps,
    calling_agent_id: AgentID,
) -> SubscriptionRevokeResponse | SubscriptionDeniedResponse:
    """Revoke a subscription. The caller must own it.

    Reason must be one of {agent_request, admin_revoked, expired, rotated};
    ``admin_revoked`` is technically callable from the MCP path but the
    audit row's ``agent_id`` field will be the agent's, not an admin's —
    in practice the dashboard uses a separate write surface for admin
    revocations.
    """
    if reason not in ("agent_request", "admin_revoked", "expired", "rotated"):
        return SubscriptionDeniedResponse(
            reason=f"unknown revocation reason {reason!r}",
            subscription_id=subscription_id,
        )

    # Verify the caller owns this subscription.
    active = await deps.subscription_reader.active_subscriptions(
        deps.company_id,
    )
    owned = {
        str(row.get("subscription_id") or ""): str(row.get("agent_id") or "")
        for row in active
    }
    if subscription_id not in owned:
        return SubscriptionDeniedResponse(
            reason=(
                f"subscription {subscription_id!r} does not exist or is "
                f"already revoked"
            ),
            subscription_id=subscription_id,
        )
    if owned[subscription_id] != calling_agent_id.value:
        return SubscriptionDeniedResponse(
            reason=(
                f"calling agent {calling_agent_id.value!r} does not own "
                f"subscription {subscription_id!r}"
            ),
            subscription_id=subscription_id,
        )

    args: dict[str, Any] = {
        "subscription_id": subscription_id,
        "reason": reason,
    }
    await deps.ledger.write(
        company_id=deps.company_id,
        propose={
            "target_kind": "agent_subscription_revoked",
            "ref_id": subscription_id,
            "reason": reason,
        },
        execute_fn=lambda: {
            "tool": "emit_agent_subscription_revoked",
            "args": dict(args),
            "result_ref": subscription_id,
        },
        verify_fn=lambda _e: {
            "checks": [
                {"name": "agent_subscription_revoked_recorded", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"subscription revoked: {reason}",
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )

    # Drop the per-subscription queue — no further consumer is interested.
    deps.stream_registry.clear(subscription_id)

    return SubscriptionRevokeResponse(
        revoked=True, subscription_id=subscription_id,
    )


async def stream_subscription(
    *,
    subscription_id: str,
    since_seq: int = 0,
    deps: SubscriptionToolDeps,
    calling_agent_id: AgentID,
) -> AsyncIterator[dict[str, Any]]:
    """Yield events for a subscription as an async generator.

    Resumption semantics:

      * If ``since_seq > 0``: replay all ``agent_event_delivered`` entries
        for this subscription whose ``triggering_entry_seq > since_seq``,
        oldest-first.
      * After replay: enter live-tail mode by reading from the per-subscription
        ``StreamRegistry`` queue.

    The generator returns when the caller breaks out of its iteration.
    FastMCP's tool runner is responsible for cancellation propagation.

    Auth: the calling agent must own the subscription. We perform the
    check on entry; if the sub is later revoked the queue will be cleared
    and ``get()`` will hang until the next event — production deploys
    set a tool-level timeout on long-poll streams.
    """
    active = await deps.subscription_reader.active_subscriptions(
        deps.company_id,
    )
    owner = None
    for row in active:
        if str(row.get("subscription_id") or "") == subscription_id:
            owner = str(row.get("agent_id") or "")
            break
    if owner is None:
        # Not active — either never existed or revoked. Surface that as a
        # single-shot error event and return.
        yield {
            "status": "denied",
            "reason": (
                f"subscription {subscription_id!r} not active"
            ),
        }
        return
    if owner != calling_agent_id.value:
        yield {
            "status": "denied",
            "reason": (
                f"calling agent {calling_agent_id.value!r} does not own "
                f"subscription {subscription_id!r}"
            ),
        }
        return

    # Resumption replay — fetch agent_event_delivered entries with
    # triggering_entry_seq > since_seq for this subscription.
    if since_seq > 0:
        replayed = await _replay_delivered(
            ledger=deps.ledger,
            company_id=deps.company_id,
            subscription_id=subscription_id,
            since_seq=since_seq,
        )
        for event in replayed:
            yield event

    # Live-tail loop. The caller breaks out by ending iteration; FastMCP's
    # cancellation propagates here via asyncio.CancelledError.
    queue = deps.stream_registry.queue_for(subscription_id)
    try:
        while True:
            event = await queue.get()
            yield event
    except asyncio.CancelledError:
        # Normal stream-end: agent disconnected. Bubble up so the FastMCP
        # transport cleans up; the queue persists for the next reconnect.
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_subscription_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project an active-subscription reader row to the MCP response shape."""
    return {
        "subscription_id": str(row.get("subscription_id") or ""),
        "agent_id": str(row.get("agent_id") or ""),
        "filter": dict(row.get("filter") or {}),
        "transport": str(row.get("transport") or ""),
        "webhook_url": row.get("webhook_url"),
        "description": row.get("description"),
        "created_seq": int(row.get("created_seq") or 0),
    }


async def _replay_delivered(
    *,
    ledger: Any,
    company_id: UUID,
    subscription_id: str,
    since_seq: int,
) -> list[dict[str, Any]]:
    """Return ``agent_event_delivered`` events for this subscription with
    ``triggering_entry_seq > since_seq``, oldest-first.

    Used by ``stream_subscription`` for resumption. The replay shape matches
    the live-tail event payload — agents process them uniformly.
    """
    entries = await ledger.fetch(company_id)
    out: list[dict[str, Any]] = []
    for e in entries:
        if e.get("kind") != "execute":
            continue
        payload = e.get("payload") or {}
        if payload.get("tool") != "emit_agent_event_delivered":
            continue
        args = payload.get("args") or {}
        if str(args.get("subscription_id") or "") != subscription_id:
            continue
        try:
            triggering_seq = int(args.get("triggering_entry_seq") or 0)
        except (TypeError, ValueError):
            continue
        if triggering_seq <= since_seq:
            continue
        out.append({
            "subscription_id": subscription_id,
            "triggering_entry_seq": triggering_seq,
            "kind": str(args.get("triggering_entry_kind") or ""),
            "delivery_status": str(args.get("delivery_status") or ""),
            "replay": True,
        })
    return out


__all__ = [
    "SubscriptionCreateResponse",
    "SubscriptionDeniedResponse",
    "SubscriptionListResponse",
    "SubscriptionRevokeResponse",
    "SubscriptionToolDeps",
    "create_subscription",
    "list_subscriptions",
    "revoke_subscription",
    "stream_subscription",
]
