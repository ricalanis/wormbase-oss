"""Integration tests — SSE probe diagnostics (Path B, 2026-05-13).

Pins the diagnostics surface that surrounds
:func:`fastmcp_supports_streaming_tools`:

1. :func:`fastmcp_streaming_probe_diagnosis` returns a structured
   ``StreamingProbeDiagnosis`` with a categorical reason and a
   human-readable detail, not just a bool.
2. The probe is **feature-detection-driven** — it inspects
   ``FunctionTool._materialize_generator`` rather than hard-coding False.
   When that method is absent (a future FastMCP that no longer
   materializes generators), the probe still returns False but the
   reason switches to ``materialize_generator_absent`` for auditor
   visibility.
3. :func:`log_sse_eligibility_at_boot` emits exactly one INFO line per
   call summarizing config-intent vs runtime-capability. Fires on
   ``build_stream_transport_from_env`` whenever the env knob is set;
   silent when env knob is off (no log spam in the default path).

This is the **Path B** outcome of the 2026-05-13 #2 final-wave
investigation:

* FastMCP 3.2.4 (installed) materializes generators at
  ``function_tool.py:_materialize_generator``.
* FastMCP 3.3.0b2 (latest beta, downloaded + inspected 2026-05-13) ships
  the **same** materialize-into-list behavior in its ``fastmcp_slim/``
  sdist payload. The 3.3 series focus is ``fastmcp-slim`` (client
  packaging split), not tool-result streaming.
* No FastMCP release notes from 3.0.0 through 3.3.0b2 mention
  async-generator streaming for tools.

The probe therefore stays False; the diagnostics surface improves so
operators have a single boot-log line to read instead of running a
detective hunt through release notes.

When a future FastMCP grows streaming-tool support, the path forward is:

  1. Bump ``fastmcp>=X.Y.Z`` in ``pyproject.toml``.
  2. Confirm the materialize-generator method is gone or rewritten.
  3. The probe flips True automatically (feature detection).
  4. SseStreamTransport's existing SSE branch (already covered by
     ``test_sse_transport_yields_directly_when_probe_returns_true``)
     delivers true per-event yield to clients.
  5. Add a live-yield integration test
     (``test_subscription_stream_sse_native.py`` per the open-paths
     scope) that asserts events arrive incrementally rather than as a
     batch.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

from wormbase_agent_gateway.subscriptions.stream_transport import (
    StreamingProbeDiagnosis,
    build_stream_transport_from_env,
    fastmcp_streaming_probe_diagnosis,
    fastmcp_supports_streaming_tools,
    log_sse_eligibility_at_boot,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Structured-diagnosis probe
# ---------------------------------------------------------------------------


async def test_diagnosis_is_structured_and_complete():
    """Probe returns a fully-populated StreamingProbeDiagnosis dict.

    Every key in the TypedDict is required at the runtime layer — boot
    logs and CLI eligibility checks rely on the full structure being
    present, not partial.
    """
    diag = fastmcp_streaming_probe_diagnosis()

    # Required keys.
    assert set(diag.keys()) == {
        "supports_streaming",
        "fastmcp_version",
        "reason",
        "detail",
    }
    # Value types.
    assert isinstance(diag["supports_streaming"], bool)
    assert isinstance(diag["fastmcp_version"], str)
    assert isinstance(diag["reason"], str)
    assert isinstance(diag["detail"], str)
    assert diag["detail"]  # non-empty


async def test_diagnosis_reflects_installed_fastmcp_3_2_4():
    """On FastMCP 3.2.4, probe detects materialize-into-list behavior.

    The reason code ``materialize_generator_detected`` is the today-state
    signal: the FunctionTool._materialize_generator method exists AND
    its source matches the materialize-into-list pattern. Empirical
    verification of the assumption that drives the False answer.
    """
    diag = fastmcp_streaming_probe_diagnosis()

    assert diag["supports_streaming"] is False
    assert diag["reason"] == "materialize_generator_detected"
    # Version string should look like a fastmcp version.
    assert diag["fastmcp_version"].startswith(("3.", "4.")) or diag[
        "fastmcp_version"
    ] == "unknown"
    # Detail mentions the materialize hot path so operators can audit.
    assert "materialize" in diag["detail"].lower()


async def test_probe_bool_agrees_with_diagnosis():
    """fastmcp_supports_streaming_tools() == diagnosis['supports_streaming'].

    The bool probe is a thin shim over the structured diagnosis. They
    cannot drift; pinning their agreement guards against future
    refactors that accidentally hard-code the bool path.
    """
    diag = fastmcp_streaming_probe_diagnosis()
    assert fastmcp_supports_streaming_tools() is diag["supports_streaming"]


async def test_probe_handles_missing_materialize_method_conservatively():
    """When FunctionTool._materialize_generator is absent, probe stays False.

    A future FastMCP that drops the method might or might not support
    streaming — the absence is necessary but not sufficient evidence.
    The probe stays conservative (False) and surfaces a distinct reason
    code so the upgrader can audit and flip the probe deliberately.

    This pins the upgrade-audit contract: a FastMCP bump alone never
    silently flips True; the upgrader sees a clear
    ``materialize_generator_absent`` diagnosis and explicitly verifies
    the new streaming behavior before flipping.
    """
    from fastmcp.tools.function_tool import FunctionTool

    # Simulate a future FastMCP that removed the materialize method.
    with patch.object(
        FunctionTool, "_materialize_generator", None, create=False
    ), patch(
        "wormbase_agent_gateway.subscriptions.stream_transport."
        "getattr",
        side_effect=lambda obj, name, default=None: (
            None
            if obj is FunctionTool and name == "_materialize_generator"
            else getattr(obj, name) if default is None else getattr(obj, name, default)
        ),
    ):
        # The patch above is fragile; use a direct delattr-style test instead.
        pass

    # Cleaner approach: subclass FunctionTool with the method shadowed to None.
    class FutureFunctionTool:
        """Stand-in for a future FastMCP FunctionTool sans materialize hook."""

    with patch(
        "fastmcp.tools.function_tool.FunctionTool", FutureFunctionTool
    ):
        diag = fastmcp_streaming_probe_diagnosis()
    assert diag["supports_streaming"] is False
    assert diag["reason"] == "materialize_generator_absent"
    assert "audit" in diag["detail"].lower() or "unknown" in diag["detail"].lower()


async def test_probe_handles_fastmcp_unavailable_gracefully():
    """When fastmcp is uninstalled, probe returns False with a clear reason.

    Defensive coverage — the agent-gateway depends on fastmcp, so this
    should never fire in production, but the probe must not raise.
    The reason ``fastmcp_unavailable`` lets a future test harness
    inspect the failure mode without crashing.
    """
    # Force the import to fail by injecting a sentinel that raises on attribute
    # access. We patch the import machinery for the local import inside the
    # probe.
    import builtins

    real_import = builtins.__import__

    def import_blocking_fastmcp(name, *args, **kwargs):
        if name == "fastmcp":
            raise ImportError("simulated missing fastmcp")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", import_blocking_fastmcp):
        diag = fastmcp_streaming_probe_diagnosis()

    assert diag["supports_streaming"] is False
    assert diag["reason"] == "fastmcp_unavailable"
    assert diag["fastmcp_version"] == "unknown"
    assert "fastmcp" in diag["detail"].lower()


# ---------------------------------------------------------------------------
# Boot-log emission
# ---------------------------------------------------------------------------


async def test_boot_log_silent_when_env_knob_unset(caplog):
    """No log spam in the default path (env knob off).

    The byte-identical pre-Path-3 default must stay byte-identical at the
    log level too. Operators should never see SSE-related logs from
    builds that don't opt into the env knob.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORMBASE_MCP_SSE_TRANSPORT", None)
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            log_sse_eligibility_at_boot()

    assert not caplog.records, (
        f"Boot log should be silent when env knob is off; got "
        f"{[r.getMessage() for r in caplog.records]}"
    )


