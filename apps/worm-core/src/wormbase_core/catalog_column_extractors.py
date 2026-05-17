"""Catalog-mirror Wave 2 Sub-wave B — connector-kind column extraction registry.

Connectors implement the canonical ``SurfaceDriver`` Protocol (discover /
profile / sample), but their native catalog metadata varies wildly:
csv_local exposes a flat header row, postgres exposes
``information_schema.columns``, snowflake exposes ``DESCRIBE TABLE``,
etc. Rather than churn the SurfaceDriver Protocol surface with a new
``catalog_columns`` method (which would force every connector — including
opaque-secret ones like Stripe / HubSpot — to implement an unused
method), we maintain a small worm-core-side dispatch registry that maps
``connector_kind`` → extraction function.

Each extractor function takes the same three inputs:

  * ``connector`` — the registered ``SurfaceDriver`` instance
  * ``handle`` — the authenticated AuthHandle
  * ``resource_id`` — the per-table identifier (matches the
    ``ResourceProposal.resource_id`` returned by ``SurfaceDriver.discover``)

and returns ``list[CatalogColumnSpec]`` — the per-column metadata as
typed by the Sub-wave A ledger payload. Extractors that lack column-
type introspection (csv_local does NOT infer types from samples for
catalog purposes — that's L5's territory) return ``CatalogColumnSpec``
records with ``type=None``.

The registry is the canonical extensibility seam for new connectors:
when a postgres connector ships an extractor, the same source-builder
emission path flips on for postgres sources without source-builder code
change. csv_local is the first connector wired end-to-end; postgres /
s3_csv / http_csv graduated in the per-connector extractor bundle
(2026-06-10). Other connector kinds (bigquery / gsheets / stripe /
salesforce / hubspot) fall through to the empty-list extractor (which
causes ``catalog_table_imported`` to emit with ``columns=()`` — the
honest empty-upstream posture preserved per-connector). The rationale
for those five honest-empty kinds is documented in the registry
docstrings further down this file.

Doctrine: this matches the Sampler activation Wave's bridge pattern
(``ConnectorSampler`` per-kind dispatch in
``connector_sampler.py``). Both are worm-core-side adapters that absorb
per-connector variance without touching the Protocol surface.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any

from wormbase_ledger.entries import CatalogColumnSpec

logger = logging.getLogger("wormbase_core.catalog_column_extractors")

__all__ = [
    "ColumnExtractor",
    "extract_columns",
    "register_column_extractor",
    "csv_local_extractor",
    "postgres_extractor",
    "s3_csv_extractor",
    "http_csv_extractor",
]


# Type alias — connector-kind dispatch surface.
ColumnExtractor = Callable[
    [Any, Any, str],  # (connector, handle, resource_id)
    "list[CatalogColumnSpec]",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_csv_header_bytes(raw: bytes) -> list[CatalogColumnSpec]:
    """Decode a CSV byte payload, split the first line as the header.

    Used by file-based connectors that fetch the first few KB of a CSV
    object (s3_csv, http_csv). Returns ``[]`` for empty payloads or
    when the header row is empty. Empty header cells are skipped — they
    would fail the :class:`CatalogColumnSpec` ``name`` validator
    downstream, and synthesizing names like ``__col_3`` has no upstream
    truth.

    Type info is NOT inferred — that's L5 fingerprinting's job. The
    catalog substrate carries ``type=None`` for raw-CSV-header derived
    columns, preserving the honest-empty-upstream posture for the type
    axis while still populating column names (so L2 ColumnSet /
    L8 SchemaShape get real signal).
    """
    if not raw:
        return []
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    if not text:
        return []
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    columns: list[CatalogColumnSpec] = []
    for raw_name in header:
        name = (raw_name or "").strip()
        if not name:
            continue
        columns.append(CatalogColumnSpec(name=name, type=None))
    return columns


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync extractor.

    Extractors are called from sync code paths (write_actions wraps the
    emit with no async boundary). The async connector methods (e.g.
    ``SurfaceDriver.sample()``) need a fresh event loop here. If a loop is
    already running (e.g. an async caller eventually wires this), fall
    back to ``asyncio.new_event_loop()`` + run-on-thread so we don't
    block the parent loop. For the current sync emission path this
    just delegates to ``asyncio.run``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)
    # A running loop exists; we cannot reuse it. Spin a private loop on
    # a worker thread. This is defensive — today's extractor callers
    # are synchronous, but the cost is one thread when async callers
    # graduate to wrapping the extractor in a thread executor.
    import concurrent.futures

    def _runner() -> Any:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_runner).result()


# ---------------------------------------------------------------------------
# csv_local extractor — reads the CSV header row.
# ---------------------------------------------------------------------------


def csv_local_extractor(
    connector: Any, handle: Any, resource_id: str,
) -> list[CatalogColumnSpec]:
    """Extract column specs for a csv_local resource.

    The CSV ``resource_id`` is the absolute file path (per
    :meth:`CsvLocalSurfaceDriver.discover` which sets
    ``ResourceProposal.resource_id = str(path)``). We read the first
    line as the header, split via :mod:`csv`, and emit one
    :class:`CatalogColumnSpec` per header field.

    csv_local has NO column type info available at catalog-discovery
    time (type inference requires reading the data — that's L5's
    fingerprinting territory, not catalog substrate). We therefore
    set ``type=None`` for every column — preserving the
    honest-empty-upstream posture for the ``type`` axis while still
    populating column names. The Sub-wave A
    :class:`CatalogColumnSpec` payload models this with
    ``type: str | None = None``.

    Defensive empty-state returns:
      * File does not exist → ``[]`` (extractor cannot fail the emit).
      * Empty file → ``[]``.
      * Empty header row → ``[]``.
      * Read errors (binary file, encoding crash) → ``[]`` + warning
        log; the emit path falls back to ``columns=()`` and remains
        honest about empty-upstream signal.

    SurfaceDriver / handle args accepted for the dispatch signature;
    csv_local resolves everything from ``resource_id`` (the path).
    """
    del connector, handle  # csv_local needs only the path
    path = Path(resource_id)
    if not path.exists():
        return []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning(
            "csv_local_extractor: could not read %s: %s",
            resource_id,
            exc,
        )
        return []
    if not raw:
        return []

    # Mirror csv_local's encoding-detection rule (utf-8 → cp1252 →
    # latin-1) so a non-UTF-8 header is decoded the same way the
    # profile path decodes data rows.
    try:
        from wormbase_lake_surfaces.csv_local import detect_encoding
        encoding = detect_encoding(raw)
    except Exception:  # noqa: BLE001
        encoding = "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except Exception:  # noqa: BLE001
        return []

    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []

    columns: list[CatalogColumnSpec] = []
    for raw_name in header:
        name = (raw_name or "").strip()
        if not name:
            # Skip empty header cells — payload validator would reject
            # them downstream. Preserving the position would require a
            # synthetic name ("__col_3") that has no upstream truth.
            continue
        columns.append(CatalogColumnSpec(name=name, type=None))
    return columns


# ---------------------------------------------------------------------------
# postgres extractor — queries information_schema.columns.
# ---------------------------------------------------------------------------


def postgres_extractor(
    connector: Any, handle: Any, resource_id: str,
) -> list[CatalogColumnSpec]:
    """Extract column specs for a postgres table.

    The postgres ``resource_id`` is the qualified ``schema.table`` name
    (per :meth:`PostgresSurfaceDriver.discover` which sets
    ``ResourceProposal.resource_id = f"{schema}.{name}"``).

    Implementation mirrors :meth:`PostgresSurfaceDriver.profile`'s
    information_schema.columns query — but takes only the (name,
    data_type) pair the catalog substrate cares about. The profile
    path additionally carries nullability + ordinal_position for L5/L7
    consumption; those axes flow through the existing profile pipeline
    and are not part of the L2 catalog substrate.

    Unlike csv_local, postgres DOES surface native types (uuid,
    timestamp, jsonb, etc.), so each :class:`CatalogColumnSpec` carries
    ``type=<information_schema data_type string>`` verbatim.

    Defensive empty-state returns:
      * Missing handle / handle without dsn → ``[]``.
      * resource_id without a ``.`` separator → ``[]`` (the postgres
        profile path raises here, but the extractor swallows so it
        cannot block the emit).
      * Connection failure or query error → ``[]`` + warning log
        (extract_columns's outer try/except logs the exception).
    """
    del connector  # registry pattern argument; we re-import asyncpg directly
    if handle is None:
        return []
    dsn = None
    extra = getattr(handle, "extra", None)
    if isinstance(extra, dict):
        dsn = extra.get("dsn")
    if not dsn or not isinstance(dsn, str):
        return []
    if "." not in resource_id:
        return []
    schema, table = resource_id.split(".", 1)

    async def _fetch() -> list[Any]:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn)
        try:
            return await conn.fetch(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                schema, table,
            )
        finally:
            await conn.close()

    rows = _run_async(_fetch())
    columns: list[CatalogColumnSpec] = []
    for row in rows:
        # asyncpg rows behave like mappings; defensive .get if dict-like.
        try:
            name = row["column_name"]
            dtype = row["data_type"]
        except (KeyError, TypeError):
            continue
        if not isinstance(name, str) or not name:
            continue
        type_str: str | None = (
            dtype if isinstance(dtype, str) and dtype else None
        )
        columns.append(CatalogColumnSpec(name=name, type=type_str))
    return columns


# ---------------------------------------------------------------------------
# s3_csv extractor — Range-fetches the header bytes.
# ---------------------------------------------------------------------------


# How many bytes to fetch when looking for a CSV header row. 4KB
# generously covers wide-column headers (hundreds of columns) without
# pulling whole files. The s3_csv profile path uses 64KB; the extractor
# only needs the FIRST LINE so we stay smaller.
_S3_HEADER_BYTES: int = 4096
_HTTP_HEADER_BYTES: int = 4096


def s3_csv_extractor(
    connector: Any, handle: Any, resource_id: str,
) -> list[CatalogColumnSpec]:
    """Extract column specs for an s3_csv resource.

    The s3_csv ``resource_id`` is the S3 object key (per
    :meth:`S3CsvSurfaceDriver.discover`). We use the connector's existing
    sample() path (Range-bounded GetObject) to pull the first ~4KB of
    bytes, then parse the first line as the CSV header.

    Reuses :meth:`SurfaceDriver.sample` rather than re-implementing the
    aioboto3 session lifecycle — keeps the AWS auth + region + custom
    endpoint logic on the connector and uses the extractor as a thin
    adapter that just asks for the head bytes.

    Defensive empty-state returns:
      * Missing connector instance → ``[]``.
      * Missing handle → ``[]``.
      * Sample call raises (auth failure, missing object) → ``[]`` +
        outer try/except in extract_columns logs.
      * Body too short to contain a complete header line → header is
        still parsed (csv.reader returns whatever first line exists);
        empty cells skipped.
    """
    if connector is None or handle is None:
        return []

    async def _fetch() -> bytes:
        return await connector.sample(handle, resource_id, _S3_HEADER_BYTES)

    raw = _run_async(_fetch())
    if not isinstance(raw, (bytes, bytearray)):
        return []
    return _parse_csv_header_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# http_csv extractor — Range-fetches the header bytes.
# ---------------------------------------------------------------------------


def http_csv_extractor(
    connector: Any, handle: Any, resource_id: str,
) -> list[CatalogColumnSpec]:
    """Extract column specs for an http_csv resource.

    The http_csv ``resource_id`` is the HTTPS URL (per
    :meth:`HttpCsvSurfaceDriver.discover` which uses one URL == one
    resource). The extractor calls :meth:`SurfaceDriver.sample` to fetch
    the first ~4KB via a Range request, then parses the first line as
    the CSV header.

    Reuses :meth:`SurfaceDriver.sample` so we inherit the connector's
    httpx timeout + auth header + custom-headers logic without
    duplicating it. Servers that don't honor Range requests still
    return data; csv parsing happily takes whatever first line lands.

    Defensive empty-state returns:
      * Missing connector instance → ``[]``.
      * Missing handle → ``[]``.
      * Sample call raises (HTTP error, network down, server 4xx) →
        ``[]`` (outer try/except in extract_columns logs the
        traceback).
      * Server returns non-CSV (HTML error page) → header parses as
        garbage; usually one column with the first ``<`` chunk; the
        L2/L5/L7 strategies treat it as upstream signal and the
        downstream truth gates eventually catch the mistake. We do
        not synthesize a smarter content-type check here; the
        connector should refuse before reaching the extractor when
        the URL is wrong.
    """
    if connector is None or handle is None:
        return []

    async def _fetch() -> bytes:
        return await connector.sample(handle, resource_id, _HTTP_HEADER_BYTES)

    raw = _run_async(_fetch())
    if not isinstance(raw, (bytes, bytearray)):
        return []
    return _parse_csv_header_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# Honest-empty connectors — explicit rationale per kind.
# ---------------------------------------------------------------------------
#
# The following connectors do NOT have a registered extractor by
# design. Each has a specific reason that's worth preserving here so
# future polish bundles know what graduating each one would entail.
#
# bigquery
#   ``BigQuerySurfaceDriver`` is skeletal (``status = "coming_soon"``).
#   ``google-cloud-bigquery`` integration lands in v1.5. Once wired,
#   the extractor will read ``table.schema`` directly — BigQuery
#   schema objects expose ``SchemaField`` records with ``name`` +
#   ``field_type`` strings (``"STRING"``, ``"INTEGER"``,
#   ``"TIMESTAMP"``, etc.) — making it the easiest cloud-warehouse
#   extractor to write once the underlying client lands.
#
# gsheets
#   ``GsheetsSurfaceDriver`` is skeletal (``status = "coming_soon"``).
#   Google Sheets API v4 integration lands in v1.5. The extractor
#   will use ``sheets.values.get(range='1:1')`` to fetch row 1 of
#   each sheet and parse cells as column names. Sheets carries no
#   per-column type metadata (cells are free-form), so the extractor
#   will emit ``type=None`` exactly like the csv_local extractor.
#
# stripe
#   ``StripeSurfaceDriver`` IS production-grade, but the catalog is
#   special: it's a fixed enum of 6 Stripe object types
#   (``charges``, ``customers``, ``payouts``, ``subscriptions``,
#   ``invoices``, ``balance_transactions``) and each object's
#   "columns" are JSON keys from the live API response. The profile
#   path peeks ``GET /v1/<object>?limit=1`` then introspects keys of
#   ``data[0]`` — that's a real network call per table per snapshot.
#   Wiring a catalog extractor would amortize one Stripe API call
#   per catalog import per object type per tenant — non-trivial
#   cost + rate-limit risk that deserves its own design decision.
#   Defer until a customer or demo specifically needs Stripe
#   substrate populated in L2 ColumnSet / L8 SchemaShape.
#
# salesforce
#   ``SalesforceSurfaceDriver`` is skeletal (``status = "coming_soon"``).
#   Salesforce describe APIs (``SObject.describe()``) ARE the
#   canonical column-metadata surface, but the SDK + OAuth flow is
#   substantial work. When the connector graduates to production
#   the extractor wraps ``describe()`` for each sobject the
#   discover step surfaced; SF emits ``soapType`` strings as native
#   types.
#
# hubspot
#   ``HubspotSurfaceDriver`` is skeletal (``status = "coming_soon"``).
#   HubSpot's CRM API exposes a ``GET /crm/v3/properties/{objectType}``
#   endpoint that returns per-property type strings (``string``,
#   ``number``, ``datetime``, etc.). Wiring is straightforward
#   when the connector graduates to production; the rate-limit + auth
#   surface needs the same scoping as Salesforce.
#
# Doctrine: per-connector extractors are the well-paved
# extensibility path. Adding new connectors gets a productive
# extractor "for free" if the connector already has CSV / SQL /
# struct-schema introspection; SaaS describe-API integrations
# (Stripe / Salesforce / HubSpot) are a separate, larger lift
# because they consume customer rate-limit budget and need their
# own retry / backoff posture.


# ---------------------------------------------------------------------------
# Registry + lookup
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, ColumnExtractor] = {}


def register_column_extractor(
    connector_kind: str, extractor: ColumnExtractor,
) -> None:
    """Register an extractor for ``connector_kind``.

    Replaces any prior registration for the same kind (test-friendly
    by design — fixtures can swap an extractor for a stub). Kind
    matching is case-sensitive and exact.
    """
    _REGISTRY[connector_kind] = extractor


def extract_columns(
    *, connector: Any, handle: Any, resource_id: str, connector_kind: str,
) -> list[CatalogColumnSpec]:
    """Dispatch to the registered extractor for ``connector_kind``.

    Returns ``[]`` when no extractor is registered for the kind — the
    honest empty-upstream posture per the Sub-wave A
    :class:`CatalogTableImportedPayload` design (``columns`` may be an
    empty tuple).

    Defensive try/except: a buggy extractor MUST NOT block the
    emission of ``catalog_table_imported`` — we log + fall back to
    ``[]``. The strategies degrade to honest empty-upstream behaviour
    rather than crashing the source-builder transaction.
    """
    extractor = _REGISTRY.get(connector_kind)
    if extractor is None:
        return []
    try:
        return extractor(connector, handle, resource_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "extract_columns: extractor for %r raised %s on resource_id=%r; "
            "falling back to empty columns",
            connector_kind,
            exc,
            resource_id,
        )
        return []


# ---------------------------------------------------------------------------
# Auto-registration of wired extractors.
# ---------------------------------------------------------------------------
# csv_local — first production-wired (Sub-wave B, 2026-06-10).
# postgres / s3_csv / http_csv — per-connector extractor bundle
# (2026-06-10). All four share the same dispatch shape; the file-based
# trio (csv_local / s3_csv / http_csv) shares the CSV header-parse
# helper for type-free name extraction.
register_column_extractor("csv_local", csv_local_extractor)
register_column_extractor("postgres", postgres_extractor)
register_column_extractor("s3_csv", s3_csv_extractor)
register_column_extractor("http_csv", http_csv_extractor)
