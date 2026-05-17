"""Boot-path wire regression test (Wave E.3 — hub redefinition).

Pins the orchestration-doc target shape: ``apps/worm-core/cli.py`` calls
``wire_<worm>_for_install`` for each extracted worm package. If a future
refactor accidentally drops a wire (or renames it without updating the
hub), this suite fires loudly.

Five wires are bound today:

- ``wire_identity_for_install``      (Wave A   — wormbase-identity-tracker)
- ``wire_chat_for_install``          (Wave B   — wormbase-chat-presence)
- ``wire_process_for_install``       (Wave C₂  — wormbase-process-extractor)
- ``wire_research_for_install``      (Wave C₁  — wormbase-research-loop)
- ``wire_agent_gateway_for_install`` (Wave 2 Task 8 — wormbase-agent-gateway)

``wire_lake_for_install``, ``wire_governance_for_install``, and the
catalog-mirror wire remain intentionally unbound — lake-maintainer wires
per-source via ``wire_maintenance_for_source`` from inside
``source_builder.py``; catalog-mirror wires per-source via
``wire_catalog_for_source`` from the same lifecycle hook (Wave 1
cleanup 1a, 2026-05-11); governance gates compose into other wires at
construction sites. Their absence here is by design, not an oversight.
"""
from __future__ import annotations

import inspect

import pytest


_EXPECTED_WIRES = (
    "wire_identity_for_install",
    "wire_chat_for_install",
    "wire_process_for_install",
    "wire_research_for_install",
    "wire_agent_gateway_for_install",
)


@pytest.mark.parametrize("wire_name", _EXPECTED_WIRES)
def test_cli_module_binds_wire(wire_name: str) -> None:
    """Each expected wire is importable from cli's module namespace."""
    from wormbase_core import cli

    assert hasattr(cli, wire_name), (
        f"cli.py missing import for {wire_name}; the worm package's "
        f"lifecycle hook must be threaded through cli's _run_async path"
    )
    bound = getattr(cli, wire_name)
    assert callable(bound), (
        f"{wire_name} is bound on cli but not callable; check the import"
    )


def test_cli_run_async_calls_each_wire() -> None:
    """The boot path source references each wire by name.

    A textual check (rather than an async run) — _run_async opens
    Postgres, builds Slack adapters, and starts long-lived asyncio
    tasks. We assert the call sites exist in the source so a rename or
    deletion fails the test instead of silently dropping a worm from
    the boot path.
    """
    from wormbase_core import cli

    src = inspect.getsource(cli._run_async)
    for wire_name in _EXPECTED_WIRES:
        assert f"{wire_name}(" in src, (
            f"_run_async does not appear to call {wire_name}; this is a "
            f"regression — every extracted worm must wire at boot"
        )


def test_cli_imports_extracted_worm_packages() -> None:
    """The four wires come from their canonical worm packages.

    Pins the import statement so a future maintainer can't accidentally
    point a wire at a stale shim or fork.
    """
    from wormbase_agent_gateway import wire_agent_gateway_for_install as _wag
    from wormbase_chat_presence import wire_chat_for_install as _wc
    from wormbase_identity_tracker import wire_identity_for_install as _wi
    from wormbase_process_extractor import wire_process_for_install as _wp
    from wormbase_research_loop import wire_research_for_install as _wr

    from wormbase_core import cli

    # Identity equality: cli.py must hold the SAME callables that the
    # canonical packages export, not aliases or wrappers.
    assert cli.wire_chat_for_install is _wc
    assert cli.wire_identity_for_install is _wi
    assert cli.wire_process_for_install is _wp
    assert cli.wire_research_for_install is _wr
    assert cli.wire_agent_gateway_for_install is _wag
