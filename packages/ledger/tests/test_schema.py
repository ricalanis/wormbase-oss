import pytest
from sqlalchemy import inspect
from wormbase_ledger.db import get_engine
from wormbase_ledger.schema import metadata  # noqa: F401  (used by autouse fixture)


@pytest.mark.asyncio
async def test_ledger_table_exists(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "ledger" in names


@pytest.mark.asyncio
async def test_ledger_has_required_columns(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda s: {c["name"] for c in inspect(s).get_columns("ledger")}
        )
    required = {
        "entry_id",
        "company_id",
        "seq",
        "ts",
        "kind",
        "quadrant",
        "payload",
        "prev_hash",
        "hash",
    }
    assert required.issubset(cols), f"missing: {required - cols}"


@pytest.mark.asyncio
async def test_unique_company_seq(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        uniques = await conn.run_sync(
            lambda s: inspect(s).get_unique_constraints("ledger")
        )
    col_sets = [tuple(sorted(u["column_names"])) for u in uniques]
    assert ("company_id", "seq") in col_sets


@pytest.mark.asyncio
async def test_projection_tables_exist(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda s: set(inspect(s).get_table_names()))
    for t in (
        "projection_sources",
        "projection_memory",
        "projection_kpi_nodes",
        "projection_ramp",
        "projection_persons",
        "projection_person_identities",
        "projection_installs",
        "projection_roles",
        "projection_data_products",
        "projection_data_product_runs",
        "projection_data_product_consumption",
        "projection_notebooks",
        "projection_notebook_runs",
        "replay_cursor",
    ):
        assert t in names, f"missing projection table: {t}"
