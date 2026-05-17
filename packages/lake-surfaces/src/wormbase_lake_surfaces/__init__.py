"""WormBase lake-surfaces — Connector Protocol + lake-side Protocols + registry.

A ``Connector`` (to be renamed ``SurfaceDriver`` in Wave D2) is the
driver-class abstraction the source-building flows know about. Adding
a new data-source kind is a class registration via
``@register_connector``; no core code ever changes.

Per ADR-0013 (continuous lake philosophy) + ADR-0003 (2026-05-17
addendum), this package also hosts the three lake-side Protocols
(``AcquirableSource``, ``MaintainableSource``, ``LakeStore``) and the
per-family Source impls (external + filedrop via ``AcquirableSourceImpl``,
conversation via ``ConversationSource``, evidence via ``EvidenceSource``).

Public surface:
    * Driver Protocol: :class:`Connector`
    * Lake-side Protocols: :class:`AcquirableSource`,
                    :class:`MaintainableSource`, :class:`LakeStore`
    * Source impls: :class:`AcquirableSourceImpl`,
                    :class:`ConversationSource`,
                    :class:`EvidenceSource`
    * Types:        :class:`SecretBundle`, :class:`AuthHandle`,
                    :class:`ResourceProposal`, :class:`Profile`,
                    :class:`Change`, :class:`Capability`,
                    :class:`DriftReport`, :class:`ClassificationUpdate`,
                    :class:`StalenessReport`, :class:`LineageReport`,
                    :class:`SourceFamily`, :class:`Classification`
    * Registry:     :class:`ConnectorRegistry`,
                    :func:`register_connector`,
                    :func:`default_registry`

Importing this package eagerly imports every day-one driver so
their ``@register_connector`` decorators fire — the dashboard's
lake-surface picker (D4) and the source-builder's ``discover`` flow can
then look up any of them by kind without further imports.

The eager-import surface is intentionally narrow: the driver modules
are pure-Python and small (skeletons are <30 LOC each); the real
drivers lazy-import their underlying libraries (asyncpg, aioboto3,
snowflake.connector) inside method bodies, so importing this package
does NOT load 100MB of database drivers.
"""

from __future__ import annotations

from .base import Connector
from .protocols import (
    AcquirableSource,
    LakeStore,
    MaintainableSource,
)
from .registry import (
    ConnectorRegistry,
    default_registry,
    register_connector,
)
from .types import (
    AuthHandle,
    Capability,
    Change,
    Classification,
    ClassificationHint,
    ClassificationUpdate,
    DriftReport,
    LineageEdge,
    LineageReport,
    Profile,
    ResourceProposal,
    SecretBundle,
    SourceFamily,
    SourceId,
    StalenessReport,
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
from . import mcp_presets  # noqa: F401, E402

# Source-impl re-exports — moved here per ADR-0013 (continuous lake
# philosophy) so surface-family impls live next to the SurfaceDriver
# drivers + Protocols.
from .conversation_source import ConversationSource  # noqa: E402
from .evidence_source import EvidenceSource  # noqa: E402
from .external_source import AcquirableSourceImpl  # noqa: E402

__all__ = [
    "AcquirableSource",
    "AcquirableSourceImpl",
    "AuthHandle",
    "Capability",
    "Change",
    "Classification",
    "ClassificationHint",
    "ClassificationUpdate",
    "Connector",
    "ConnectorRegistry",
    "ConversationSource",
    "DriftReport",
    "EvidenceSource",
    "LakeStore",
    "LineageEdge",
    "LineageReport",
    "MaintainableSource",
    "Profile",
    "ResourceProposal",
    "SecretBundle",
    "SourceFamily",
    "SourceId",
    "StalenessReport",
    "default_registry",
    "register_connector",
]
