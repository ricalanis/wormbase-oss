"""In-memory per-subscription async queue registry for the ``mcp_stream`` transport.

The ``SubscriptionDispatcher`` Reactivity hands events for ``mcp_stream``
subscriptions to a :class:`StreamRegistry`. The FastMCP ``agent.subscriptions.stream``
tool reads from the same registry as an SSE-style long-poll consumer.

Two-axis design:

  * **Per-subscription queue** — each ``subscription_id`` gets its own
    ``asyncio.Queue`` (maxsize 1000). When the consumer disconnects, the
    queue persists so a reconnect can drain stale events; the resumption
    path in the stream tool prefers ledger-replay over queue-drain so
    queues primarily serve the live-tail mode.
  * **Bounded overflow** — when the queue is full and a new event arrives,
    the OLDEST event is dropped (so the freshest events always reach a
    just-reconnecting consumer) and a warning is logged. The dispatch
    Reactivity still records ``agent_event_delivered`` with
    ``delivery_status="delivered"`` — overflow is a consumer-side data
    loss, not a delivery failure (delivery means "we put it on the
    queue").

The registry is process-local; in v2.A the agent-gateway runs single-process
per install so there is no shared-queue concern. Multi-process / multi-pod
deploys are a v2.B+ concern (Redis-backed queue or similar).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("wormbase_agent_gateway.subscriptions.stream_registry")


_DEFAULT_MAXSIZE: int = 1000


class StreamRegistry:
    """Per-subscription in-memory event queue map.

    Thread-safety: methods are async but the underlying dict mutations
    happen synchronously on the event loop. Single-loop-per-process
    is the assumed deploy posture; cross-loop usage requires external
    synchronization (out of scope for v2.A).
    """

    def __init__(self, *, maxsize: int = _DEFAULT_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    def queue_for(self, subscription_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Return the queue for ``subscription_id``, creating it lazily."""
        q = self._queues.get(subscription_id)
        if q is None:
            q = asyncio.Queue(maxsize=self._maxsize)
            self._queues[subscription_id] = q
        return q

    async def push(self, subscription_id: str, event: dict[str, Any]) -> None:
        """Enqueue an event. On overflow, drop the oldest and log a warning.

        Returns ``None`` regardless of overflow — the dispatcher treats
        successful enqueue (with possible drop) as ``delivery_status=delivered``.
        Queue-overflow is consumer slowness, not dispatcher failure.
        """
        q = self.queue_for(subscription_id)
        if q.full():
            try:
                dropped = q.get_nowait()
                logger.warning(
                    "StreamRegistry queue full for subscription_id=%s; "
                    "dropped oldest event=%r",
                    subscription_id,
                    {
                        "triggering_entry_seq": dropped.get(
                            "triggering_entry_seq",
                        ),
                        "kind": dropped.get("kind"),
                    },
                )
            except asyncio.QueueEmpty:  # pragma: no cover — race
                pass
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:  # pragma: no cover — drained above
            pass

    def size(self, subscription_id: str) -> int:
        """Current queue depth — used by stream-tool tests + observability."""
        q = self._queues.get(subscription_id)
        if q is None:
            return 0
        return q.qsize()

    def clear(self, subscription_id: str) -> None:
        """Drop the queue for ``subscription_id``.

        Called by ``agent.subscriptions.revoke`` after writing the
        revocation entry — the live queue is no longer interesting.
        """
        self._queues.pop(subscription_id, None)


__all__ = ["StreamRegistry"]
