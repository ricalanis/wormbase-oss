"""Sampler activation Wave — ``SourceHandleProvider`` Protocol + ledger impl.

Bridges the L3 / L5 / L8 lake-side strategies' ``SamplerProtocol`` to the
production ``Connector.sample()`` surface. The provider answers
"for ``(company_id, source_id)``, what's the ``(connector_kind, auth_handle,
resource_map)`` I need to call the right connector?"

Today's source-pipeline ledger entries (``source_proposed`` →
``source_confirmed`` → ``source_connected`` → ``source_profiled``) carry
``source_kind`` + ``uri`` (on proposed), ``connection_ref`` + optional
``credential_ref`` (on connected).

Two reconstruction paths:

  * **Path-shaped / DSN-shaped connectors** (``csv_local``, ``postgres``,
    ``snowflake``, ``bigquery``, ``s3_csv``, ``http_csv``) — the URI IS
    the credential. ``_reconstruct_auth_handle_from_uri`` builds the
    handle deterministically from ``source_proposed.uri``.

  * **Opaque-secret connectors** (``stripe``, ``salesforce``,
    ``hubspot``, ``gsheets``, ``mcp:*``) — the URI is non-credential;
    the real secret material lives in a :class:`CredentialBroker` (Vault,
    Env, future KMS). When the broker is wired AND
    ``source_connected.credential_ref`` is set, the provider calls
    :meth:`CredentialBroker.hold_data_account` and threads the resolved
    secret payload through :data:`_OPAQUE_AUTH_HANDLE_ASSEMBLERS` per
    connector kind. When the broker is None OR ``credential_ref`` is
    missing, the provider returns ``None`` and the sampler falls back to
    honest-empty samples (preserves Sampler activation default-OFF
    behavior).

Reuses the same ledger-walk pattern as
:mod:`wormbase_core.lineage_catalog_reader` —
``_is_emit_tool`` / ``_execute_args`` helpers, oldest-first fold,
most-recent-wins per source_id.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

logger = logging.getLogger("wormbase_core.source_handle_provider")

__all__ = [
    "LedgerSourceHandleProvider",
    "NON_OPAQUE_CONNECTOR_KINDS",
    "OPAQUE_AUTH_HANDLE_ASSEMBLERS",
    "SourceHandleProvider",
    "SourceHandleRecord",
]


class _LedgerFetcher(Protocol):
    """Minimal Ledger-like surface this module needs.

    Matches the shape in :mod:`wormbase_core.lineage_catalog_reader` so
    both modules can take the same ``ledger`` argument structurally.
    """

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


class _CredentialBrokerProtocol(Protocol):
    """The slice of :class:`CredentialBroker` this module consumes.

    Matches :meth:`wormbase_agent_gateway.credential_broker.CredentialBroker.hold_data_account`
    structurally so this module can take any conforming broker without
    importing the agent-gateway package at module-load time.
    """

    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str,
    ) -> Any: ...  # pragma: no cover


@dataclass(frozen=True)
class SourceHandleRecord:
    """The materialised result of a successful
    :meth:`SourceHandleProvider.get_handle` lookup.

    Carries everything :class:`wormbase_core.connector_sampler.ConnectorSampler`
    needs to drive a per-source ``Connector.sample()`` call:

      * ``source_id`` — the tenant-scoped source UUID.
      * ``connector_kind`` — registry key (``"csv_local"`` / ``"postgres"``
        / ``"snowflake"`` / ...). Looked up against
        :func:`wormbase_connectors.registry.default_registry`.
      * ``auth_handle`` — opaque blob the connector kind understands.
        For csv_local this is an :class:`AuthHandle` reconstructed from
        the source's ``uri``; for DSN-backed connectors it carries the
        DSN; for opaque-secret connectors it carries the broker-resolved
        secret payload assembled per connector kind. Never logged.
      * ``resource_map`` — ``{table_id: resource_id}`` mapping the
        L3/L5/L8 callers' ``table_id`` to the connector-internal
        ``resource_id`` understood by ``Connector.sample``. Today's
        single-table connectors (csv_local) map their lone resource
        under the ``uri`` key, mirroring how
        :meth:`wormbase_connectors.csv_local.CsvLocalConnector.discover`
        returns ``resource_id = str(path)``.
    """

    source_id: str
    connector_kind: str
    auth_handle: object
    resource_map: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class SourceHandleProvider(Protocol):
    """Looks up ``(company_id, source_id)`` → handle record.

    Implementations are tenant-aware (the ``company_id`` leg scopes the
    ledger walk). Returns ``None`` when the source is not connected or
    its handle is unavailable — :class:`ConnectorSampler` interprets
    ``None`` as "fall back to honest empty samples".
    """

    async def get_handle(
        self, *, company_id: UUID, source_id: str,
    ) -> SourceHandleRecord | None: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Ledger walk helpers (mirror ``lineage_catalog_reader``)
# ---------------------------------------------------------------------------


def _is_emit_tool(entry: dict[str, Any], tool: str) -> bool:
    """True iff this is an ``execute`` entry whose payload.tool matches ``tool``."""
    if entry.get("kind") != "execute":
        return False
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return False
    return payload.get("tool") == tool


def _execute_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``args`` dict from an execute entry's payload."""
    if entry.get("kind") != "execute":
        return {}
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return {}
    return args


