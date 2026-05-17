"""The :class:`Connector` Protocol.

Every data-source kind WormBase knows about implements this Protocol.
The registry binds a ``kind`` string to a Connector class; the
source-builder flows look connectors up by kind and call the methods
declared here.

The Protocol is ``runtime_checkable`` — tests use ``isinstance(c,
Connector)`` to assert structural conformance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .types import (
    AuthHandle,
    Capability,
    Change,
    ClassificationHint,
    ConnectorStatus,
    Profile,
    ResourceProposal,
    SecretBundle,
)


@runtime_checkable
class Connector(Protocol):
    """A pluggable data-source connector.

    Implementations register themselves via :func:`register_connector`
    and live in :mod:`wormbase_lake_surfaces.<kind>`. The four operational
    methods are all async; capabilities not supported by a given
    connector should raise ``NotImplementedError`` (skeletal stubs) or
    return an empty result (e.g. ``watch`` for pull-only connectors).

    Capability-honesty: every Connector declares ``status`` and
    ``status_note`` so the dashboard's connector picker can render an
    accurate badge ("production" / "preview" / "coming_soon") + a short
    user-facing note explaining what works and what doesn't. Skeletal
    connectors are NOT hidden — they're proof-of-abstraction value —
    but the picker UI must label them honestly.
    """

    kind: str
    capability: set[Capability]
    classification_hints: list[ClassificationHint]
    status: ConnectorStatus
    status_note: str

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle: ...

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]: ...

    async def profile(
        self, handle: AuthHandle, resource_id: str
    ) -> Profile: ...

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes: ...

    def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]: ...


__all__ = ["Connector"]
