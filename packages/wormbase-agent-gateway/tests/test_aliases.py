"""Smoke tests for MCP tool-name aliases (Wave D4).

Per the continuous-lake spec §10.7 + §12.1, MCP tool renames during
Wave D ship with a one-release alias that routes the old name to the
new handler. This test verifies the alias-mapping mechanism works for
the two cases:

1. Unrecognized name → returned unchanged (covers every tool not
   renamed).
2. Recognized alias → returned canonicalized to the new name (covers
   the future case where an alias is added).

Today (2026-05-17) the alias table is empty — no ``*connector*`` MCP
tool names exist on the gateway, so no aliases are needed. This test
locks the alias *mechanism* so future renames are safe.
"""
from __future__ import annotations

import wormbase_agent_gateway.aliases as aliases_mod
from wormbase_agent_gateway.aliases import TOOL_NAME_ALIASES, resolve_tool_name


def test_alias_table_is_a_mapping() -> None:
    """The alias table must be a string → string mapping."""
    assert isinstance(TOOL_NAME_ALIASES, dict) or hasattr(
        TOOL_NAME_ALIASES, "__getitem__"
    )
    for old_name, new_name in TOOL_NAME_ALIASES.items():
        assert isinstance(old_name, str) and old_name, (
            f"alias key {old_name!r} must be a non-empty str"
        )
        assert isinstance(new_name, str) and new_name, (
            f"alias value for {old_name!r} must be a non-empty str"
        )


def test_unrecognized_name_passes_through() -> None:
    """Every tool name not in the alias table is returned unchanged."""
    for name in [
        "lake.catalog.tables",
        "lake.query",
        "decisions.list",
        "processes.get",
        "data_products.list",
        "agent.subscriptions.create",
        "totally.nonexistent.tool",
    ]:
        assert resolve_tool_name(name) == name


def test_aliases_resolve_to_canonical_names() -> None:
    """When an alias is registered, resolve_tool_name returns the new name."""
    # No aliases today; the test guards the mechanism by patching one in.
    sentinel_old = "lake.connectors.list"
    sentinel_new = "lake.surfaces.list"
    original = dict(TOOL_NAME_ALIASES)
    try:
        # Temporarily inject an alias to exercise the routing code path.
        aliases_mod.TOOL_NAME_ALIASES = {  # type: ignore[assignment]
            **original,
            sentinel_old: sentinel_new,
        }
        assert aliases_mod.resolve_tool_name(sentinel_old) == sentinel_new
        # The new name is idempotent under resolution.
        assert aliases_mod.resolve_tool_name(sentinel_new) == sentinel_new
        # Unrelated names still pass through.
        assert aliases_mod.resolve_tool_name("decisions.list") == "decisions.list"
    finally:
        aliases_mod.TOOL_NAME_ALIASES = original  # type: ignore[assignment]


def test_resolve_is_idempotent_for_canonical_names() -> None:
    """resolve_tool_name(resolve_tool_name(x)) == resolve_tool_name(x)."""
    for name in [
        "lake.catalog.tables",
        "decisions.list",
        "processes.get",
    ]:
        once = resolve_tool_name(name)
        twice = resolve_tool_name(once)
        assert once == twice
