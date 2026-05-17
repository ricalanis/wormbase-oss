"""Integration tests — SseStreamTransport streaming-path contract (post-rest #2).

Path #2 of the post-rest final wave (2026-05-13): pin the SSE streaming
branch's behavior at the **transport** level, independent of FastMCP's
tool runner. The existing files
:mod:`test_subscription_stream_sse` and
:mod:`test_subscription_stream_sse_diagnostics` cover the probe + env-knob
+ degrade-to-list-mode + boot-log surfaces; this file fills the
remaining transport-level contract:

  * Multi-event yield ordering through ``_wrap_stream``.
  * Resumption-then-live-tail interaction when the generator carries
    both replay events and live-queue events through the transport.
  * Disconnect cleanup — closing the async iterator early raises
    GeneratorExit through the wrapper without resource leak; the
    underlying generator's CancelledError handler bubbles up correctly.
  * since_seq filter honored at the generator level — pre-filtered events
    flow through the transport unchanged.
  * Empty-stream behavior — no events yielded; the iterator terminates.
  * subscription_id stamping never overwrites a generator-supplied
    subscription_id (defensive idempotence).
  * Wave 4 invariant: the transport never inspects TenantContext;
    tenant capture is an upstream concern. Pinning this absence keeps
    future refactors honest about where auth lives.

Why drive the transport directly rather than via the FastMCP Client?
FastMCP 3.2.4's tool runner materializes async generators into lists
at ``function_tool.py:_materialize_generator``, so a round-trip through
``Client.call_tool`` always returns a list — masking the
yield-one-at-a-time semantics of the SSE branch. Driving the transport
directly with a mocked probe is the only way to pin the contract that
will activate when a future FastMCP grows true streaming-tool support.

When FastMCP grows that support and the probe flips True automatically
(feature detection in :func:`fastmcp_streaming_probe_diagnosis`), these
tests will continue to pass — they exercise the same branch the
production path will take. No code change in stream_transport.py is
required to flip the streaming on; this file pins that contract.

Path 3 of the v2.A overnight roadmap shipped the SseStreamTransport
skeleton; post-rest #2 augments it with these contract tests so the
probe-flip-day deployment is risk-free.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.stream_transport import (
    SseStreamTransport,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _streaming_probe_true():
    """Context manager that flips the probe to True for the duration."""
    return patch(
        "wormbase_agent_gateway.subscriptions.stream_transport."
        "fastmcp_supports_streaming_tools",
        return_value=True,
    )


async def _drain(result: Any) -> list[dict[str, Any]]:
    """Drain an async iterator returned by SseStreamTransport.deliver()."""
    events: list[dict[str, Any]] = []
    async for ev in result:
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Multi-event yield ordering
# ---------------------------------------------------------------------------


async def test_sse_path_yields_multiple_events_in_generator_order():
    """Three events from the generator → three yields in the same order.

    The transport must not reorder, drop, or coalesce yields. Each
    event flows through ``_wrap_stream`` unchanged (modulo
    subscription_id stamping, which is tested separately).
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-multi-event"

    async def gen():
        yield {"subscription_id": sub_id, "triggering_entry_seq": 10, "kind": "a"}
        yield {"subscription_id": sub_id, "triggering_entry_seq": 11, "kind": "b"}
        yield {"subscription_id": sub_id, "triggering_entry_seq": 12, "kind": "c"}

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    assert [e["triggering_entry_seq"] for e in events] == [10, 11, 12]
    assert [e["kind"] for e in events] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Resumption-then-live-tail interaction
# ---------------------------------------------------------------------------