# ---------------------------------------------------------------------------
# Connector classification — opaque-secret vs URI-shaped
# ---------------------------------------------------------------------------


#: Connector kinds whose authentication is fully reconstructable from the
#: ``source_proposed.uri`` alone (path-shaped, DSN-shaped, URL-shaped). These
#: never require :class:`CredentialBroker` resolution; pre-existing csv_local
#: / postgres / snowflake / bigquery / s3_csv / http_csv handle paths route
#: through :func:`_reconstruct_auth_handle_from_uri`.
NON_OPAQUE_CONNECTOR_KINDS: frozenset[str] = frozenset({
    "csv_local",
    "postgres",
    "snowflake",
    "bigquery",
    "s3_csv",
    "http_csv",
})


def _reconstruct_auth_handle_from_uri(
    *, connector_kind: str, uri: str,
) -> object | None:
    """Re-build an ``AuthHandle`` for URI-shaped connectors.

    Returns ``None`` only when the late ``wormbase_connectors`` import
    fails (shouldn't happen in production); otherwise always returns a
    real handle — these connector kinds are deterministically
    reconstructable from ``uri`` alone.
    """
    try:
        from wormbase_connectors.types import AuthHandle
    except ImportError:
        return None

    if connector_kind == "csv_local":
        return AuthHandle(
            connector_kind=connector_kind,
            handle_id=uri,
            extra={"path": uri},
        )

    if connector_kind in {"postgres", "snowflake", "bigquery"}:
        return AuthHandle(
            connector_kind=connector_kind,
            handle_id=uri,
            extra={"dsn": uri},
        )

    if connector_kind in {"s3_csv", "http_csv"}:
        return AuthHandle(
            connector_kind=connector_kind,
            handle_id=uri,
            extra={"url": uri},
        )

    return None


# ---------------------------------------------------------------------------
# Opaque-secret AuthHandle assembly — per-kind dict-dispatch
# ---------------------------------------------------------------------------
#
# Mirrors the ``catalog_column_extractors`` per-kind registry pattern (per
# 2026-06-10 "Per-connector extractor bundle"). Each entry maps a
# connector kind to a callable that takes the broker-resolved secret
# payload (``dict[str, Any]``) + the source's ``uri`` and returns an
# ``AuthHandle`` shaped exactly as the connector's ``authenticate()``
# would have produced. The connector's own ``sample()`` then consumes
# the handle verbatim.


