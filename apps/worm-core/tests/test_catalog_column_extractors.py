"""Catalog-mirror Wave 2 Sub-wave B — column-extractor registry tests.

Pins the per-connector-kind extraction dispatch surface used by
``emit_catalog_table_imported_for_resource`` in write_actions. csv_local
is the first production-wired connector kind; unknown kinds fall
through to ``[]`` (the honest-empty-upstream posture).
"""
from __future__ import annotations

import csv as _csv
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from wormbase_ledger.entries import CatalogColumnSpec

from wormbase_core.catalog_column_extractors import (
    csv_local_extractor,
    extract_columns,
    register_column_extractor,
)


# ---------------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------------


def test_extract_columns_unknown_kind_returns_empty() -> None:
    """Kinds without a registered extractor return ``[]`` (honest fallback)."""
    cols = extract_columns(
        connector=None,
        handle=None,
        resource_id="anything",
        connector_kind="utterly-unknown-connector-kind-xyz",
    )
    assert cols == []


def test_extract_columns_csv_local_dispatches_to_extractor(
    tmp_path: Path,
) -> None:
    """csv_local kind dispatches to ``csv_local_extractor``."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("id,name,amount\n1,Alpha,10\n", encoding="utf-8")

    cols = extract_columns(
        connector=None,
        handle=None,
        resource_id=str(csv_path),
        connector_kind="csv_local",
    )
    assert [c.name for c in cols] == ["id", "name", "amount"]
    assert all(c.type is None for c in cols)


def test_extract_columns_returns_catalog_column_spec_instances(
    tmp_path: Path,
) -> None:
    """Returned objects are validated ``CatalogColumnSpec`` records."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

    cols = extract_columns(
        connector=None,
        handle=None,
        resource_id=str(csv_path),
        connector_kind="csv_local",
    )
    assert all(isinstance(c, CatalogColumnSpec) for c in cols)


def test_extract_columns_resource_id_defaults_via_caller() -> None:
    """Registry returns ``[]`` when an empty resource_id has no header."""
    cols = extract_columns(
        connector=None,
        handle=None,
        resource_id="",
        connector_kind="csv_local",
    )
    assert cols == []


def test_register_column_extractor_overrides_existing() -> None:
    """Registering the same kind twice replaces the prior extractor."""
    sentinel_called: dict[str, Any] = {"hit": False}

    def _stub(
        _connector: Any, _handle: Any, resource_id: str,
    ) -> list[CatalogColumnSpec]:
        sentinel_called["hit"] = True
        sentinel_called["resource_id"] = resource_id
        return [CatalogColumnSpec(name="sentinel", type=None)]

    try:
        register_column_extractor("___test_kind___", _stub)
        cols = extract_columns(
            connector=None,
            handle=None,
            resource_id="ignored",
            connector_kind="___test_kind___",
        )
        assert sentinel_called["hit"]
        assert sentinel_called["resource_id"] == "ignored"
        assert [c.name for c in cols] == ["sentinel"]
    finally:
        # Cleanup: drop the test kind so other tests don't see it.
        from wormbase_core import catalog_column_extractors as _mod
        _mod._REGISTRY.pop("___test_kind___", None)


def test_extract_columns_buggy_extractor_falls_back_to_empty() -> None:
    """An extractor that raises is caught + falls back to ``[]``."""
    def _boom(
        _connector: Any, _handle: Any, _resource_id: str,
    ) -> list[CatalogColumnSpec]:
        raise RuntimeError("boom")

    try:
        register_column_extractor("___boom_kind___", _boom)
        cols = extract_columns(
            connector=None,
            handle=None,
            resource_id="r",
            connector_kind="___boom_kind___",
        )
        assert cols == []
    finally:
        from wormbase_core import catalog_column_extractors as _mod
        _mod._REGISTRY.pop("___boom_kind___", None)


# ---------------------------------------------------------------------------
# csv_local extractor — direct
# ---------------------------------------------------------------------------


