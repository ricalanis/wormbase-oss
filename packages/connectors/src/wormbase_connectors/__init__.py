"""WormBase Connector Protocol + registry.

A `Connector` is the only abstraction the source-building flows know
about. Adding a new data-source kind is a class registration via
`@register_connector`; no core code ever changes.

Public surface:
    * Protocol:     :class:`Connector`
    * Types:        :class:`SecretBundle`, :class:`AuthHandle`,
                    :class:`ResourceProposal`, :class:`Profile`,
                    :class:`Change`, :class:`Capability`
    * Registry:     :class:`ConnectorRegistry`,
                    :func:`register_connector`,
                    :func:`default_registry`

Importing this package eagerly imports every day-one connector so
their @register_connector decorators fire — the dashboard's connector
picker (D4) and the source-builder's `discover` flow can then look up
any of them by kind without further imports.

The eager-import surface is intentionally narrow: the connector
modules are pure-Python and small (skeletons are <30 LOC each); the
real connectors lazy-import their drivers (asyncpg, aioboto3,
snowflake.connector) inside method bodies, so importing this package
does NOT load 100MB of database drivers.
"""

from __future__ import annotations

from .base import Connector
from .registry import (
    ConnectorRegistry,
    default_registry,
    register_connector,
)
from .types import (
    AuthHandle,
    Capability,
    Change,
    ClassificationHint,
    Profile,
    ResourceProposal,
    SecretBundle,
)

# Eager imports — each module's @register_connector decorator runs at
# import time. Order matches the dashboard /sources/new picker order.
from . import (  # noqa: F401
    local_lake,
    csv_local,
    postgres,
    s3_csv,
    http_csv,
    stripe,
    snowflake,
    bigquery,
    salesforce,
    hubspot,
    gsheets,
    notion,
    linear,
)

# MCP presets (Block J4) — each preset's ``make_mcp_preset(...)`` call
# self-registers with the default registry as ``mcp:<vendor>``. Imported
# after the native connectors so the picker order remains
# native-first / mcp-second by default.
from . import mcp_presets  # noqa: F401

__all__ = [
    "AuthHandle",
    "Capability",
    "Change",
    "ClassificationHint",
    "Connector",
    "ConnectorRegistry",
    "Profile",
    "ResourceProposal",
    "SecretBundle",
    "default_registry",
    "register_connector",
]
