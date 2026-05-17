"""Agent event subscription primitives (v2.A agent-as-teammate).

Public surface for the subscription dispatcher pipeline. v2.A Batch A
shipped the foundation layer (filter + webhook transport). Batch B
adds the dispatcher Reactivity + per-subscription stream registry
that compose on top.

The layer split stays useful: filter + transport are pure (no I/O
state, no substrate dependency); the dispatcher composes them with
a subscription reader and the ledger.
"""

from __future__ import annotations

from wormbase_agent_gateway.subscriptions.dispatcher import (
    SubscriptionDispatcher,
    SubscriptionDispatcherDeps,
    SubscriptionReader,
    make_subscription_dispatcher_reactivity,
)
from wormbase_agent_gateway.subscriptions.filter import (
    AgentEventFilter,
    compile_filter,
    deserialize_filter,
    serialize_filter,
)
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.stream_transport import (
    ListModeTransport,
    SseStreamTransport,
    StreamTransport,
    build_stream_transport_from_env,
    fastmcp_supports_streaming_tools,
    is_sse_transport_enabled,
)
from wormbase_agent_gateway.subscriptions.transports import (
    WebhookDeliveryResult,
    WebhookTransport,
    sign_body,
    verify_signature,
)

__all__ = [
    "AgentEventFilter",
    "ListModeTransport",
    "SseStreamTransport",
    "StreamRegistry",
    "StreamTransport",
    "SubscriptionDispatcher",
    "SubscriptionDispatcherDeps",
    "SubscriptionReader",
    "WebhookDeliveryResult",
    "WebhookTransport",
    "build_stream_transport_from_env",
    "compile_filter",
    "deserialize_filter",
    "fastmcp_supports_streaming_tools",
    "is_sse_transport_enabled",
    "make_subscription_dispatcher_reactivity",
    "serialize_filter",
    "sign_body",
    "verify_signature",
]