def test_csv_local_extractor_reads_header(tmp_path: Path) -> None:
    """Header row → one CatalogColumnSpec per non-empty cell."""
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("col_a,col_b,col_c\nv1,v2,v3\n", encoding="utf-8")
    cols = csv_local_extractor(None, None, str(csv_path))
    assert [c.name for c in cols] == ["col_a", "col_b", "col_c"]
    # Type info is unknown at catalog-discovery time for raw CSV.
    assert all(c.type is None for c in cols)


def test_csv_local_extractor_skips_empty_header_cells(
    tmp_path: Path,
) -> None:
    """Empty header cells are skipped (validator rejects empty names)."""
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("a,,c,\n1,2,3,4\n", encoding="utf-8")
    cols = csv_local_extractor(None, None, str(csv_path))
    assert [c.name for c in cols] == ["a", "c"]


def test_csv_local_extractor_missing_file_returns_empty() -> None:
    """Non-existent file → ``[]`` (extractor cannot fail the emit)."""
    cols = csv_local_extractor(None, None, "/definitely/not/a/real/file.csv")
    assert cols == []


def test_csv_local_extractor_empty_file_returns_empty(
    tmp_path: Path,
) -> None:
    """Zero-byte file → ``[]``."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_bytes(b"")
    cols = csv_local_extractor(None, None, str(csv_path))
    assert cols == []


def test_csv_local_extractor_handles_cp1252_encoding(
    tmp_path: Path,
) -> None:
    """Latin-1/cp1252 headers decode via the connector's detection."""
    csv_path = tmp_path / "latin.csv"
    # "résumé" in cp1252 plus an ascii header.
    csv_path.write_bytes(
        "id,r\xe9sum\xe9,note\nv1,v2,v3\n".encode("cp1252"),
    )
    cols = csv_local_extractor(None, None, str(csv_path))
    names = [c.name for c in cols]
    assert names[0] == "id"
    # The cp1252 column is preserved as-is (encoding detection succeeds).
    assert any("sum" in n.lower() for n in names)
    assert names[-1] == "note"


def test_csv_local_extractor_returns_names_for_realistic_csv(
    tmp_path: Path,
) -> None:
    """End-to-end with a realistic finance-style header."""
    csv_path = tmp_path / "fin.csv"
    headers = [
        "transaction_id", "customer_email", "amount", "currency",
        "transacted_at", "settled_at",
    ]
    sio = StringIO()
    w = _csv.writer(sio)
    w.writerow(headers)
    w.writerow(["tx1", "x@y.com", "10.00", "USD", "2026-01-01", "2026-01-02"])
    csv_path.write_text(sio.getvalue(), encoding="utf-8")

    cols = csv_local_extractor(None, None, str(csv_path))
    assert [c.name for c in cols] == headers


def test_csv_local_extractor_handles_quoted_commas(tmp_path: Path) -> None:
    """csv.reader handles quoted commas inside header cells."""
    csv_path = tmp_path / "quoted.csv"
    csv_path.write_text('"a,b",c,"d"\n1,2,3\n', encoding="utf-8")
    cols = csv_local_extractor(None, None, str(csv_path))
    assert [c.name for c in cols] == ["a,b", "c", "d"]


