"""Shared types for the Connector Protocol.

Every type here is a frozen dataclass — connectors are pure functions
of (secrets, handle, resource_id), and the input/output shapes need to
be hashable for trace-replay determinism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Capability + ClassificationHint are exposed as plain string aliases
# for documentary convenience. The registry does not enforce the
# allowed values; that's per-connector documentation.
Capability = str  # "discover" | "profile" | "sample" | "watch"
ClassificationHint = str  # "pii" | "confidential" | "regulated" | ...

# ConnectorStatus drives capability honesty in the dashboard's connector
# picker (D4). Production: every Connector method is wired; preview: some
# methods work but others stub/skeletal; coming_soon: skeleton only —
# discover returns [], profile/sample/watch raise NotImplementedError.
ConnectorStatus = Literal["production", "preview", "coming_soon"]


@dataclass(frozen=True)
class SecretBundle:
    """Opaque container for connector credentials. KMS-wrapped at rest.

    The ``payload`` dict is connector-specific: a Postgres connector may
    expect ``{"dsn": ...}`` while a Stripe connector may expect
    ``{"api_key": ...}``. The `Connector.authenticate` method validates
    the shape and raises ValueError if the bundle is malformed.

    Secrets are NEVER logged. The registry, the HTTP write-API, and the
    ledger emit redacted projections only.
    """

    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthHandle:
    """Returned by :meth:`Connector.authenticate`. Used in subsequent calls.

    ``handle_id`` is a stable, non-secret identifier the connector can
    use to resolve runtime state (e.g. a connection-pool key, a session
    cookie cache, a thread-local boto client). ``extra`` is a free-form
    bag for connector-internal state — never logged, never serialized
    to the ledger.
    """

    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceProposal:
    """A resource discovered by :meth:`Connector.discover`.

    ``resource_id`` is connector-internal but stable across calls —
    e.g. a fully-qualified Postgres `schema.table`, an S3 object key,
    a Stripe object name like ``charges``. The source-builder uses
    this id to call subsequent ``profile``/``sample``/``watch``.
    """

    resource_id: str
    name: str
    kind: str  # "table" | "file" | "endpoint" | ...
    classification_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """Result of :meth:`Connector.profile`.

    ``schema_hash`` is a short stable digest of the ordered (column,
    dtype) pairs — used by the lake-builder to detect schema drift
    between profile calls.
    """

    row_count: int | None
    column_count: int | None
    columns: list[dict[str, Any]]
    schema_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """Streaming change record from :meth:`Connector.watch`.

    Most day-one connectors do not implement watch; those that do
    yield ``Change`` records for the lake-builder's CDC ingestion.
    """

    resource_id: str
    seq: int
    kind: str  # "insert" | "update" | "delete"
    payload: dict[str, Any]


__all__ = [
    "AuthHandle",
    "Capability",
    "Change",
    "ClassificationHint",
    "ConnectorStatus",
    "Profile",
    "ResourceProposal",
    "SecretBundle",
]
