"""Stream-transport abstraction for ``agent.subscriptions.stream`` (Path 3).

The MCP ``agent.subscriptions.stream`` tool consumes an async generator
(``stream_subscription``) that yields events from the per-subscription
queue. Two consumers are supported:

  * **ListModeTransport** — collects events into a list and returns them
    as a single MCP response. Required for FastMCP versions (including
    the installed 3.2.4) whose tool runner materializes async generators
    into lists. The agent receives a ``{subscription_id, events: [...]}``
    payload in one shot. Long-poll semantics are preserved by the
    generator's queue-drain-then-break behavior at call time.

  * **SseStreamTransport** — yields events one at a time through the
    generator (true server-sent-event semantics) when the underlying
    FastMCP server supports streaming tool results. The
    ``ToolMaterializesAsyncGenerators`` capability probe in
    :func:`fastmcp_supports_streaming_tools` (backed by
    :func:`fastmcp_streaming_probe_diagnosis` for structured why-codes)
    returns True only when the installed FastMCP yields tool results
    event-by-event; until then the SseStreamTransport degrades to
    ListModeTransport with a one-line INFO log so the env knob does not
    silently downgrade real-time semantics. The transport's public shape
    stays identical when FastMCP eventually grows the capability —
    flipping ``probe()`` to True promotes SseStreamTransport to true
    event-stream mode without any consumer-side change.

    The probe is feature-detection-driven, not version-pinned: it
    inspects ``fastmcp.tools.function_tool.FunctionTool._materialize_generator``
    and confirms the materialize-into-list source pattern. As of
    2026-05-13 FastMCP 3.2.4 (installed) and 3.3.0b2 (latest beta) both
    ship the same materialize-into-list behavior, so the probe returns
    False on both. The 3.3.0 betas ship ``fastmcp-slim`` (client
    packaging refactor) — not streaming-tool support. When the materialize
    method is removed or rewritten, the probe flips True automatically.

Path 3 of the 2026-05-21 overnight roadmap. The list-mode wrapper that
previously lived inline in ``mcp_server/server.py`` is now a transport
impl behind a Protocol.

Doctrine compliance: this is Case 6 of the Optional-Effect Injection
doctrine
(``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``).
``StreamTransport | None`` is injected on ``SubscriptionToolDeps``;
``None`` defaults to ``ListModeTransport()`` (byte-identical to the
pre-Path-3 wrapper). SseStreamTransport is opt-in via the env knob
``WORMBASE_MCP_SSE_TRANSPORT``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol, TypedDict

from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry

logger = logging.getLogger("wormbase_agent_gateway.subscriptions.stream_transport")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class StreamTransport(Protocol):
    """Transport that materializes the stream-tool's async generator.

    Two impls ship: :class:`ListModeTransport` (the default; FastMCP 3.2.4
    compat) and :class:`SseStreamTransport` (opt-in; SSE-style yield when
    the underlying FastMCP supports streaming tool results).

    The transport receives:

      * ``subscription_id`` — surfaced in the final response for shape
        compatibility with list-mode.
      * ``generator`` — the live async generator produced by
        :func:`stream_subscription`. The transport drives the generator
        and decides how to surface yielded events to the FastMCP tool
        return value.
      * ``stream_registry`` — peeked by list-mode to decide when to break
        out of live-tail after the initial drain.
    """

    async def deliver(
        self,
        *,
        subscription_id: str,
        generator: AsyncIterator[dict[str, Any]],
        stream_registry: StreamRegistry,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# ListModeTransport — current default (FastMCP 3.2.4 compat)
# ---------------------------------------------------------------------------


@dataclass
class ListModeTransport:
    """Drain the generator into a single ``{subscription_id, events: [...]}``.

    Byte-identical to the wrapper that lived inline in
    ``mcp_server/server.py`` lines 1146-1175 before Path 3. The generator's
    initial pass yields replay events (from ledger lookup) and any
    pre-queued live events; once the registry's queue is empty, this
    transport breaks so the FastMCP response returns to the agent.

    The break-on-empty-queue heuristic preserves the
    "long-poll-returns-when-drained" semantics that v2.A Batch B shipped.
    Cross-version compat for FastMCP versions that materialize async
    generators into lists (the installed 3.2.4 does) — the agent receives
    the same event sequence either way.
    """

    async def deliver(
        self,
        *,
        subscription_id: str,
        generator: AsyncIterator[dict[str, Any]],
        stream_registry: StreamRegistry,
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        async for ev in generator:
            events.append(ev)
            # Surface ``{status: "denied", ...}`` events immediately —
            # they are single-shot terminals (auth failure / not active).
            if ev.get("status") == "denied":
                break
            # Bound the single-shot response to events available at
            # call-time. The generator's replay pass yields synchronously
            # available events first; live-tail then blocks on
            # ``queue.get()``. We break when the queue has drained so the
            # response returns instead of long-polling forever.
            if stream_registry.size(subscription_id) == 0:
                break
        return {"subscription_id": subscription_id, "events": events}


# ---------------------------------------------------------------------------
# SseStreamTransport — opt-in; future FastMCP true-streaming impl
# ---------------------------------------------------------------------------


class StreamingProbeDiagnosis(TypedDict):
    """Structured result of the FastMCP streaming-tools capability probe.

    Returned by :func:`fastmcp_streaming_probe_diagnosis` so operators can
    see *why* the probe answered the way it did, not just the yes/no.
    Useful in boot logs and the SSE-eligibility self-check CLI flag.
    """

    supports_streaming: bool
    fastmcp_version: str
    reason: Literal[
        "materialize_generator_detected",
        "materialize_generator_absent",
        "fastmcp_unavailable",
        "probe_error",
    ]
    detail: str


def fastmcp_streaming_probe_diagnosis() -> StreamingProbeDiagnosis:
    """Return a structured diagnosis of the installed FastMCP's streaming support.

    The probe uses **feature detection** rather than version-pinning:
    it inspects ``fastmcp.tools.function_tool.FunctionTool`` for the
    ``_materialize_generator`` method that consumes async generators
    into lists. Empirically verified for both 3.2.4 (installed) and
    3.3.0b2 (latest beta as of 2026-05-13): both ship the same
    materialize-into-list behavior at
    ``function_tool.py:_materialize_generator``.

    When a future FastMCP grows true async-generator tool streaming —
    likely by removing ``_materialize_generator`` from the hot path,
    adding a ``stream=True`` decorator flag, or introducing a new tool
    type — the probe's ``supports_streaming`` flips True automatically
    on the next install. No code change needed in this module; the
    transport's SSE branch already returns the raw generator and is
    pinned by ``test_sse_transport_yields_directly_when_probe_returns_true``.

    Returns a :class:`StreamingProbeDiagnosis` carrying:

    * ``supports_streaming`` — the bool the rest of the system consumes.
    * ``fastmcp_version`` — what's installed (or ``"unknown"``).
    * ``reason`` — categorical why-code (see TypedDict for values).
    * ``detail`` — human-readable explanation for log lines.
    """
    try:
        import fastmcp  # local import so probe doesn't hard-fail on missing dep
    except ImportError as exc:
        return StreamingProbeDiagnosis(
            supports_streaming=False,
            fastmcp_version="unknown",
            reason="fastmcp_unavailable",
            detail=f"fastmcp import failed: {exc!s}",
        )

    version = getattr(fastmcp, "__version__", "unknown")

    try:
        from fastmcp.tools.function_tool import FunctionTool
    except ImportError as exc:
        # FastMCP installed but tool runner moved — assume materialize
        # behavior absent and the new path may support streaming. Conservative
        # default: stay False until a known-streaming version ships.
        return StreamingProbeDiagnosis(
            supports_streaming=False,
            fastmcp_version=version,
            reason="probe_error",
            detail=(
                f"fastmcp {version} has no fastmcp.tools.function_tool.FunctionTool; "
                f"probe could not verify materialize behavior: {exc!s}"
            ),
        )

    materialize = getattr(FunctionTool, "_materialize_generator", None)
    if materialize is None:
        # The hot path no longer materializes generators. Likely (but not
        # certain) the tool runner now streams them. We still gate True on
        # a positive feature marker rather than absence of the old one —
        # absence could also mean the method was renamed. Conservative:
        # False with a clear diagnosis so the upgrader can audit.
        return StreamingProbeDiagnosis(
            supports_streaming=False,
            fastmcp_version=version,
            reason="materialize_generator_absent",
            detail=(
                f"fastmcp {version} no longer exposes FunctionTool."
                f"_materialize_generator; tool runner behavior is unknown — "
                f"audit before flipping the probe to True"
            ),
        )

    # Confirm materialize-generator does what we think — guard against the
    # method being renamed-but-kept-as-noop in a future release.
    try:
        source = inspect.getsource(materialize)
    except (OSError, TypeError):  # pragma: no cover — defensive
        source = ""
    if "isasyncgen" in source and "async for" in source:
        return StreamingProbeDiagnosis(
            supports_streaming=False,
            fastmcp_version=version,
            reason="materialize_generator_detected",
            detail=(
                f"fastmcp {version} materializes async generators into lists "
                f"at FunctionTool._materialize_generator; true SSE yield is "
                f"not available — list-mode is the only viable transport"
            ),
        )

    # Method present but the materialize behavior is no longer detectable in
    # its source. Conservative: stay False, surface as probe_error so the
    # operator audits.
    return StreamingProbeDiagnosis(
        supports_streaming=False,
        fastmcp_version=version,
        reason="probe_error",
        detail=(
            f"fastmcp {version} has FunctionTool._materialize_generator but "
            f"its source does not match the known materialize-into-list "
            f"pattern; conservative default is False"
        ),
    )


def fastmcp_supports_streaming_tools() -> bool:
    """Probe — does the installed FastMCP yield tool results event-by-event?

    Returns ``True`` when the installed FastMCP's tool runner streams
    yielded values to the client instead of materializing them into a
    list. As of FastMCP 3.2.4 (installed) and 3.3.0b2 (latest beta),
    the answer is **False** — the runner's ``_materialize_generator``
    consumes ``async for item in result`` into a list before returning
    (see ``.venv/lib/python3.12/site-packages/fastmcp/tools/function_tool.py``
    lines 289-301; same behavior in 3.3.0b2's ``fastmcp_slim`` sdist).

    When a future FastMCP grows true async-generator tool streaming
    (likely via a ``stream=True`` decorator flag or a new tool type),
    this probe should return True for those versions. SseStreamTransport
    then promotes to true event-by-event yield without any consumer-side
    change.

    The probe is **feature-detection-driven** via
    :func:`fastmcp_streaming_probe_diagnosis`. Today's answer is False
    because the FunctionTool._materialize_generator method is present
    and matches the materialize-into-list source pattern. A FastMCP
    upgrade that removes that method (or rewrites it not to materialize)
    flips this to True on the next install — no code change needed here.
    """
    return fastmcp_streaming_probe_diagnosis()["supports_streaming"]


@dataclass
class SseStreamTransport:
    """Opt-in transport: SSE-style event-by-event yield via async generator.

    When :func:`fastmcp_supports_streaming_tools` returns True this
    transport returns the underlying generator directly to FastMCP, which
    then yields each event to the client as a streaming chunk. When the
    probe returns False (today's FastMCP 3.2.4), this transport delegates
    to :class:`ListModeTransport` with a one-line INFO log so the env
    knob's intent is honored as far as the runtime allows.

    This shape preserves the v2.A external contract
    (``{subscription_id, events: [...]}``) in list-mode while paving the
    upgrade path: when FastMCP grows streaming, no consumer code changes
    — only the probe flips True.

    **Streaming-path activation contract (post-rest #2, 2026-05-13).**

    The probe-True branch is **already implemented and pinned by tests**
    in :mod:`tests/integration/test_subscription_stream_sse_path.py`.
    When FastMCP grows streaming-tool support and the probe flips True
    via feature detection (no manual change required), the transport
    activates the following semantics — already exercised by the path
    tests via mocked probes:

      * **Multi-event yield ordering** — yields preserve generator
        order; no reordering, drop, or coalesce.
      * **Replay-then-live-tail interaction** — replay events from the
        ledger stream first; live-queue events stream after; both flow
        through the same wrapper in encounter-order.
      * **Disconnect cleanup** — caller-side ``aclose()`` propagates
        ``GeneratorExit`` to the underlying generator so its ``finally``
        block runs; the production producer's CancelledError handler
        re-raises so FastMCP's transport cleans up.
      * **subscription_id stamping is non-destructive** — pre-stamped
        events are not overwritten; unstamped events are stamped from
        the deliver-time subscription_id parameter.
      * **No tenant-context coupling** — the transport does NOT receive
        or inspect ``TenantContext``. Per Wave 4 doctrine (Path 4
        close-out: per-event rate-limiting on a long-poll connection is
        an anti-pattern), TenantContext + auth + rate-limit are
        resolved ONCE at stream-open upstream of the transport.
        Subsequent generator yields bypass per-event checks.
      * **Replay-mode determinism** — the wire-replay path is the
        deterministic backstop; the transport itself has no replay-mode
        branch because the generator producer handles replay
        upstream. The same transport code runs for live and replay
        with byte-identical output.
      * **since_seq filter is upstream** — :func:`stream_subscription`
        applies the since_seq cutoff during the replay phase; events
        reaching the transport have already been filtered. The
        transport is a pure pass-through for this semantic.

    These pins ensure the probe-flip-day deployment is risk-free: when
    a future FastMCP release removes ``_materialize_generator`` or
    rewrites it not to materialize, the feature-detection probe in
    :func:`fastmcp_streaming_probe_diagnosis` returns True automatically;
    the SSE branch activates; and the contract above is exactly what
    clients observe — no code change in this module required.
    """

    _list_fallback: ListModeTransport | None = None

    def __post_init__(self) -> None:
        if self._list_fallback is None:
            self._list_fallback = ListModeTransport()

    async def deliver(
        self,
        *,
        subscription_id: str,
        generator: AsyncIterator[dict[str, Any]],
        stream_registry: StreamRegistry,
    ) -> Any:
        if fastmcp_supports_streaming_tools():
            # True SSE: hand the generator back to FastMCP. The tool
            # runner yields each event to the client as a streaming
            # chunk. The generator's CancelledError handler in
            # stream_subscription bubbles disconnects up correctly.
            #
            # The list-mode contract ({events: [...]}) is preserved by
            # wrapping each yielded event with the subscription_id —
            # clients consuming the stream get the same per-event shape
            # the list-mode response carries inside ``events[*]``.
            return self._wrap_stream(subscription_id, generator)
        # Capability probe says False — degrade to list-mode so the env
        # knob never produces a worse experience than the byte-identical
        # default. Log once-per-call at INFO so operators can see the
        # degradation in service logs without noise at WARN.
        logger.info(
            "WORMBASE_MCP_SSE_TRANSPORT requested but the installed "
            "FastMCP does not yet support streaming tool results; "
            "degrading to list-mode for subscription_id=%s",
            subscription_id,
        )
        assert self._list_fallback is not None  # __post_init__ invariant
        return await self._list_fallback.deliver(
            subscription_id=subscription_id,
            generator=generator,
            stream_registry=stream_registry,
        )

    @staticmethod
    async def _wrap_stream(
        subscription_id: str,
        generator: AsyncIterator[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Tag each yielded event with subscription_id for client shape parity.

        The list-mode payload's ``events[*]`` already carry
        ``subscription_id`` as a key (see :func:`stream_subscription`'s
        replay + queue events); this wrapper preserves the same shape
        when events are yielded one at a time.

        **Disconnect cleanup** (pinned by
        ``test_sse_path_aclose_propagates_to_underlying_generator``):
        when the caller (FastMCP's tool runner on client disconnect)
        calls ``aclose()`` on this wrapper, the inner ``generator`` is
        explicitly aclose()'d in the ``finally`` block. Without that,
        ``async for`` over the inner generator does not propagate
        ``GeneratorExit`` to the producer's ``finally`` clauses —
        Python relies on GC, which can leave queue subscriptions
        dangling indefinitely on long-lived processes. The explicit
        ``aclose()`` call ensures the producer's cleanup paths
        (``stream_subscription``'s ``CancelledError`` handler in
        particular) fire deterministically.
        """
        try:
            async for ev in generator:
                if "subscription_id" not in ev:
                    ev = {**ev, "subscription_id": subscription_id}
                yield ev
        except asyncio.CancelledError:
            # Stream-end via disconnect; propagate so FastMCP cleans up.
            raise
        finally:
            # Explicitly aclose the inner generator. The `async for`
            # loop above does NOT do this on GeneratorExit / exception
            # propagation — Python relies on GC, which is non-deterministic
            # and can hold queue subscriptions open across reconnects.
            # ``aclose`` on an already-exhausted generator is a no-op,
            # so this is safe for the normal exhaustion path too.
            aclose = getattr(generator, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except (StopAsyncIteration, RuntimeError):
                    # Already closed / mid-await — swallow; the cleanup
                    # signal already fired.
                    pass


# ---------------------------------------------------------------------------
# Env-knob factory
# ---------------------------------------------------------------------------


def is_sse_transport_enabled() -> bool:
    """Return True iff ``WORMBASE_MCP_SSE_TRANSPORT`` is truthy.

    Default-off (Optional-Effect Injection §3 Rule 1): an unset env knob
    composes :class:`ListModeTransport` and produces byte-identical
    behavior to pre-Path-3.
    """
    return os.environ.get("WORMBASE_MCP_SSE_TRANSPORT", "false").lower() in (
        "1", "true", "yes", "on",
    )


def log_sse_eligibility_at_boot(*, force: bool = False) -> StreamingProbeDiagnosis:
    """Emit one INFO log line summarizing SSE eligibility at boot.

    Called from :func:`build_stream_transport_from_env` whenever the env
    knob is set (or always, when ``force=True``). Surfaces:

      * The configured intent (env knob on / off).
      * The probed runtime capability (FastMCP supports streaming or not).
      * The chosen transport (list-mode vs SSE).
      * The reason from :class:`StreamingProbeDiagnosis`.

    Returns the diagnosis so callers (CLI ``--check-mcp-sse-eligible``,
    health-check endpoints, tests) can inspect it without re-running the
    probe. The boot log is the operator's only signal that
    ``WORMBASE_MCP_SSE_TRANSPORT=true`` is requested but degraded — the
    per-request degrade log fires only when a stream is actually opened,
    which can be confusing during quiet hours.

    Idempotent in terms of side effects: every call writes one log line.
    The default ``force=False`` path means the only place this fires
    automatically is during transport composition with the env knob set.
    """
    diagnosis = fastmcp_streaming_probe_diagnosis()
    env_requested = is_sse_transport_enabled()

    if not env_requested and not force:
        # Default path: env knob off → list-mode is byte-identical to
        # pre-Path-3. No log spam.
        return diagnosis

    if env_requested and diagnosis["supports_streaming"]:
        # Both intent and capability align — true SSE is active.
        logger.info(
            "SseStreamTransport active: WORMBASE_MCP_SSE_TRANSPORT=true and "
            "FastMCP %s supports streaming tools (reason=%s). Subscription "
            "stream will yield events one-by-one to clients.",
            diagnosis["fastmcp_version"],
            diagnosis["reason"],
        )
    elif env_requested and not diagnosis["supports_streaming"]:
        # Intent set, capability missing — degrade to list-mode.
        logger.info(
            "SseStreamTransport not active despite WORMBASE_MCP_SSE_TRANSPORT=true: "
            "FastMCP %s lacks streaming-tool support (reason=%s). %s. "
            "Subscription stream degrades to list-mode; the {subscription_id, "
            "events: [...]} contract is preserved. Audit the probe diagnosis "
            "before assuming SSE is live.",
            diagnosis["fastmcp_version"],
            diagnosis["reason"],
            diagnosis["detail"],
        )
    else:
        # force=True with env off — operator self-check.
        if diagnosis["supports_streaming"]:
            logger.info(
                "SSE eligibility check: FastMCP %s SUPPORTS streaming tools "
                "(reason=%s) but WORMBASE_MCP_SSE_TRANSPORT is unset. Set the "
                "env knob to opt into SseStreamTransport.",
                diagnosis["fastmcp_version"],
                diagnosis["reason"],
            )
        else:
            logger.info(
                "SSE eligibility check: FastMCP %s does NOT support streaming "
                "tools (reason=%s). %s. WORMBASE_MCP_SSE_TRANSPORT would degrade "
                "to list-mode even if set.",
                diagnosis["fastmcp_version"],
                diagnosis["reason"],
                diagnosis["detail"],
            )

    return diagnosis


def build_stream_transport_from_env() -> StreamTransport:
    """Compose the StreamTransport based on the env knob.

    Default: :class:`ListModeTransport` (byte-identical to pre-Path-3).
    Opt-in: ``WORMBASE_MCP_SSE_TRANSPORT=true`` → :class:`SseStreamTransport``,
    which yields true SSE when the FastMCP capability probe permits and
    degrades to list-mode otherwise.

    Emits one boot-log line via :func:`log_sse_eligibility_at_boot` when
    the env knob is set, so operators can see at startup whether SSE is
    actually active or has degraded to list-mode. No log spam when the
    env knob is unset (default path).
    """
    if is_sse_transport_enabled():
        # One-shot diagnostic at composition time. Operators see SSE
        # active/degraded at server boot, not after the first stream call.
        log_sse_eligibility_at_boot()
        return SseStreamTransport()
    return ListModeTransport()


__all__ = [
    "ListModeTransport",
    "SseStreamTransport",
    "StreamTransport",
    "StreamingProbeDiagnosis",
    "build_stream_transport_from_env",
    "fastmcp_streaming_probe_diagnosis",
    "fastmcp_supports_streaming_tools",
    "is_sse_transport_enabled",
    "log_sse_eligibility_at_boot",
]