def _assemble_stripe_handle(
    *, secret_payload: Mapping[str, Any], uri: str,  # noqa: ARG001
) -> object | None:
    """Assemble a stripe AuthHandle from broker-resolved secrets.

    Matches :meth:`wormbase_connectors.stripe.StripeConnector.authenticate`
    output shape: ``handle.extra`` carries ``api_key``, optional
    ``api_version``, and the precomputed ``auth_header`` so the
    connector's HTTP path runs verbatim.
    """
    try:
        from wormbase_connectors.stripe import _basic_auth_header
        from wormbase_connectors.types import AuthHandle
    except ImportError:
        return None
    import hashlib

    api_key = secret_payload.get("api_key")
    if not api_key or not isinstance(api_key, str):
        logger.debug("stripe broker payload missing api_key; honest-empty")
        return None
    api_version = secret_payload.get("api_version")
    return AuthHandle(
        connector_kind="stripe",
        handle_id=hashlib.sha256(api_key.encode()).hexdigest()[:16],
        extra={
            "api_key": api_key,
            "api_version": api_version,
            "auth_header": _basic_auth_header(api_key),
        },
    )


def _assemble_salesforce_handle(
    *, secret_payload: Mapping[str, Any], uri: str,  # noqa: ARG001
) -> object | None:
    """Assemble a salesforce AuthHandle from broker-resolved secrets.

    Matches :class:`wormbase_connectors.salesforce.SalesforceConnector`'s
    ``required_secrets = ("instance_url", "access_token")`` contract.
    Since SalesforceConnector is :class:`SkeletalConnector`, its
    ``sample()`` raises ``NotImplementedError`` today — the handle is
    still assembled so when the production impl lands, the broker path
    is already wired.
    """
    try:
        from wormbase_connectors.types import AuthHandle
    except ImportError:
        return None
    import hashlib

    instance_url = secret_payload.get("instance_url")
    access_token = secret_payload.get("access_token")
    if not instance_url or not access_token:
        logger.debug(
            "salesforce broker payload missing instance_url or "
            "access_token; honest-empty",
        )
        return None
    seed = str(access_token).encode()
    return AuthHandle(
        connector_kind="salesforce",
        handle_id=hashlib.sha256(seed).hexdigest()[:16],
        extra={
            "secrets": dict(secret_payload),
            "instance_url": instance_url,
            "access_token": access_token,
        },
    )


def _assemble_hubspot_handle(
    *, secret_payload: Mapping[str, Any], uri: str,  # noqa: ARG001
) -> object | None:
    """Assemble a hubspot AuthHandle from broker-resolved secrets.

    Matches :class:`wormbase_connectors.hubspot.HubspotConnector`'s
    ``required_secrets = ("access_token",)`` contract.
    """
    try:
        from wormbase_connectors.types import AuthHandle
    except ImportError:
        return None
    import hashlib

    access_token = secret_payload.get("access_token")
    if not access_token or not isinstance(access_token, str):
        logger.debug("hubspot broker payload missing access_token; honest-empty")
        return None
    return AuthHandle(
        connector_kind="hubspot",
        handle_id=hashlib.sha256(access_token.encode()).hexdigest()[:16],
        extra={"secrets": dict(secret_payload), "access_token": access_token},
    )


def _assemble_gsheets_handle(
    *, secret_payload: Mapping[str, Any], uri: str,  # noqa: ARG001
) -> object | None:
    """Assemble a gsheets AuthHandle from broker-resolved secrets.

    Matches :class:`wormbase_connectors.gsheets.GsheetsConnector`'s
    ``required_secrets = ("service_account_json",)`` contract.
    """
    try:
        from wormbase_connectors.types import AuthHandle
    except ImportError:
        return None
    import hashlib

    sa_json = secret_payload.get("service_account_json")
    if not sa_json or not isinstance(sa_json, str):
        logger.debug(
            "gsheets broker payload missing service_account_json; honest-empty",
        )
        return None
    return AuthHandle(
        connector_kind="gsheets",
        handle_id=hashlib.sha256(sa_json.encode()).hexdigest()[:16],
        extra={
            "secrets": dict(secret_payload),
            "service_account_json": sa_json,
        },
    )