def test_csv_local_extractor_directory_returns_empty(
    tmp_path: Path,
) -> None:
    """A directory path (not a file) → ``[]`` instead of crashing."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    cols = csv_local_extractor(None, None, str(sub))
    assert cols == []


def test_csv_local_extractor_ignores_connector_and_handle(
    tmp_path: Path,
) -> None:
    """csv_local needs only resource_id; other args are accepted but unused."""
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("x,y\n1,2\n", encoding="utf-8")
    cols_a = csv_local_extractor("ignored", "also ignored", str(csv_path))
    cols_b = csv_local_extractor(None, None, str(csv_path))
    assert [c.name for c in cols_a] == [c.name for c in cols_b] == ["x", "y"]


# ---------------------------------------------------------------------------
# Auto-registration
# ---------------------------------------------------------------------------


def test_csv_local_extractor_auto_registered_on_module_import() -> None:
    """``csv_local`` is wired at module import — no manual registration."""
    from wormbase_core import catalog_column_extractors as _mod
    assert "csv_local" in _mod._REGISTRY


@pytest.mark.parametrize(
    "kind",
    [
        # SaaS-API and skeletal connectors that REMAIN honest-empty after
        # the per-connector extractor bundle (2026-06-10):
        #   - bigquery / gsheets — skeletal (coming_soon), awaiting v1.5 SDK
        #   - stripe — production, but live-API describe cost defers wiring
        #   - salesforce / hubspot — skeletal SaaS, describe-API surfaces
        #     deserve their own design pass
        # snowflake stays here because it's productive via TableMeta.columns
        # directly (no extractor needed for the productive path).
        "snowflake",
        "bigquery",
        "gsheets",
        "stripe",
        "hubspot",
        "salesforce",
    ],
)
def test_honest_empty_connectors_return_empty(kind: str) -> None:
    """SurfaceDriver kinds without registered extractors return ``[]`` honestly.

    Per the per-connector extractor bundle (2026-06-10) the wired
    extractors are: csv_local, postgres, s3_csv, http_csv. The
    remaining kinds (bigquery / gsheets / stripe / salesforce /
    hubspot — plus snowflake, which is productive via
    TableMeta.columns rather than an extractor) intentionally fall
    through to the empty-list fallback. Rationale is documented in
    the registry module itself.
    """
    cols = extract_columns(
        connector=None,
        handle=None,
        resource_id="placeholder",
        connector_kind=kind,
    )
    assert cols == []


# ---------------------------------------------------------------------------
# Per-connector extractor bundle (2026-06-10) — wired registry kinds.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["csv_local", "postgres", "s3_csv", "http_csv"],
)
def test_wired_extractors_registered_on_module_import(kind: str) -> None:
    """All four wired extractors auto-register on module import."""
    from wormbase_core import catalog_column_extractors as _mod
    assert kind in _mod._REGISTRY


# ---------------------------------------------------------------------------
# postgres extractor — uses asyncpg-mocked connection.
# ---------------------------------------------------------------------------


from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from wormbase_core.catalog_column_extractors import (  # noqa: E402
    http_csv_extractor,
    postgres_extractor,
    s3_csv_extractor,
)


@pytest.fixture
def _postgres_handle() -> Any:
    """Stub AuthHandle-shaped object exposing a dsn in extra."""
    class _Handle:
        connector_kind = "postgres"
        handle_id = "x"
        extra = {"dsn": "postgresql://wb@db/wb"}
    return _Handle()


def test_postgres_extractor_returns_columns_from_information_schema(
    _postgres_handle: Any,
) -> None:
    """information_schema rows fold to CatalogColumnSpec(name, type)."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetch = AsyncMock(
        return_value=[
            {"column_name": "id", "data_type": "uuid"},
            {"column_name": "created_at", "data_type": "timestamp"},
            {"column_name": "amount", "data_type": "numeric"},
        ],
    )
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        cols = postgres_extractor(None, _postgres_handle, "public.ledger")

    assert [c.name for c in cols] == ["id", "created_at", "amount"]
    assert [c.type for c in cols] == ["uuid", "timestamp", "numeric"]
    fake_conn.close.assert_awaited()


def test_postgres_extractor_handles_empty_table(_postgres_handle: Any) -> None:
    """A table whose information_schema query returns no rows → ``[]``."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        cols = postgres_extractor(None, _postgres_handle, "public.empty")
    assert cols == []


def test_postgres_extractor_rejects_unqualified_resource_id(
    _postgres_handle: Any,
) -> None:
    """resource_id without a ``.`` (no schema) → ``[]`` (no crash)."""
    cols = postgres_extractor(None, _postgres_handle, "ledger")
    assert cols == []


def test_postgres_extractor_handles_missing_handle() -> None:
    """Missing handle / no dsn → ``[]`` (defensive)."""
    assert postgres_extractor(None, None, "public.t") == []

    class _Empty:
        extra: dict[str, Any] = {}
    assert postgres_extractor(None, _Empty(), "public.t") == []


def test_postgres_extractor_returns_catalog_column_spec_instances(
    _postgres_handle: Any,
) -> None:
    """Returned objects are ``CatalogColumnSpec`` validated records."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetch = AsyncMock(
        return_value=[{"column_name": "a", "data_type": "text"}],
    )
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        cols = postgres_extractor(None, _postgres_handle, "s.t")
    assert all(isinstance(c, CatalogColumnSpec) for c in cols)


