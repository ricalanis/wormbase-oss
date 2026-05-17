"""MCP-backed Connector — instantiate any MCP server as a WormBase source.

Per `docs/superpowers/specs/2026-04-27-mcp-integration.md` §6 (Connector-vs-MCP):
``MCPConnector`` implements the standard :class:`Connector` Protocol by
speaking MCP under the hood. From the rest of the codebase's
perspective, an MCP-backed source is indistinguishable from a Postgres
source — same ``discover/profile/sample/watch``, same registry, same
flows. This is Option C from §6.1 ("MCP IS ONE Connector
implementation"): no parallel substrate, no fork in the source-builder,
no new flow surface.

Mapping:

* ``Connector.discover``  → MCP ``list_resources()``
* ``Connector.profile``   → MCP ``read_resource(uri)`` against
  metadata URIs (each preset names which resources are "metadata"-style
  vs. "bytes"-style); fallback to a column-less Profile when the
  upstream doesn't expose schemas.
* ``Connector.sample``    → MCP ``read_resource(uri)`` with byte cap
* ``Connector.watch``     → not advertised; MCP is request/response in
  v1 (per §6.4). Returns an empty async iterator.

Presets configure per-server URLs + auth shape + classification hints
(``packages/connectors/src/wormbase_connectors/mcp_presets/``). The
core ``MCPConnector`` class is preset-agnostic — it accepts a
:class:`MCPServerConfig` describing where to connect and how.

Auth model:

The core class accepts two auth flavors via the SecretBundle payload:

* ``{"bearer_token": "..."}``  — opaque OAuth bearer (production path
  for vendor MCP servers like Notion / Atlassian / Linear / GitHub).
* ``{"api_key": "..."}``        — for servers that accept an API key
  via ``Authorization: Bearer <key>``.

The preset declares which keys are required via
:attr:`MCPServerConfig.required_secrets`.

Transport:

In v1 we use Streamable HTTP (SSE-based) — the canonical remote MCP
transport per the spec. ``mcp.client.streamable_http.streamablehttp_client``
opens a long-lived session against the configured server URL, and
``mcp.ClientSession`` is the request-side handle.

Tests inject a fake transport via the ``session_factory`` constructor
argument (see ``tests/test_mcp_connector.py``); the dependency injection
keeps the network out of unit tests while preserving the production
code path for everything else.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Protocol

from .base import Connector
from .registry import register_connector
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


# ---------------------------------------------------------------------------
# Config + session-factory contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPServerConfig:
    """Per-server preset config.

    Presets live in :mod:`wormbase_connectors.mcp_presets` and bind a
    ``kind`` (e.g. ``"mcp:notion"``) to a server URL + auth shape +
    classification hints. The dashboard's connector picker (D4) reads
    ``required_secrets`` to render the credential form.
    """

    kind: str
    server_url: str
    """Streamable-HTTP MCP endpoint, e.g. ``https://mcp.notion.com/mcp``."""

    required_secrets: tuple[str, ...]
    """Keys the SecretBundle payload must carry. e.g. ``("bearer_token",)``."""

    optional_secrets: tuple[str, ...] = ()
    classification_hints: tuple[ClassificationHint, ...] = ()
    scopes: tuple[str, ...] = ()
    """OAuth scopes requested at install time (informational; the auth
    handshake itself happens via OAuth 2.1 elsewhere — the connector
    only verifies the bearer token at authenticate-time)."""
    description: str = ""
    """Short editorial description rendered in the connector picker."""


class MCPSessionLike(Protocol):
    """Subset of :class:`mcp.ClientSession` we depend on.

    Keeping this narrow lets tests inject fakes without depending on
    the full SDK type hierarchy. Production wires the real
    ``ClientSession`` here.
    """

    async def initialize(self) -> Any: ...

    async def list_resources(
        self, cursor: str | None = None
    ) -> Any: ...

    async def read_resource(self, uri: Any) -> Any: ...


SessionFactory = Callable[
    [MCPServerConfig, SecretBundle],
    AbstractAsyncContextManager[MCPSessionLike],
]
"""Factory yielding an authenticated MCP session for a (config, secrets)
pair. Production binds this to a Streamable-HTTP transport; tests
inject an in-memory fake."""


