"""Tests for the six MCP presets — config shape + registry binding.

Each preset is ~30 LOC of declarative config; these tests guard the
contract the dashboard's connector picker depends on:

* Each preset registers a unique ``mcp:<vendor>`` kind in the default
  registry.
* Each preset declares ``required_secrets`` (so the credential form
  knows what fields to render).
* Each preset's ``server_url`` is non-empty + an HTTPS URL.
* Each preset is a SurfaceDriver-Protocol implementation.
"""

from __future__ import annotations

import pytest

from wormbase_lake_surfaces.base import SurfaceDriver
from wormbase_lake_surfaces.mcp import MCPSurfaceDriver, MCPServerConfig
from wormbase_lake_surfaces.mcp_presets.atlassian_preset import (
    ATLASSIAN_CONFIG,
    AtlassianMCPSurfaceDriver,
)
from wormbase_lake_surfaces.mcp_presets.github_preset import (
    GITHUB_CONFIG,
    GithubMCPSurfaceDriver,
)
from wormbase_lake_surfaces.mcp_presets.gworkspace_preset import (
    GWORKSPACE_CONFIG,
    GworkspaceMCPSurfaceDriver,
)
from wormbase_lake_surfaces.mcp_presets.hubspot_preset import (
    HUBSPOT_CONFIG,
    HubspotMCPSurfaceDriver,
)
from wormbase_lake_surfaces.mcp_presets.linear_preset import (
    LINEAR_CONFIG,
    LinearMCPSurfaceDriver,
)
from wormbase_lake_surfaces.mcp_presets.notion_preset import (
    NOTION_CONFIG,
    NotionMCPSurfaceDriver,
)
from wormbase_lake_surfaces.registry import default_registry

PRESETS: list[tuple[MCPServerConfig, type[MCPSurfaceDriver]]] = [
    (NOTION_CONFIG, NotionMCPSurfaceDriver),
    (ATLASSIAN_CONFIG, AtlassianMCPSurfaceDriver),
    (LINEAR_CONFIG, LinearMCPSurfaceDriver),
    (GITHUB_CONFIG, GithubMCPSurfaceDriver),
    (GWORKSPACE_CONFIG, GworkspaceMCPSurfaceDriver),
    (HUBSPOT_CONFIG, HubspotMCPSurfaceDriver),
]

EXPECTED_KINDS = {
    "mcp:notion",
    "mcp:atlassian",
    "mcp:linear",
    "mcp:github",
    "mcp:gworkspace",
    "mcp:hubspot",
}


def test_each_preset_registers_a_unique_mcp_kind() -> None:
    """All 6 presets show up in the default registry under unique kinds."""
    reg = default_registry()
    registered = set(reg.all_kinds())
    assert EXPECTED_KINDS.issubset(registered), (
        f"missing presets: {EXPECTED_KINDS - registered}"
    )


@pytest.mark.parametrize(
    "config, cls",
    PRESETS,
    ids=lambda v: getattr(v, "kind", str(v)),
)
def test_preset_class_is_a_connector(
    config: MCPServerConfig, cls: type[MCPSurfaceDriver]
) -> None:
    assert issubclass(cls, MCPSurfaceDriver)
    instance = cls()  # config bound at class level
    assert isinstance(instance, SurfaceDriver)
    assert instance.kind == config.kind
    assert instance.kind.startswith("mcp:")


@pytest.mark.parametrize("config, cls", PRESETS, ids=lambda v: getattr(v, "kind", str(v)))
def test_preset_config_shape(
    config: MCPServerConfig, cls: type[MCPSurfaceDriver]
) -> None:
    """Each preset declares the dashboard-renderable shape."""
    assert config.kind == cls.kind
    assert config.server_url.startswith("https://"), (
        f"{config.kind}: server_url must be HTTPS for production posture"
    )
    assert isinstance(config.required_secrets, tuple)
    assert len(config.required_secrets) >= 1, (
        f"{config.kind}: must declare at least one required secret"
    )
    assert "bearer_token" in config.required_secrets or "api_key" in config.required_secrets, (
        f"{config.kind}: must accept either bearer_token or api_key"
    )
    assert isinstance(config.scopes, tuple)
    assert config.description, f"{config.kind}: description must be non-empty"


@pytest.mark.parametrize("config, cls", PRESETS, ids=lambda v: getattr(v, "kind", str(v)))
def test_preset_class_binds_to_registry(
    config: MCPServerConfig, cls: type[MCPSurfaceDriver]
) -> None:
    reg = default_registry()
    assert reg.get(config.kind) is cls


@pytest.mark.parametrize("config, cls", PRESETS, ids=lambda v: getattr(v, "kind", str(v)))
def test_preset_capabilities_are_complete(
    config: MCPServerConfig, cls: type[MCPSurfaceDriver]
) -> None:
    """All presets advertise discover/profile/sample (watch is v2)."""
    instance = cls()
    assert "discover" in instance.capability
    assert "profile" in instance.capability
    assert "sample" in instance.capability


@pytest.mark.parametrize("config, cls", PRESETS, ids=lambda v: getattr(v, "kind", str(v)))
def test_preset_status_and_note(
    config: MCPServerConfig, cls: type[MCPSurfaceDriver]
) -> None:
    """Honest status: presets are ``preview`` (vendor-maintained external surface)."""
    assert cls.status in ("preview", "production"), (
        f"{config.kind}: MCP presets ship in preview, never coming_soon"
    )
    assert cls.status_note, f"{config.kind}: status_note must be non-empty"


def test_six_presets_total_no_more_no_less() -> None:
    """v1 cut is exactly six. Adding a 7th means updating the catalog test."""
    assert len(EXPECTED_KINDS) == 6
    assert len(PRESETS) == 6


def test_hubspot_preset_coexists_with_native_hubspot() -> None:
    """``mcp:hubspot`` is a parallel path to the native ``hubspot`` connector."""
    reg = default_registry()
    native = reg.get("hubspot")
    mcp_path = reg.get("mcp:hubspot")
    assert native is not None
    assert mcp_path is not None
    assert native is not mcp_path