#: Per-kind dispatch table. Each callable accepts ``(secret_payload, uri)``
#: kwargs and returns either an ``AuthHandle`` (success) or ``None``
#: (broker payload malformed for this kind → honest-empty fallback).
#:
#: ``mcp:*`` connector kinds are NOT registered here — the MCP connector
#: family is preset-driven and a single dispatch entry would not cover the
#: per-preset secret-shape variance. MCP broker integration is deferred
#: until MCP server presets that need broker-held bearer tokens land in
#: production (today's MCP servers are dev-mode bearer-via-env).
OPAQUE_AUTH_HANDLE_ASSEMBLERS: dict[
    str, Callable[..., object | None]
] = {
    "stripe": _assemble_stripe_handle,
    "salesforce": _assemble_salesforce_handle,
    "hubspot": _assemble_hubspot_handle,
    "gsheets": _assemble_gsheets_handle,
}


def _resource_map_for_kind(
    *, connector_kind: str, uri: str,  # noqa: ARG001
) -> dict[str, str]:
    """Best-effort ``{table_id: resource_id}`` map.

    For single-resource connectors (csv_local, http_csv) the resource_id
    IS the URI; the table_id at the L3/L5/L8 strategy layer is the same
    URI string (the catalog mirror's per-source lineage edges use the
    same path token). For multi-resource connectors (postgres, snowflake,
    bigquery) the catalog mirror's ``external_lineage_imported`` edges
    expand to fully-qualified ``schema.table`` ids that the connector's
    own ``Connector.sample`` call accepts as ``resource_id`` verbatim —
    so the identity map suffices.

    The map is consulted by :class:`ConnectorSampler.sample_column`; a
    missing ``table_id`` falls back to identity (table_id ≡ resource_id),
    which is the right answer for the canonical case.
    """
    return {uri: uri}


# ---------------------------------------------------------------------------
# Production SourceHandleProvider — ledger-backed
# ---------------------------------------------------------------------------