def test_postgres_extractor_skips_rows_with_empty_column_name(
    _postgres_handle: Any,
) -> None:
    """Defensive: a degenerate row with an empty name is skipped."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetch = AsyncMock(
        return_value=[
            {"column_name": "good", "data_type": "text"},
            {"column_name": "", "data_type": "text"},
            {"column_name": "also_good", "data_type": "int"},
        ],
    )
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        cols = postgres_extractor(None, _postgres_handle, "s.t")
    assert [c.name for c in cols] == ["good", "also_good"]


def test_extract_columns_postgres_dispatches_through_registry(
    _postgres_handle: Any,
) -> None:
    """Registry dispatch for postgres invokes the postgres extractor."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetch = AsyncMock(
        return_value=[{"column_name": "id", "data_type": "uuid"}],
    )
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        cols = extract_columns(
            connector=None,
            handle=_postgres_handle,
            resource_id="public.users",
            connector_kind="postgres",
        )
    assert [c.name for c in cols] == ["id"]
    assert [c.type for c in cols] == ["uuid"]


# ---------------------------------------------------------------------------
# s3_csv extractor — uses SurfaceDriver.sample mock.
# ---------------------------------------------------------------------------


def _make_sampler_mock(payload: bytes | Exception) -> Any:
    """Build a fake SurfaceDriver-like object whose .sample returns/raises."""
    connector = MagicMock()
    if isinstance(payload, Exception):
        connector.sample = AsyncMock(side_effect=payload)
    else:
        connector.sample = AsyncMock(return_value=payload)
    return connector


def test_s3_csv_extractor_parses_header_from_first_bytes() -> None:
    """sample()'s leading bytes are parsed as a CSV header."""
    body = b"order_id,customer,amount\n1,alice,10.00\n2,bob,20.00\n"
    connector = _make_sampler_mock(body)
    handle = MagicMock()

    cols = s3_csv_extractor(connector, handle, "data/orders.csv")

    assert [c.name for c in cols] == ["order_id", "customer", "amount"]
    # CSV has no upstream type info — L5 handles that axis.
    assert all(c.type is None for c in cols)
    connector.sample.assert_awaited_once()
    # Confirm we asked for header-sized bytes, not the entire file.
    args, _ = connector.sample.call_args
    assert args[2] <= 8192  # bounded sample size for header extraction


def test_s3_csv_extractor_returns_empty_for_empty_object() -> None:
    """An empty S3 object → ``[]``."""
    connector = _make_sampler_mock(b"")
    cols = s3_csv_extractor(connector, MagicMock(), "data/empty.csv")
    assert cols == []


def test_s3_csv_extractor_returns_empty_on_sample_failure() -> None:
    """sample() raising falls through the extract_columns catch."""
    connector = _make_sampler_mock(RuntimeError("permission denied"))
    cols = extract_columns(
        connector=connector,
        handle=MagicMock(),
        resource_id="data/forbidden.csv",
        connector_kind="s3_csv",
    )
    assert cols == []


def test_s3_csv_extractor_handles_missing_connector_or_handle() -> None:
    """Either argument missing → ``[]`` (defensive)."""
    assert s3_csv_extractor(None, MagicMock(), "k") == []
    assert s3_csv_extractor(MagicMock(), None, "k") == []


def test_s3_csv_extractor_skips_empty_header_cells() -> None:
    """A header with empty cells emits only the populated names."""
    body = b"a,,c,\n1,2,3,4\n"
    cols = s3_csv_extractor(_make_sampler_mock(body), MagicMock(), "k")
    assert [c.name for c in cols] == ["a", "c"]


