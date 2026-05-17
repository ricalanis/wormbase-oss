"""Wave 2 Task 4 — AgentID boundary-conversion + agent_tool_reasoning route.

These tests pin the Phase 0 §7 finding: ``RouteRequest.requested_by``
STAYS a ``str = "unknown"`` at the dataclass boundary; the conversion
to :class:`AgentID` happens INSIDE the router (at the audit-emission
site) via :meth:`AgentID.from_legacy_string`. Retyping the field
directly is blocked by ``frozen=True, slots=True`` — the S6 spike
proved this and the design accommodates it.
"""
from __future__ import annotations

from wormbase_inference import AgentID, RouteRequest, default_backend


def test_agent_id_type_exists_and_wraps_str() -> None:
    """AgentID is a frozen wrapper over ``str`` exported at the public surface."""
    agent_id = AgentID(value="agent-123")
    assert agent_id.value == "agent-123"


def test_agent_id_from_legacy_string_round_trips() -> None:
    """``from_legacy_string`` is the boundary-conversion entry point.

    The router calls this inside ``CachedRouter.call`` before emitting
    ``inference_served`` — every existing internal caller keeps passing
    a plain ``str`` and the conversion happens at the boundary.
    """
    legacy = "worm:chat_presence"
    agent_id = AgentID.from_legacy_string(legacy)
    assert agent_id.value == legacy
    assert agent_id == AgentID(value=legacy)


def test_route_request_requested_by_stays_str_at_dataclass_boundary() -> None:
    """RouteRequest.requested_by remains ``str = 'unknown'`` per Phase 0 §7.

    ``slots=True + frozen=True`` blocks ``__post_init__`` coercion to
    AgentID. Conversion to AgentID happens INSIDE the router at the
    inference_served emission site, NOT at RouteRequest construction.
    """
    req = RouteRequest(call_type="reasoning")
    assert req.requested_by == "unknown"
    assert isinstance(req.requested_by, str)

    req2 = RouteRequest(call_type="reasoning", requested_by="worm:chat_presence")
    assert req2.requested_by == "worm:chat_presence"
    assert isinstance(req2.requested_by, str)
    # Not an AgentID — type stayed str at the dataclass boundary.
    assert not isinstance(req2.requested_by, AgentID)


def test_default_backend_routes_agent_tool_reasoning_to_kimi() -> None:
    """Wave 2 added ``agent_tool_reasoning`` (Kimi) and ``embed_query`` (Gemma).

    MCP-tool reasoning goes to Kimi (frontier reasoning, low-volume,
    high-stakes); query embeddings go to Gemma (commodity workload on
    the owned VLAN endpoint).
    """
    assert default_backend("agent_tool_reasoning") == "kimi"
    assert default_backend("embed_query") == "gemma"