@dataclass
class LedgerSourceHandleProvider:
    """Reads ``source_proposed`` + ``source_connected`` ledger entries to
    reconstruct per-source connector handles.

    Walks ledger entries oldest-first; for each ``source_id`` keeps the
    most-recent ``source_proposed`` (carrying ``source_kind`` + ``uri``)
    and the most-recent ``source_connected`` (which advances the source's
    lifecycle status, carrying ``connection_ref`` + optional
    ``credential_ref``). Returns a :class:`SourceHandleRecord` only when
    BOTH entries are present (i.e. the source has reached the
    ``connected`` state) AND a handle can be reconstructed for the
    connector kind.

    Reconstruction paths:

      * **URI-shaped** kinds in :data:`NON_OPAQUE_CONNECTOR_KINDS`:
        :func:`_reconstruct_auth_handle_from_uri` builds the handle from
        ``uri`` alone. Broker not consulted.
      * **Opaque-secret** kinds with an entry in
        :data:`OPAQUE_AUTH_HANDLE_ASSEMBLERS`: when ``credential_broker``
        is wired AND ``source_connected.credential_ref`` is set, the
        provider calls
        :meth:`CredentialBroker.hold_data_account(credential_ref, upstream_kind=kind)`
        and threads the resolved payload through the per-kind assembler.
      * **Unknown** kinds OR opaque kinds without broker/credential_ref
        AND wholly missing dispatch entries: return ``None`` —
        :class:`ConnectorSampler` falls back to honest-empty samples.

    Tenant isolation rides on ``ledger.fetch(company_id)`` — same pattern
    as :class:`LedgerCatalogReader` / :class:`LedgerDbtManifestReader`.

    Constructor args:

      * ``ledger`` — required; the tenant-aware fetch surface.
      * ``credential_broker`` — optional :class:`CredentialBroker`. When
        ``None`` (default), opaque-secret connectors return ``None``
        from :meth:`get_handle`, preserving Sampler activation
        default-OFF behavior. When supplied, opaque-secret kinds with a
        registered assembler and a credential_ref become productive.
      * ``install_id`` — optional override for the install_id passed to
        ``broker.hold_data_account``. When ``None`` (default), the
        ``credential_ref`` from ``source_connected`` is used directly
        (the canonical case: broker secret slots are keyed by
        credential_ref). The override exists for tenants that share a
        broker install_id across multiple credential refs.
    """

    ledger: _LedgerFetcher
    credential_broker: _CredentialBrokerProtocol | None = None
    install_id: str | None = None

    async def get_handle(
        self, *, company_id: UUID, source_id: str,
    ) -> SourceHandleRecord | None:
        """Return the handle record for ``source_id``, or ``None``.

        The ``source_id`` argument is matched against the ledger via
        TWO strategies, in order:

          1. Exact match against the ``source_id`` field in
             ``source_proposed`` entries (production source-pipeline
             lookups — the L1 cascade emits real source UUIDs).
          2. Fallback: exact match against the ``uri`` field. This
             accommodates the L3/L5/L8 catalog-mirror substrate where
             the strategies pass the catalog's ``table_id`` token (which
             for single-resource connectors like ``csv_local`` /
             ``http_csv`` IS the source's URI). The token-as-uri match
             unblocks the Sampler activation Wave without requiring the
             catalog mirror to emit a new table_id↔source_id index.

        Returns ``None`` when:

          * The source has no entries for this tenant under either
            strategy.
          * The source is in ``proposed`` / ``confirmed`` but not yet
            ``connected`` (handle not yet meaningful).
          * The connector kind is opaque-secret AND the broker is not
            wired / no ``credential_ref`` is on the connected entry /
            the broker resolve failed / the per-kind assembler returns
            None. Sampler then falls back to empty per-source.
        """
        entries = await self.ledger.fetch(company_id)
        target = str(source_id)

        # First-pass fold: build a per-(internal-source-id) view of the
        # proposed + connected state. Most-recent-wins per field.
        # Index also keys by URI so a uri-shaped ``source_id`` arg
        # resolves to the same record.
        state: dict[str, dict[str, Any]] = {}
        uri_to_sid: dict[str, str] = {}

        for entry in entries:
            if _is_emit_tool(entry, "emit_source_proposed"):
                args = _execute_args(entry)
                sid = str(args.get("source_id") or "")
                if not sid:
                    continue
                rec = state.setdefault(
                    sid,
                    {
                        "source_kind": None,
                        "uri": None,
                        "connection_ref": None,
                        "credential_ref": None,
                        "is_connected": False,
                    },
                )
                rec["source_kind"] = str(args.get("source_kind") or "") or None
                rec["uri"] = str(args.get("uri") or "") or None
                if rec["uri"]:
                    uri_to_sid[rec["uri"]] = sid
                continue
            if _is_emit_tool(entry, "emit_source_connected"):
                args = _execute_args(entry)
                sid = str(args.get("source_id") or "")
                if not sid:
                    continue
                rec = state.setdefault(
                    sid,
                    {
                        "source_kind": None,
                        "uri": None,
                        "connection_ref": None,
                        "credential_ref": None,
                        "is_connected": False,
                    },
                )
                rec["connection_ref"] = (
                    str(args.get("connection_ref") or "") or None
                )
                # Additive (2026-06-10) — None when the entry pre-dates the
                # field or the connector kind doesn't need broker resolution.
                cred_ref_raw = args.get("credential_ref")
                rec["credential_ref"] = (
                    str(cred_ref_raw) if cred_ref_raw else None
                )
                rec["is_connected"] = True
                continue

        # Resolution: source_id match first, then URI fallback.
        resolved_sid: str | None = None
        if target in state:
            resolved_sid = target
        elif target in uri_to_sid:
            resolved_sid = uri_to_sid[target]
        if resolved_sid is None:
            return None

        rec = state[resolved_sid]
        if not rec["is_connected"]:
            return None
        source_kind = rec["source_kind"]
        uri = rec["uri"]
        if not source_kind or not uri:
            logger.debug(
                "source_connected for source_id=%s in tenant=%s "
                "lacks an earlier source_proposed; skipping handle "
                "reconstruction.", resolved_sid, company_id,
            )
            return None

        auth_handle = await self._reconstruct_auth_handle(
            connector_kind=source_kind,
            uri=uri,
            connection_ref=rec["connection_ref"] or uri,
            credential_ref=rec["credential_ref"],
        )
        if auth_handle is None:
            logger.debug(
                "connector_kind=%s for source_id=%s has no reconstructable "
                "handle (opaque-secret without broker/credential_ref, or "
                "unknown kind). Returning None so sampler falls back to "
                "empty.", source_kind, resolved_sid,
            )
            return None

        return SourceHandleRecord(
            source_id=resolved_sid,
            connector_kind=source_kind,
            auth_handle=auth_handle,
            resource_map=_resource_map_for_kind(
                connector_kind=source_kind, uri=uri,
            ),
        )

    async def _reconstruct_auth_handle(
        self,
        *,
        connector_kind: str,
        uri: str,
        connection_ref: str,  # noqa: ARG002 — reserved for future routing
        credential_ref: str | None,
    ) -> object | None:
        """Pick the right reconstruction path for ``connector_kind``.

        URI-shaped kinds (csv_local, postgres, snowflake, bigquery,
        s3_csv, http_csv): reconstruct from ``uri`` alone. Broker not
        consulted.

        Opaque-secret kinds (stripe, salesforce, hubspot, gsheets) with
        a registered assembler: resolve secrets via
        :meth:`CredentialBroker.hold_data_account` and dispatch to the
        per-kind assembler. Returns ``None`` when:

          * broker is None
          * credential_ref is None (no broker slot to look up)
          * broker.hold_data_account raises
          * per-kind assembler returns None (payload malformed for kind)

        Unknown kinds: return ``None``.
        """
        if connector_kind in NON_OPAQUE_CONNECTOR_KINDS:
            return _reconstruct_auth_handle_from_uri(
                connector_kind=connector_kind, uri=uri,
            )

        assembler = OPAQUE_AUTH_HANDLE_ASSEMBLERS.get(connector_kind)
        if assembler is None:
            return None

        if self.credential_broker is None:
            logger.debug(
                "credential_broker not wired for opaque-secret kind=%s; "
                "honest-empty fallback (Sampler activation default-OFF "
                "behaviour preserved)", connector_kind,
            )
            return None

        if not credential_ref:
            logger.debug(
                "opaque-secret kind=%s has no credential_ref on "
                "source_connected; cannot resolve via broker; honest-empty",
                connector_kind,
            )
            return None

        # The install_id arg to hold_data_account is the broker's secret-slot
        # key. By default we use credential_ref directly (the canonical
        # per-credential slot); the constructor override lets multi-tenant
        # SaaS deploys share one install_id across many credential refs.
        broker_install_id = self.install_id or credential_ref
        try:
            handle = await self.credential_broker.hold_data_account(
                broker_install_id, upstream_kind=connector_kind,
            )
        except Exception as exc:  # noqa: BLE001 — defensive boundary
            logger.warning(
                "credential_broker.hold_data_account raised for "
                "kind=%s credential_ref=%s: %s; honest-empty fallback",
                connector_kind, credential_ref, exc,
            )
            return None

        secret_payload = getattr(handle, "payload", None)
        if not isinstance(secret_payload, dict):
            logger.debug(
                "broker returned non-dict payload (%s) for kind=%s; "
                "honest-empty", type(secret_payload).__name__, connector_kind,
            )
            return None

        return assembler(secret_payload=secret_payload, uri=uri)