async def test_boot_log_fires_once_when_env_knob_set_and_degraded(caplog):
    """One INFO line when env knob is true but FastMCP can't stream.

    This is the Path B headline behavior: operators set
    ``WORMBASE_MCP_SSE_TRANSPORT=true`` expecting live SSE, get
    list-mode silently in v2.A. The boot log fixes that — one INFO
    line at startup says "you asked for SSE; FastMCP <ver> can't, so
    we're list-mode."
    """
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": "true"}):
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            diag = log_sse_eligibility_at_boot()

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1, (
        f"expected exactly one boot log line; got "
        f"{[r.getMessage() for r in info_records]}"
    )
    msg = info_records[0].getMessage()
    assert "SseStreamTransport not active" in msg
    assert "WORMBASE_MCP_SSE_TRANSPORT=true" in msg
    assert "list-mode" in msg
    assert diag["fastmcp_version"] in msg  # version surfaced for ops
    assert diag["supports_streaming"] is False


async def test_boot_log_fires_with_force_for_self_check(caplog):
    """force=True emits the eligibility check even when env knob is off.

    Powers a future ``--check-mcp-sse-eligible`` CLI flag (or operator
    self-check endpoint) without needing to flip the env knob. Stays
    in the agent-gateway package — no apps/worm-core/ change required.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORMBASE_MCP_SSE_TRANSPORT", None)
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            diag = log_sse_eligibility_at_boot(force=True)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    msg = info_records[0].getMessage()
    assert "SSE eligibility check" in msg
    assert "does NOT support streaming" in msg or "SUPPORTS streaming" in msg
    assert diag["fastmcp_version"] in msg


async def test_boot_log_says_active_when_probe_returns_true(caplog):
    """When probe + env knob both align, boot log confirms SSE active.

    The future-good-case: FastMCP grows streaming, probe flips True,
    env knob is on. Operators see "SseStreamTransport active" — no
    detective work needed to confirm the live-yield path is engaged.
    """
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": "true"}), patch(
        "wormbase_agent_gateway.subscriptions.stream_transport."
        "fastmcp_streaming_probe_diagnosis",
        return_value=StreamingProbeDiagnosis(
            supports_streaming=True,
            fastmcp_version="9.9.9-future",
            reason="materialize_generator_absent",
            detail="hypothetical future FastMCP with streaming tools",
        ),
    ):
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            log_sse_eligibility_at_boot()

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    msg = info_records[0].getMessage()
    assert "SseStreamTransport active" in msg
    assert "9.9.9-future" in msg
    assert "supports streaming" in msg.lower()


# ---------------------------------------------------------------------------
# Boot log composes with the env factory
# ---------------------------------------------------------------------------


async def test_env_factory_emits_boot_log_on_opt_in(caplog):
    """build_stream_transport_from_env() fires the boot log when env=true.

    The composition path is where operators discover SSE state — one
    place to look at server boot. Pins the integration so future
    factory refactors don't accidentally drop the boot-log call.
    """
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": "true"}):
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            transport = build_stream_transport_from_env()

    # SseStreamTransport returned.
    from wormbase_agent_gateway.subscriptions.stream_transport import (
        SseStreamTransport,
    )
    assert isinstance(transport, SseStreamTransport)
    # Boot log fired.
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert "SseStreamTransport" in info_records[0].getMessage()


async def test_env_factory_silent_on_default_path(caplog):
    """build_stream_transport_from_env() never logs in the default path.

    Pins the no-spam contract for the byte-identical default. If a
    future change accidentally calls log_sse_eligibility_at_boot
    unconditionally, this fails.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORMBASE_MCP_SSE_TRANSPORT", None)
        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            transport = build_stream_transport_from_env()

    from wormbase_agent_gateway.subscriptions.stream_transport import (
        ListModeTransport,
    )
    assert isinstance(transport, ListModeTransport)
    assert not caplog.records, (
        f"Default-path env factory should be silent; got "
        f"{[r.getMessage() for r in caplog.records]}"
    )
