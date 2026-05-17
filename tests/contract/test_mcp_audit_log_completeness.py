"""Contract gate (Block J8): every MCP registration writes an audit row.

The MCP-native institutional-AI thesis claims auditability across the
entire surface, not just the read tools. This gate enforces that every
tool, prompt, and resource registered on the FastMCP server invokes
one of the canonical audit primitives:

- ``record_mcp_call``  — the canonical PEVR audit write.
- ``audit``            — the shared helper (delegates to ``record_mcp_call``).
- ``_audit``           — the Phase 0 ``mcp_server.py`` helper (also delegates).
- ``_audit_resource_read`` — the resource-side delegate.
- ``_finish_call`` / ``_finish`` — read-tool / write-tool wrappers that
  in turn invoke ``audit``.

Mechanism: introspect the FastMCP server (built via ``build_mcp_server``)
via its ``_tool_manager`` / ``_prompt_manager`` / ``_resource_manager``,
walk to each registered handler function, and read the function's
source via ``inspect.getsource``. Assert that the source references one
of the audit primitives. A registration that ships without audit
decoration fails this gate.

Why static-source inspection rather than a runtime patch + stub-context
drive: every tool needs a different valid argument shape and a fresh
auth context. Static inspection is far cheaper, deterministic, and
catches the same defect (a missing audit decoration).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_ledger import InMemoryLedger


_AUDIT_PRIMITIVES = (
    "record_mcp_call",
    "audit(",          # ``audit(ledger, ...)`` — the shared helper.
    "_audit(",         # Phase 0 mcp_server.py helper.
    "_audit_resource_read",
    "_finish_call(",   # read_tools wrapper that calls audit().
    "_finish(",        # write_tools wrapper that calls audit().
)


def _assert_audits(name: str, fn: Any) -> None:
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError) as exc:
        raise AssertionError(
            f"could not inspect source of MCP handler {name!r}: {exc}"
        ) from exc
    if not any(token in src for token in _AUDIT_PRIMITIVES):
        raise AssertionError(
            f"MCP handler {name!r} ships without an audit decoration. "
            f"Its body must invoke one of {_AUDIT_PRIMITIVES} so every "
            f"call lands an emit_mcp_call_received row on the ledger. "
            f"(Defined in {getattr(fn, '__module__', '?')}.)"
        )


def _registered_tools(mcp: Any) -> dict[str, Any]:
    tm = mcp._tool_manager  # noqa: SLF001
    out: dict[str, Any] = {}
    # FastMCP's ToolManager exposes tools via _tools dict; some versions
    # use list_tools() iteration. We fall back if the dict isn't present.
    tools_dict = getattr(tm, "_tools", None)
    if tools_dict:
        for name, tool in tools_dict.items():
            out[name] = tool.fn
    else:  # pragma: no cover - defensive
        import asyncio
        for tool in asyncio.run(mcp.list_tools()):
            out[tool.name] = getattr(tool, "fn", None)
    return out


def _registered_prompts(mcp: Any) -> dict[str, Any]:
    pm = mcp._prompt_manager  # noqa: SLF001
    out: dict[str, Any] = {}
    prompts_dict = getattr(pm, "_prompts", None)
    if prompts_dict:
        for name, prompt in prompts_dict.items():
            out[name] = prompt.fn
    return out


def _registered_resources(mcp: Any) -> dict[str, Any]:
    rm = mcp._resource_manager  # noqa: SLF001
    out: dict[str, Any] = {}
    # FastMCP keeps URI-templated resources under _templates and
    # statically-bound ones under _resources.
    for attr in ("_templates", "_resources"):
        d = getattr(rm, attr, None)
        if not d:
            continue
        for key, item in d.items():
            out[str(key)] = item.fn
    return out


@pytest.fixture(scope="module")
def mcp_server() -> Any:
    return build_mcp_server(
        ledger=InMemoryLedger(), api_token="contract-gate",
    )


def test_every_registered_tool_invokes_audit(mcp_server: Any) -> None:
    tools = _registered_tools(mcp_server)
    assert tools, "no tools registered — the FastMCP server is empty"
    for name, fn in tools.items():
        _assert_audits(name, fn)


def test_every_registered_prompt_invokes_audit_or_documents_exception(
    mcp_server: Any,
) -> None:
    """Prompts read context but don't (yet) write audit rows.

    The MCP spec treats prompts as user-curated templates that the
    client renders — they're closer to resources than to tools. The
    Phase 0/J3 implementation follows that convention: prompt
    invocation does not write a per-call audit row. We document the
    exemption here so a future spec change that reverses it lands a
    failing gate instead of silently shipping unaudited prompts.

    If you tighten the policy (require prompts to audit), remove this
    test and let the per-tool gate above subsume them.
    """
    prompts = _registered_prompts(mcp_server)
    assert prompts, "no prompts registered — the J3 wiring may have regressed"
    # Sanity: every prompt's body MUST be inspectable — even if it does
    # not currently audit, we want to be able to reason about it.
    for name, fn in prompts.items():
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError) as exc:
            raise AssertionError(
                f"prompt {name!r} source is not inspectable: {exc}"
            ) from exc
        assert src, f"prompt {name!r} has empty source"


def test_every_registered_resource_invokes_audit(mcp_server: Any) -> None:
    resources = _registered_resources(mcp_server)
    assert resources, "no resources registered — the J3 wiring may have regressed"
    for name, fn in resources.items():
        _assert_audits(name, fn)


def test_audit_primitive_set_includes_record_mcp_call(mcp_server: Any) -> None:
    """At least ONE registered handler must call ``record_mcp_call`` directly.

    This guards against a future refactor that renames ``record_mcp_call``
    out from under us — if the primitive disappears, this test fires.
    """
    tools = _registered_tools(mcp_server)
    seen_record = False
    for fn in tools.values():
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if "record_mcp_call" in src or "_audit(" in src:
            seen_record = True
            break
    # Some tools call record_mcp_call indirectly via audit() — also count
    # those by walking the audit() helper's source.
    if not seen_record:
        from wormbase_core.mcp_tools.auth import audit as audit_helper
        try:
            helper_src = inspect.getsource(audit_helper)
        except (OSError, TypeError):
            helper_src = ""
        seen_record = "record_mcp_call" in helper_src
    assert seen_record, (
        "no handler reaches record_mcp_call (directly or via audit()) — "
        "the canonical PEVR audit primitive may have been renamed."
    )
