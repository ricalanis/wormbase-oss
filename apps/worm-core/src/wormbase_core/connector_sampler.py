"""Sampler activation Wave — ``ConnectorSampler`` bridge.

Bridges the :class:`wormbase_agent_gateway.lineage.SamplerProtocol`
shape — called by L3 ``SampleOverlapStrategy``, L5
``ValuePatternFingerprintStrategy``, and L8
``SampleOverlapEntityStrategy`` — to the
:meth:`wormbase_lake_surfaces.Connector.sample` surface.

The bridge is default-OFF: instantiation only happens in
``agent_gateway_construction.compose_*_reactivity_if_enabled`` when
``WORMBASE_SAMPLER_ACTIVATION_ENABLED=true``. With the env knob unset
the construction sites use :class:`NoopSampler` and the strategies see
exactly the byte-identical behaviour as today.

Per-source graceful fallback: when the
:class:`SourceHandleProvider` returns ``None`` (source not connected /
opaque-secret connector kind), the bridge returns ``set()`` for that
table — preserving the strategies' honest-stub posture per-source
rather than crashing or globally falling back.

Tenant scope: the bridge is constructed once per install with
``company_id`` bound; the same instance answers every
:meth:`sample_column` call for that tenant. Multi-tenant deployments
get one instance per tenant via the per-install construction path.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from io import StringIO
from typing import Any
from uuid import UUID

from wormbase_core.source_handle_provider import SourceHandleProvider

logger = logging.getLogger("wormbase_core.connector_sampler")

__all__ = ["ConnectorSampler"]


# Hard cap on sample size — safety net against pathological strategy
# inputs (e.g. accidental sample_size=10_000_000). Strategies' caller
# defaults are 20 (L5) / 200 (L8) / 1000 (L3); the cap is well above
# all three. Tunable via ``WORMBASE_SAMPLER_MAX_N`` env knob at
# construction time, NOT per-call.
DEFAULT_MAX_SAMPLE_N: int = 1000


def _parse_csv_column(raw: bytes, column: str, *, n: int) -> set[str]:
    """Parse CSV/TSV bytes; return distinct non-null values for ``column``.

    Handles both CSV (RFC 4180) and TSV (tab-delimited) via stdlib's
    :mod:`csv` Sniffer fallback. Returns empty set on:

      * Empty bytes.
      * Missing column header in row.
      * Pure-empty values for the requested column (the strategies want
        DISTINCT non-null values; empty strings are treated as null
        consistent with :class:`SampleOverlapStrategy`'s
        ``value_richness`` semantics).

    The cap at ``n`` honours the strategy's requested sample size —
    when the underlying file has more rows than ``n``, we slice the
    distinct-value set to ``n`` items (deterministic ordering by
    insertion).
    """
    if not raw:
        return set()
    try:
        text = raw.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return set()
    if not text:
        return set()
    sio = StringIO(text)
    try:
        # Sniff delimiter from the first 1KB so TSV streams parse cleanly.
        sample_for_sniff = text[:1024]
        dialect = csv.Sniffer().sniff(sample_for_sniff, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel  # default to comma-delimited
    reader = csv.DictReader(sio, dialect=dialect)
    if not reader.fieldnames or column not in reader.fieldnames:
        logger.debug(
            "column=%r not in CSV header %r; returning empty",
            column, reader.fieldnames,
        )
        return set()
    out: list[str] = []
    seen: set[str] = set()
    for row in reader:
        if len(out) >= n:
            break
        val = row.get(column)
        if val is None:
            continue
        val = str(val).strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return set(out)


@dataclass
class ConnectorSampler:
    """SamplerProtocol-compatible bridge to ``Connector.sample()``.

    Constructed per install (tenant-scoped via bound ``company_id``).
    The L3 / L5 / L8 strategies call :meth:`sample_column` /
    :meth:`estimate_table_size` without knowing whether the underlying
    sampler is a :class:`NoopSampler` or a :class:`ConnectorSampler` —
    the env knob picks the impl at construction time.
    """

    handle_provider: SourceHandleProvider
    company_id: UUID
    # Optional override; defaults to ``wormbase_lake_surfaces.default_registry``
    # at first lookup. Injectable for tests.
    connector_registry: Any | None = None
    max_sample_n: int = DEFAULT_MAX_SAMPLE_N

    # Per-instance cache so concurrent strategy calls share lookups for
    # the same source_id within a single inference pass. Keyed by
    # source_id; value is the resolved SourceHandleRecord or None.
    _handle_cache: dict[str, Any | None] = field(default_factory=dict)

    def _registry(self) -> Any:
        if self.connector_registry is not None:
            return self.connector_registry
        # Late import so worm-core test runs that don't touch the
        # connector registry don't pay the import cost.
        from wormbase_lake_surfaces.registry import default_registry
        return default_registry()

    def _source_id_for_table(self, table_id: str) -> str:
        """Best-effort extraction of ``source_id`` from a ``table_id``.

        The L3 / L5 / L8 catalog-mirror substrate uses table_ids that
        encode the owning source as their leading segment (the
        ``external_lineage_imported`` edge tuples carry connector-internal
        fully-qualified names that mirror the source's URI).

        For single-resource connectors (``csv_local``, ``http_csv``,
        ``s3_csv``) the table_id IS the URI which IS the source's
        connection_ref — so we return it verbatim and the handle
        provider's lookup will find the right source_proposed entry.

        For multi-resource connectors (``postgres``, ``snowflake``,
        ``bigquery``) the lineage edge token is typically
        ``<dsn>.<schema>.<table>`` or just ``<schema>.<table>``. Today's
        catalog mirror is honest-stubbed on these (per L3 wave docs),
        and the handle provider walks the full ledger for the
        identifying ``source_proposed`` — so returning the raw table_id
        falls back to "scan all sources for one whose uri matches the
        leading segment". The lookup either finds a match or returns
        None (→ empty samples), preserving honest-stub posture.

        When a future wave grows a per-tenant ``table_id → source_id``
        catalog mapping, swap this method for a lookup against that
        index. For Wave 1, raw-table_id-as-source-key is the right
        default.
        """
        return table_id

    async def _resolve_handle(self, table_id: str) -> Any | None:
        """Look up the handle for ``table_id`` (cached per instance).

        Cache key is the derived source_id (raw table_id today). Cache
        lives for the lifetime of this sampler instance — refreshed on
        instance reconstruction at the next compose wire.
        """
        source_id = self._source_id_for_table(table_id)
        if source_id in self._handle_cache:
            return self._handle_cache[source_id]
        try:
            record = await self.handle_provider.get_handle(
                company_id=self.company_id, source_id=source_id,
            )
        except Exception:  # noqa: BLE001 — defensive boundary; log + fall back
            logger.exception(
                "SourceHandleProvider.get_handle raised for source_id=%s "
                "tenant=%s; falling back to empty samples.",
                source_id, self.company_id,
            )
            record = None
        self._handle_cache[source_id] = record
        return record

    async def sample_column(
        self, table_id: str, column: str, n: int,
    ) -> set[str]:
        """Return up to ``min(n, max_sample_n)`` distinct non-null values.

        Per :class:`SamplerProtocol`. Honest-stub posture per-source:
        when the handle is unavailable / the connector kind unknown /
        the column not in the CSV header, returns ``set()`` and the
        strategy treats it as "no samples" (same as today's
        :class:`NoopSampler`).
        """
        capped_n = min(max(0, int(n)), self.max_sample_n)
        if capped_n == 0:
            return set()
        record = await self._resolve_handle(table_id)
        if record is None:
            return set()

        registry = self._registry()
        connector_cls = registry.get(record.connector_kind)
        if connector_cls is None:
            logger.debug(
                "connector kind=%r not in registry for source_id=%s; "
                "returning empty samples.",
                record.connector_kind, record.source_id,
            )
            return set()
        resource_id = record.resource_map.get(table_id) or table_id

        try:
            connector = connector_cls()
            raw = await connector.sample(
                record.auth_handle, resource_id, capped_n,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Connector.sample raised for kind=%s resource_id=%s "
                "tenant=%s; returning empty samples.",
                record.connector_kind, resource_id, self.company_id,
            )
            return set()

        if not isinstance(raw, (bytes, bytearray)):
            logger.debug(
                "Connector.sample returned non-bytes (%s) for kind=%s; "
                "returning empty.", type(raw).__name__, record.connector_kind,
            )
            return set()
        return _parse_csv_column(bytes(raw), column, n=capped_n)

    async def estimate_table_size(self, table_id: str) -> int:
        """Return a row-count estimate, or ``0`` when unknown.

        Per :class:`SamplerProtocol`. The L3
        :class:`SampleOverlapStrategy` uses this as a pre-filter
        (skip when size > ``max_table_size``); returning ``0`` is the
        honest "I don't know" answer that always passes the cap.

        Today's :class:`Connector` Protocol does not expose a size
        method; a future wave can grow ``Connector.size()`` and wire it
        here. For Wave 1 we always return 0 — strategies treat it as
        "unsampled" and proceed with per-column sampling.
        """
        del table_id  # unused; reserved for future per-connector hook
        return 0
