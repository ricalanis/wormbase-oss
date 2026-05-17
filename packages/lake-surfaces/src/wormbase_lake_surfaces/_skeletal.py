"""Shared base for skeletal SaaS connectors.

A skeletal connector exists to:
1. Prove the SurfaceDriver abstraction is platform-agnostic.
2. Render in the dashboard /sources/new picker (D4) at the same fidelity
   as a fully-implemented connector — JSON-schema config, capability
   chips, classification hints.
3. Define the auth shape that the production implementation will use
   when it lands post-day-one.

Skeletons:
- ``authenticate`` validates secret shape but does not call out to the
  remote — it returns a synthetic AuthHandle.
- ``discover`` returns ``[]`` with a TODO comment in the source.
- ``profile``, ``sample``, ``watch`` raise NotImplementedError with a
  clear message pointing at the issue / phase that will fill them in.

Subclasses provide:
- ``kind``        — connector kind string
- ``capability``  — set of capabilities (typically {discover}; the
                    others raise even if "advertised" so the dashboard
                    can preview the surface)
- ``classification_hints`` — list of hint strings
- ``required_secrets`` — tuple of required keys in the SecretBundle
- ``optional_secrets`` — tuple of optional keys (informational)
- ``config_schema()`` — JSON-schema dict the dashboard renders to a
                       form
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from .base import SurfaceDriver
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


class SkeletalSurfaceDriver(SurfaceDriver):
    """Base for connectors whose discover/profile/sample land post-day-one.

    Concrete subclasses set the class attributes; this base provides the
    Protocol-compliant method bodies.

    Default capability-honesty status is ``"coming_soon"`` — discover
    returns ``[]``, profile/sample/watch raise NotImplementedError.
    Subclasses promote to ``"preview"`` when at least one operational
    method is wired against the real platform.
    """

    kind: ClassVar[str] = ""
    capability: ClassVar[set[Capability]] = {"discover"}
    classification_hints: ClassVar[list[ClassificationHint]] = []
    status: ClassVar[ConnectorStatus] = "coming_soon"
    status_note: ClassVar[str] = (
        "SurfaceDriver skeleton — discovery returns empty, "
        "full implementation lands post-day-one."
    )
    required_secrets: ClassVar[tuple[str, ...]] = ()
    optional_secrets: ClassVar[tuple[str, ...]] = ()
    not_implemented_reason: ClassVar[str] = (
        "Production implementation lands post-day-one"
    )

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        """JSON-schema rendered by the dashboard's connector picker.

        Each required secret becomes a `string` property with
        `format: password`; optional secrets are surfaced as plain
        strings. Subclasses can override to expose additional shape.
        """
        properties: dict[str, dict[str, Any]] = {
            key: {"type": "string", "format": "password", "title": key}
            for key in cls.required_secrets
        }
        for key in cls.optional_secrets:
            properties[key] = {"type": "string", "title": key}
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": cls.kind,
            "type": "object",
            "required": list(cls.required_secrets),
            "properties": properties,
        }

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        missing = [
            k for k in self.required_secrets if not secrets.payload.get(k)
        ]
        if missing:
            raise ValueError(
                f"{self.kind} connector requires "
                f"{list(self.required_secrets)}; missing: {missing}"
            )
        # Stable handle id keyed off the first required secret value.
        seed = str(secrets.payload[self.required_secrets[0]]).encode()
        return AuthHandle(
            connector_kind=self.kind,
            handle_id=hashlib.sha256(seed).hexdigest()[:16],
            extra={"secrets": dict(secrets.payload)},
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        # TODO: list resources via the platform's REST/SDK.
        return []

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        raise NotImplementedError(
            f"{self.kind}.profile: {self.not_implemented_reason}"
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        raise NotImplementedError(
            f"{self.kind}.sample: {self.not_implemented_reason}"
        )

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        raise NotImplementedError(
            f"{self.kind}.watch: {self.not_implemented_reason}"
        )
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]


__all__ = ["SkeletalSurfaceDriver"]
