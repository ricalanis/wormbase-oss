"""Tests for csv_local — pull-only local CSV connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_connectors.base import Connector
from wormbase_connectors.csv_local import CsvLocalConnector
from wormbase_connectors.types import SecretBundle


def test_csv_local_implements_connector_protocol() -> None:
    c = CsvLocalConnector()
    assert isinstance(c, Connector)
    assert c.kind == "csv_local"
    assert "discover" in c.capability
    assert "profile" in c.capability
    assert "sample" in c.capability


@pytest.mark.asyncio
async def test_csv_authenticate_returns_handle() -> None:
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": "/tmp/x.csv"}))
    assert handle.connector_kind == "csv_local"
    assert handle.handle_id == "/tmp/x.csv"
    assert handle.extra["path"] == "/tmp/x.csv"


@pytest.mark.asyncio
async def test_csv_authenticate_rejects_missing_path() -> None:
    c = CsvLocalConnector()
    with pytest.raises(ValueError, match="path"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_csv_discover_returns_one_resource(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    resources = await c.discover(handle)
    assert len(resources) == 1
    assert resources[0].kind == "file"
    assert resources[0].name == "x.csv"
    assert resources[0].metadata["mimetype"] == "text/csv"
    assert resources[0].metadata["size_bytes"] > 0


@pytest.mark.asyncio
async def test_csv_discover_missing_file_returns_empty(tmp_path: Path) -> None:
    c = CsvLocalConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"path": str(tmp_path / "nope.csv")}),
    )
    assert await c.discover(handle) == []


@pytest.mark.asyncio
async def test_csv_profile_returns_columns(tmp_path: Path) -> None:
    p = tmp_path / "y.csv"
    p.write_text("name,age\nAlice,30\nBob,25\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    profile = await c.profile(handle, str(p))
    assert profile.row_count == 2
    assert profile.column_count == 2
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["name"]["dtype"] == "str"
    assert by_name["age"]["dtype"] == "int"
    assert profile.schema_hash != ""


@pytest.mark.asyncio
async def test_csv_profile_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    profile = await c.profile(handle, str(p))
    assert profile.row_count == 0
    assert profile.column_count == 0


@pytest.mark.asyncio
async def test_csv_sample_returns_n_rows(tmp_path: Path) -> None:
    p = tmp_path / "z.csv"
    p.write_text("a,b\n" + "\n".join(f"{i},{i*2}" for i in range(10)) + "\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    sample = await c.sample(handle, str(p), 3)
    # header + 3 rows = 4 lines (newlines)
    assert sample.count(b"\n") <= 4


@pytest.mark.asyncio
async def test_csv_pii_filename_classification(tmp_path: Path) -> None:
    p = tmp_path / "customers_with_ssn.csv"
    p.write_text("name,ssn\nAlice,123\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    [resource] = await c.discover(handle)
    assert resource.classification_hint == "pii"


@pytest.mark.asyncio
async def test_csv_confidential_filename_classification(tmp_path: Path) -> None:
    p = tmp_path / "q3_payroll.csv"
    p.write_text("name,salary\nAlice,100\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    [resource] = await c.discover(handle)
    assert resource.classification_hint == "confidential"


@pytest.mark.asyncio
async def test_csv_unclassified_filename(tmp_path: Path) -> None:
    p = tmp_path / "sales_q3.csv"
    p.write_text("region,amount\nEU,100\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    [resource] = await c.discover(handle)
    assert resource.classification_hint is None


@pytest.mark.asyncio
async def test_csv_dtype_inference_floats(tmp_path: Path) -> None:
    p = tmp_path / "metrics.csv"
    p.write_text("ratio,count\n0.5,10\n0.7,20\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    profile = await c.profile(handle, str(p))
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["ratio"]["dtype"] == "float"
    assert by_name["count"]["dtype"] == "int"


@pytest.mark.asyncio
async def test_csv_watch_yields_nothing(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    c = CsvLocalConnector()
    handle = await c.authenticate(SecretBundle(payload={"path": str(p)}))
    items = [item async for item in c.watch(handle, str(p))]
    assert items == []