async def test_sse_path_replay_then_live_events_in_order():
    """Generator yields replay events first, then live-queue events.

    Mirrors the production ``stream_subscription`` generator shape:
    ledger-replay events with ``replay=True`` flow through first, then
    live queue events stream after. The transport must yield both in
    encounter-order without merging or sorting.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-replay-then-live"

    async def gen():
        # Replay phase — entries from ledger lookup.
        yield {
            "subscription_id": sub_id,
            "triggering_entry_seq": 100,
            "kind": "bad_pattern_proposed",
            "replay": True,
        }
        yield {
            "subscription_id": sub_id,
            "triggering_entry_seq": 101,
            "kind": "bad_pattern_proposed",
            "replay": True,
        }
        # Live-tail phase — entries from queue.
        yield {
            "subscription_id": sub_id,
            "triggering_entry_seq": 200,
            "kind": "bad_pattern_proposed",
        }

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    assert len(events) == 3
    assert [e["triggering_entry_seq"] for e in events] == [100, 101, 200]
    # Replay events keep their replay marker; live events don't have it.
    assert events[0].get("replay") is True
    assert events[1].get("replay") is True
    assert "replay" not in events[2]


# ---------------------------------------------------------------------------
# since_seq filter honored upstream
# ---------------------------------------------------------------------------


async def test_sse_path_passes_through_since_seq_filtered_events():
    """Generator pre-filters by since_seq; transport yields what remains.

    The since_seq cutoff is enforced inside
    :func:`stream_subscription` (the generator producer) — by the time
    events reach the transport they've already been filtered. This
    test pins that the transport never re-checks the cutoff or
    re-introduces dropped events: it's a pure pass-through for
    semantics it doesn't own.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-since-seq"

    # Producer yields ONLY entries with triggering_entry_seq > 50.
    # (Entries with seq <= 50 would have been dropped by the
    # _replay_delivered call in stream_subscription.)
    async def gen():
        for seq in (51, 52, 60, 99):
            yield {
                "subscription_id": sub_id,
                "triggering_entry_seq": seq,
                "kind": "x",
                "replay": True,
            }

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    # All four pass through.
    assert [e["triggering_entry_seq"] for e in events] == [51, 52, 60, 99]
    # No <=50 entries appear in the output (the filter happens upstream).
    assert all(e["triggering_entry_seq"] > 50 for e in events)


# ---------------------------------------------------------------------------
# Empty stream
# ---------------------------------------------------------------------------


