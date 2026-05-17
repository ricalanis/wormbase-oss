"""WormBase catalog-mirror — data-plane Protocol for upstream lake structure import."""

from .errors import (
    AuthenticationError,
    CatalogError,
    DiscoveryError,
    ManifestVersionUnsupportedError,
    PolicyBodyUnavailableError,
    UnsupportedCapabilityError,
)
from .protocol import AuthHandle, CatalogSource
from .reactivities import (
    CatalogDriftReactivity,
    CatalogImportReactivity,
    make_catalog_mirror_reactivities,
)
from .registry import (
    known_catalog_kinds,
    register_catalog_source,
    resolve_catalog_source,
)
from .types import (
    CatalogCapability,
    CatalogDelta,
    CatalogSnapshot,
    ColumnMeta,
    ExternalPolicy,
    LineageEdge,
    LineageGraph,
    MetricDefinition,
    PolicyKind,
    TableMeta,
)
from .wires import wire_catalog_for_source

__all__ = [
    "AuthHandle",
    "AuthenticationError",
    "CatalogCapability",
    "CatalogDelta",
    "CatalogDriftReactivity",
    "CatalogError",
    "CatalogImportReactivity",
    "CatalogSnapshot",
    "CatalogSource",
    "ColumnMeta",
    "DiscoveryError",
    "ExternalPolicy",
    "LineageEdge",
    "LineageGraph",
    "ManifestVersionUnsupportedError",
    "MetricDefinition",
    "PolicyBodyUnavailableError",
    "PolicyKind",
    "TableMeta",
    "UnsupportedCapabilityError",
    "known_catalog_kinds",
    "make_catalog_mirror_reactivities",
    "register_catalog_source",
    "resolve_catalog_source",
    "wire_catalog_for_source",
]
