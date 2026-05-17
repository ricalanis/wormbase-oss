"""Chat-flow private protocols + helpers (lifted from flows.py:40-110).

Wave D consolidation: ``_PIIGateProto`` and ``_InterjectionGateProto``
are now aliases to the public Protocols in
``wormbase_governance.types`` (PIIGateProtocol, InterjectionGateProtocol).
The underscore-private names are retained so existing chat_flows imports
remain valid; new code should import from wormbase_governance.types
directly.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from wormbase_core.source_builder import SourceBuilder
from wormbase_governance.types import (  # noqa: F401  Re-exported as legacy compat aliases per module docstring; importers use the underscore-private names.
    InterjectionGateProtocol as _InterjectionGateProto,
    PIIGateProtocol as _PIIGateProto,
)


class _ChatSenderProto(Protocol):
    async def send(
        self, channel_id: str, text: str, *, speech_act: str = "proposal"
    ) -> None: ...


class CredentialLeakError(Exception):
    """Raised when credentials appear in a public channel."""


class FileProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_count: int
    column_count: int
    columns: list[dict[str, Any]]
    schema_hash: str


class _BuilderHostingFlow:
    """Mixin for flows that own a ``SourceBuilder`` and want public read access.

    The ``builder`` property is the canonical way for downstream cascade
    helpers and dispatchers to reach the builder; reaching for
    ``flow._builder`` is forbidden after E4. Subclasses set
    ``self._builder`` in __init__ exactly as today.
    """

    _builder: SourceBuilder

    @property
    def builder(self) -> SourceBuilder:
        """Read-only access to the SourceBuilder this flow drives."""
        return self._builder