async def test_sse_path_empty_stream_terminates_cleanly():
    """A generator that yields nothing produces a clean empty iterator.

    Edge case: an empty replay + an empty live-queue at the moment of
    stream-open. The async iterator terminates without raising; the
    caller drains an empty list.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-empty"

    async def gen():
        # Equivalent to a generator that immediately exits — no events.
        if False:  # pragma: no cover — intentionally unreachable
            yield {}
        return

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    assert events == []


# ---------------------------------------------------------------------------
# Disconnect cleanup
# ---------------------------------------------------------------------------


async def test_sse_path_aclose_propagates_to_underlying_generator():
    """aclose() on the wrapper terminates the underlying generator cleanly.

    The disconnect path: caller-side code calls ``aclose()`` on the
    iterator (FastMCP's tool runner does this on client disconnect).
    The wrapper's ``async for`` over the underlying generator must
    propagate GeneratorExit / CancelledError back to the producer's
    cleanup paths.

    We assert via a counter that the producer's ``finally`` block ran
    — the canonical signal that the generator was cleaned up rather
    than abandoned.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-disconnect"

    finalized = {"hit": False}

    async def gen():
        try:
            yield {"subscription_id": sub_id, "triggering_entry_seq": 1}
            yield {"subscription_id": sub_id, "triggering_entry_seq": 2}
            yield {"subscription_id": sub_id, "triggering_entry_seq": 3}
        finally:
            finalized["hit"] = True

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        # Consume one event then close — simulates a client disconnect
        # after the first message.
        first = await result.__anext__()
        await result.aclose()

    assert first["triggering_entry_seq"] == 1
    assert finalized["hit"] is True, (
        "underlying generator's finally block must run when the SSE "
        "wrapper is aclose()'d — otherwise queue subscriptions leak"
    )


async def test_sse_path_cancellederror_in_producer_propagates():
    """When the producer raises CancelledError, the wrapper re-raises it.

    The production ``stream_subscription`` generator catches
    ``asyncio.CancelledError`` and re-raises so FastMCP's transport
    cleans up. The SSE wrapper must propagate that — never swallow it
    into an empty iterator or convert it to a different exception.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-cancel"

    async def gen():
        yield {"subscription_id": sub_id, "triggering_entry_seq": 1}
        raise asyncio.CancelledError()

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events: list[dict[str, Any]] = []
        with pytest.raises(asyncio.CancelledError):
            async for ev in result:
                events.append(ev)

    # The pre-cancel event still flowed through.
    assert len(events) == 1
    assert events[0]["triggering_entry_seq"] == 1


# ---------------------------------------------------------------------------
# subscription_id stamping is non-destructive
# ---------------------------------------------------------------------------


async def test_sse_path_does_not_overwrite_existing_subscription_id():
    """When the generator supplies subscription_id, the wrapper leaves it alone.

    Defensive idempotence: the producer normally supplies subscription_id
    on every event (replay + live both stamp it). The wrapper's
    ``if "subscription_id" not in ev`` guard exists for the edge case
    where a future event shape omits it. This test pins that pre-stamped
    events are NOT re-stamped — the wrapper isn't a mutation surface.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-stamp-collision"
    upstream_supplied_id = "sub-original-different"

    async def gen():
        # Generator carries a DIFFERENT subscription_id than the deliver
        # call. This is a contrived case; in production they always match.
        # The test pins that the wrapper trusts the producer.
        yield {
            "subscription_id": upstream_supplied_id,
            "triggering_entry_seq": 1,
        }

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    assert len(events) == 1
    # Producer-supplied id preserved; wrapper did not overwrite.
    assert events[0]["subscription_id"] == upstream_supplied_id


async def test_sse_path_stamps_subscription_id_when_absent():
    """When the generator omits subscription_id, the wrapper stamps it.

    Mirror of the test in :mod:`test_subscription_stream_sse`
    (``test_sse_transport_wraps_events_without_subscription_id``) at
    multi-event scale. Pins that the stamping happens per-event, not
    once-and-cached — events that arrive after a stamped one continue
    to be stamped independently.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-stamp-multi"

    async def gen():
        # First event missing subscription_id, second already has it,
        # third missing again. Pin that the wrapper handles each
        # independently.
        yield {"triggering_entry_seq": 1, "kind": "a"}
        yield {
            "subscription_id": sub_id,
            "triggering_entry_seq": 2,
            "kind": "b",
        }
        yield {"triggering_entry_seq": 3, "kind": "c"}

    with _streaming_probe_true():
        result = await transport.deliver(
            subscription_id=sub_id, generator=gen(), stream_registry=registry,
        )
        events = await _drain(result)

    assert len(events) == 3
    # All three carry subscription_id (stamped or pre-existing).
    assert all(e["subscription_id"] == sub_id for e in events)
    assert [e["triggering_entry_seq"] for e in events] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Wave 4 invariant — transport does not touch tenancy
# ---------------------------------------------------------------------------


async def test_sse_path_transport_signature_excludes_tenant_context():
    """``SseStreamTransport.deliver`` does not accept TenantContext.

    Per Wave 4 doctrine (Path 4 close-out), TenantContext + rate-limit +
    auth are resolved ONCE at stream-open, upstream of the transport.
    The transport sees an already-authorized generator and a registry;
    it is a pure-mechanism component, not an auth boundary.

    Pinning the signature here guards against well-meaning future
    refactors that try to "push auth into the transport" — that would
    invert the layering and break the per-event-rate-limit anti-pattern
    Wave 4 closed out.
    """
    import inspect

    sig = inspect.signature(SseStreamTransport.deliver)
    param_names = set(sig.parameters.keys())
    # Expected params: self + subscription_id + generator + stream_registry.
    assert param_names == {"self", "subscription_id", "generator", "stream_registry"}, (
        f"SseStreamTransport.deliver signature changed unexpectedly; "
        f"got params {param_names}. Auth/tenant capture is a layer above "
        f"the transport — see Wave 4 close-out doctrine."
    )


async def test_sse_path_transport_does_not_import_tenant_context():
    """The stream_transport module does not import TenantContext.

    Same Wave 4 invariant from the module-namespace angle: if a future
    refactor accidentally pulls TenantContext into stream_transport.py,
    this fails fast. Keeps the layering crisp: tenancy is upstream of
    the transport.
    """
    import wormbase_agent_gateway.subscriptions.stream_transport as st_mod

    # The module's public surface should not reference TenantContext.
    assert "TenantContext" not in st_mod.__all__
    # And it shouldn't be in module globals either (i.e., not imported).
    assert "TenantContext" not in vars(st_mod)


# ---------------------------------------------------------------------------
# Probe-False fall-through — pins the gate stays gated
# ---------------------------------------------------------------------------


async def test_sse_path_falls_back_to_list_mode_when_probe_false():
    """When the probe is False, deliver() returns a list-mode dict.

    Today's FastMCP (3.2.4 + 3.3.0b2) has the probe at False; the
    transport degrades to list-mode and produces the v2.A external
    contract (``{subscription_id, events: [...]}``). This pins that
    path #2's streaming branch stays gated — flipping the env knob
    alone does NOT activate SSE; only the probe flipping (driven by
    feature detection on a future FastMCP) does.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-probe-false"

    async def gen():
        yield {"subscription_id": sub_id, "triggering_entry_seq": 7}

    # Do NOT patch the probe — use the real one, which returns False
    # today. Result must be a list-mode dict, not an async iterator.
    result = await transport.deliver(
        subscription_id=sub_id, generator=gen(), stream_registry=registry,
    )

    assert isinstance(result, dict)
    assert set(result.keys()) == {"subscription_id", "events"}
    assert result["subscription_id"] == sub_id
    assert len(result["events"]) == 1
    assert result["events"][0]["triggering_entry_seq"] == 7
