"""CatalogSource error taxonomy."""
from __future__ import annotations


class CatalogError(RuntimeError):
    """Base error for catalog-mirror operations."""


class AuthenticationError(CatalogError):
    """Credentials rejected by the upstream."""


class DiscoveryError(CatalogError):
    """Upstream returned an error during discover_* call."""


class PolicyBodyUnavailableError(CatalogError):
    """Caller lacks APPLY privilege; policy reference visible but body not. Per spike S2."""


class UnsupportedCapabilityError(CatalogError):
    """Caller invoked a capability not in this CatalogSource's `capability` set."""


class ManifestVersionUnsupportedError(CatalogError):
    """dbt manifest schema version outside the supported range. Per spike S1 risk."""