# ---------------------------------------------------------------------------
# MCPConnector — the Connector Protocol implementation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MCPHandleExtra:
    """What ``MCPConnector.authenticate`` stuffs into ``AuthHandle.extra``.

    Frozen + dataclass for documentary clarity; the runtime stores it
    as a plain ``dict[str, Any]`` per the AuthHandle contract.
    """

    server_url: str
    secrets: dict[str, Any] = field(default_factory=dict)
    config_kind: str = ""


class MCPConnector(Connector):
    """Connector backed by an MCP server.

    Configured per-instance with a :class:`MCPServerConfig`. The
    canonical ``kind`` is ``"mcp"`` — presets register themselves as
    e.g. ``"mcp:notion"``, ``"mcp:atlassian"``. Each preset is a
    subclass that fixes ``server_config`` at class level.

    Status defaults to ``"preview"`` because MCP servers are external
    dependencies whose schemas can drift; per-preset ``status`` may
    override (e.g. ``"production"`` for vendor-GA servers like
    Notion / Atlassian / Linear).
    """

    kind: ClassVar[str] = "mcp"
    capability: ClassVar[set[Capability]] = {"discover", "profile", "sample"}
    classification_hints: ClassVar[list[ClassificationHint]] = []
    status: ClassVar[ConnectorStatus] = "preview"
    status_note: ClassVar[str] = (
        "MCP-backed source. Connect any MCP server (OAuth 2.1 or bearer "
        "token); discover/profile/sample work today, watch is request/"
        "response in v1."
    )

    # ----- Class-level binding to a concrete server config -------------

    server_config: ClassVar[MCPServerConfig | None] = None
    """Set by per-server preset subclasses. Generic ``MCPConnector`` is
    not directly registrable — you instantiate it with a config-bound
    subclass produced by :func:`make_mcp_preset`."""

    def __init__(
        self,
        *,
        config: MCPServerConfig | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        cfg = config or self.server_config
        if cfg is None:
            raise ValueError(
                "MCPConnector requires a MCPServerConfig (pass `config=` or "
                "use a preset subclass produced by make_mcp_preset)"
            )
        self._config = cfg
        self._session_factory = session_factory or _default_session_factory

    @property
    def config(self) -> MCPServerConfig:
        return self._config

    # ----- Connector Protocol methods ----------------------------------

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        """Validate the secret shape; return a stable handle.

        Does NOT open the MCP session — that happens lazily inside
        ``discover/profile/sample`` so authenticate stays cheap (the
        dashboard re-authenticates on every flow). The session-factory
        is responsible for the actual transport handshake.
        """
        cfg = self._config
        missing = [k for k in cfg.required_secrets if not secrets.payload.get(k)]
        if missing:
            raise ValueError(
                f"{cfg.kind} connector requires "
                f"{list(cfg.required_secrets)}; missing: {missing}"
            )
        # Stable handle id keyed off the first required secret + server URL.
        seed_key = cfg.required_secrets[0] if cfg.required_secrets else "url"
        seed_val = str(secrets.payload.get(seed_key, cfg.server_url)).encode()
        seed = seed_val + b"@" + cfg.server_url.encode()
        return AuthHandle(
            connector_kind=cfg.kind,
            handle_id=hashlib.sha256(seed).hexdigest()[:16],
            extra={
                "server_url": cfg.server_url,
                "secrets": dict(secrets.payload),
                "config_kind": cfg.kind,
            },
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        """Call upstream ``list_resources()`` and shape into ResourceProposals.

        MCP ``Resource`` carries (uri, name, description, mimeType,
        size); we map uri → ``resource_id``, name → ``name``, mimeType
        → ``metadata.mimetype``. Classification hints come from the
        preset config (file-extension or path-prefix patterns are NOT
        applied here — the preset is the authoritative source).
        """
        secrets = SecretBundle(payload=handle.extra.get("secrets", {}))
        proposals: list[ResourceProposal] = []
        async with self._session_factory(self._config, secrets) as session:
            await session.initialize()
            result = await session.list_resources()
            resources = list(getattr(result, "resources", []) or [])
        for res in resources:
            uri = _coerce_uri(getattr(res, "uri", None))
            if uri is None:
                continue
            name = getattr(res, "name", None) or uri
            description = getattr(res, "description", "") or ""
            mimetype = getattr(res, "mimeType", None)
            size = getattr(res, "size", None)
            classification_hint: str | None = None
            if self._config.classification_hints:
                classification_hint = self._config.classification_hints[0]
            metadata: dict[str, Any] = {
                "description": description,
                "uri": uri,
            }
            if mimetype is not None:
                metadata["mimetype"] = mimetype
            if size is not None:
                metadata["size_bytes"] = size
            proposals.append(
                ResourceProposal(
                    resource_id=uri,
                    name=name,
                    kind="endpoint",
                    classification_hint=classification_hint,
                    metadata=metadata,
                )
            )
        return proposals

    async def profile(
        self, handle: AuthHandle, resource_id: str
    ) -> Profile:
        """Call upstream ``read_resource(uri)`` to derive a Profile.

        MCP doesn't expose tabular schemas natively (the
        ``ReadResourceResult`` carries arbitrary text or blob bytes).
        We approximate: bytes-length, line-count for text resources, no
        column inference. The lake-builder's silver-promotion step is
        responsible for parsing the bytes into rows when the mimetype
        warrants it.
        """
        secrets = SecretBundle(payload=handle.extra.get("secrets", {}))
        async with self._session_factory(self._config, secrets) as session:
            await session.initialize()
            result = await session.read_resource(_to_any_url(resource_id))
        contents = list(getattr(result, "contents", []) or [])
        body_bytes, mimetype = _extract_body(contents)
        row_count = body_bytes.count(b"\n") if mimetype.startswith("text/") else None
        schema_hash = hashlib.sha256(
            (resource_id + ":" + mimetype).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=row_count,
            column_count=None,
            columns=[],
            schema_hash=schema_hash,
            extra={
                "resource_id": resource_id,
                "bytes": len(body_bytes),
                "mimetype": mimetype,
                "classification_hints": list(self._config.classification_hints),
            },
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        """Read the resource and return up to ``n`` bytes.

        ``n`` is a byte cap. MCP servers don't natively support
        byte-range reads; we read the whole resource and slice. Future
        Optimization opportunity: pass ``n`` as a server-side
        ``params`` hint when the upstream advertises pagination.
        """
        secrets = SecretBundle(payload=handle.extra.get("secrets", {}))
        async with self._session_factory(self._config, secrets) as session:
            await session.initialize()
            result = await session.read_resource(_to_any_url(resource_id))
        contents = list(getattr(result, "contents", []) or [])
        body_bytes, _ = _extract_body(contents)
        if n <= 0:
            return b""
        return body_bytes[:n]

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        """MCP is request/response in v1 (spec §6.4); yields nothing.

        Reactivity for MCP-backed sources is polled by ``lake_discovery``
        cron rather than push-driven. Once MCP elicitation/tasks land
        (2026 roadmap), this becomes a ``subscribe_resource`` loop.
        """
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]


# ---------------------------------------------------------------------------
# Preset-class factory — produces a registrable subclass per server
# ---------------------------------------------------------------------------


def make_mcp_preset(
    config: MCPServerConfig,
    *,
    status: ConnectorStatus = "preview",
    status_note: str | None = None,
    register: bool = True,
) -> type[MCPConnector]:
    """Build a per-server MCPConnector subclass and (optionally) register it.

    Each preset module calls ``make_mcp_preset(MY_CFG)`` once at import
    time; the returned class self-registers via ``register_connector``
    so the dashboard's connector picker sees it alongside the native
    connectors. Skipping registration is supported for tests that want
    to assert the class shape without polluting the default registry.
    """
    cls_name = "MCPConnector_" + _safe_class_suffix(config.kind)
    note = status_note or (
        f"MCP-backed connector for {config.kind!s}. {config.description}".strip()
    )

    cls = type(
        cls_name,
        (MCPConnector,),
        {
            "__doc__": f"MCP preset for {config.kind} ({config.server_url}).",
            "kind": config.kind,
            "server_config": config,
            "status": status,
            "status_note": note,
            "classification_hints": list(config.classification_hints),
        },
    )
    if register:
        register_connector(cls)  # type: ignore[arg-type]
    return cls  # type: ignore[return-value]


def _safe_class_suffix(kind: str) -> str:
    """Convert ``mcp:notion`` → ``mcp_notion`` for valid class names."""
    return "".join(ch if ch.isalnum() else "_" for ch in kind)


# ---------------------------------------------------------------------------
# Default session factory — Streamable HTTP transport
# ---------------------------------------------------------------------------


def _default_session_factory(
    config: MCPServerConfig,
    secrets: SecretBundle,
) -> AbstractAsyncContextManager[MCPSessionLike]:
    """Open a Streamable-HTTP MCP session against ``config.server_url``.

    Lazy-imports the ``mcp`` SDK so the rest of the connector surface
    doesn't pay the import cost when MCP isn't in use. Tests inject
    a fake factory; production wires this via the SecretBundle bearer
    token carried as the ``Authorization`` header.
    """
    return _StreamableHttpSession(config, secrets)


class _StreamableHttpSession(AbstractAsyncContextManager["MCPSessionLike"]):
    """Async context manager wrapping the SDK transport + ClientSession.

    Kept as a thin wrapper so the test path can substitute a fake
    factory without monkey-patching the SDK. Production users invoke
    this via :func:`_default_session_factory`.
    """

    def __init__(
        self, config: MCPServerConfig, secrets: SecretBundle
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._transport_cm: AbstractAsyncContextManager[Any] | None = None
        self._session_cm: AbstractAsyncContextManager[Any] | None = None
        self._session: MCPSessionLike | None = None

    async def __aenter__(self) -> MCPSessionLike:
        # Lazy import — the rest of the connectors package shouldn't
        # pay this cost, and the SDK has a non-trivial import graph.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = _bearer_headers(self._secrets)
        self._transport_cm = streamablehttp_client(
            url=self._config.server_url,
            headers=headers,
        )
        read_stream, write_stream, _close = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()  # type: ignore[assignment]
        return self._session  # type: ignore[return-value]

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
            self._session_cm = None
        if self._transport_cm is not None:
            await self._transport_cm.__aexit__(exc_type, exc, tb)
            self._transport_cm = None


def _bearer_headers(secrets: SecretBundle) -> dict[str, str]:
    """Build the ``Authorization`` header from the SecretBundle.

    Accepts either ``bearer_token`` (OAuth-issued) or ``api_key``
    (vendor-issued). Returns an empty dict when neither is present —
    the upstream will reject the call and the surrounding code will
    surface the failure honestly.
    """
    token = secrets.payload.get("bearer_token") or secrets.payload.get("api_key")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_uri(uri: Any) -> str | None:
    """Best-effort coerce an MCP Resource ``uri`` into a string id."""
    if uri is None:
        return None
    if isinstance(uri, str):
        return uri
    # pydantic AnyUrl / similar — str() yields canonical form.
    return str(uri)


def _to_any_url(resource_id: str) -> Any:
    """Coerce a string resource_id into the SDK's expected URL type.

    The SDK validates URIs as ``pydantic.networks.AnyUrl``. We import
    it lazily for the same reason as the session factory: keep the
    SDK out of the import-time graph for non-MCP code paths.
    """
    try:
        from pydantic import AnyUrl
    except ImportError:  # pragma: no cover — pydantic is a hard dep
        return resource_id
    return AnyUrl(resource_id)


def _extract_body(
    contents: list[Any],
) -> tuple[bytes, str]:
    """Pull text or blob bytes out of a ReadResourceResult.contents list.

    MCP's contents list mixes ``TextResourceContents`` (with ``text``)
    and ``BlobResourceContents`` (with base64 ``blob``). We
    concatenate text resources as utf-8 bytes; blob resources are
    base64-decoded. Mimetype is the first non-empty value seen.
    """
    import base64

    parts: list[bytes] = []
    mimetype = ""
    for c in contents:
        text = getattr(c, "text", None)
        blob = getattr(c, "blob", None)
        mt = getattr(c, "mimeType", None)
        if not mimetype and mt:
            mimetype = str(mt)
        if text is not None:
            parts.append(str(text).encode("utf-8"))
        elif blob is not None:
            try:
                parts.append(base64.b64decode(str(blob)))
            except (ValueError, TypeError):
                parts.append(str(blob).encode("utf-8"))
    if not mimetype:
        mimetype = "application/octet-stream"
    return b"".join(parts), mimetype


__all__ = [
    "MCPConnector",
    "MCPServerConfig",
    "MCPSessionLike",
    "SessionFactory",
    "make_mcp_preset",
]