def test_extract_columns_s3_csv_dispatches_through_registry() -> None:
    """Registry dispatch for s3_csv invokes the s3_csv extractor."""
    body = b"col1,col2\n1,2\n"
    cols = extract_columns(
        connector=_make_sampler_mock(body),
        handle=MagicMock(),
        resource_id="data/x.csv",
        connector_kind="s3_csv",
    )
    assert [c.name for c in cols] == ["col1", "col2"]


# ---------------------------------------------------------------------------
# http_csv extractor — same shape as s3_csv (sample → header parse).
# ---------------------------------------------------------------------------


def test_http_csv_extractor_parses_header_from_first_bytes() -> None:
    """sample()'s leading bytes are parsed as a CSV header."""
    body = b"id,name,price\n1,Widget,9.99\n"
    connector = _make_sampler_mock(body)

    cols = http_csv_extractor(connector, MagicMock(), "https://x/y.csv")

    assert [c.name for c in cols] == ["id", "name", "price"]
    assert all(c.type is None for c in cols)
    connector.sample.assert_awaited_once()


def test_http_csv_extractor_returns_empty_for_empty_body() -> None:
    """An empty HTTP body → ``[]``."""
    connector = _make_sampler_mock(b"")
    cols = http_csv_extractor(connector, MagicMock(), "https://x/y.csv")
    assert cols == []


def test_http_csv_extractor_returns_empty_on_sample_failure() -> None:
    """sample() raising (404, network down) falls through extract_columns."""
    import httpx  # noqa: F401 — ensure httpx-style errors are catchable

    connector = _make_sampler_mock(RuntimeError("HTTP 404"))
    cols = extract_columns(
        connector=connector,
        handle=MagicMock(),
        resource_id="https://x/missing.csv",
        connector_kind="http_csv",
    )
    assert cols == []


def test_http_csv_extractor_handles_missing_connector_or_handle() -> None:
    """Either argument missing → ``[]`` (defensive)."""
    assert http_csv_extractor(None, MagicMock(), "u") == []
    assert http_csv_extractor(MagicMock(), None, "u") == []


def test_http_csv_extractor_skips_empty_header_cells() -> None:
    """A header with empty cells emits only the populated names."""
    body = b",a,,b\n1,2,3,4\n"
    cols = http_csv_extractor(_make_sampler_mock(body), MagicMock(), "u")
    assert [c.name for c in cols] == ["a", "b"]


def test_extract_columns_http_csv_dispatches_through_registry() -> None:
    """Registry dispatch for http_csv invokes the http_csv extractor."""
    body = b"x,y\n1,2\n"
    cols = extract_columns(
        connector=_make_sampler_mock(body),
        handle=MagicMock(),
        resource_id="https://x/y.csv",
        connector_kind="http_csv",
    )
    assert [c.name for c in cols] == ["x", "y"]


def test_http_csv_extractor_handles_non_bytes_sample_return() -> None:
    """If sample() returns non-bytes (defensive) → ``[]``."""
    connector = MagicMock()
    connector.sample = AsyncMock(return_value="not bytes")  # wrong type
    cols = http_csv_extractor(connector, MagicMock(), "u")
    assert cols == []


def test_s3_csv_extractor_handles_non_bytes_sample_return() -> None:
    """If sample() returns non-bytes (defensive) → ``[]``."""
    connector = MagicMock()
    connector.sample = AsyncMock(return_value="not bytes")  # wrong type
    cols = s3_csv_extractor(connector, MagicMock(), "k")
    assert cols == []


# ---------------------------------------------------------------------------
# Per-bundle parametrized happy-path check across all 4 wired extractors.
# ---------------------------------------------------------------------------


def test_all_wired_extractors_are_in_registry() -> None:
    """Sanity: the bundle wires exactly the 4 expected kinds.

    Pins the per-connector extractor bundle's surface — the wired set
    is {csv_local, postgres, s3_csv, http_csv}. Adding a new wired
    kind requires updating this assertion (intentional friction).
    """
    from wormbase_core import catalog_column_extractors as _mod
    assert set(_mod._REGISTRY.keys()) == {
        "csv_local", "postgres", "s3_csv", "http_csv",
    }
