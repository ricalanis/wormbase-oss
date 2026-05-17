import pytest
from wormbase_ledger.db import get_engine, session_scope


@pytest.mark.asyncio
async def test_engine_connects(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("SELECT 1")
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_session_scope_yields_session(test_database_url: str) -> None:
    async with session_scope(get_engine(test_database_url)) as session:
        assert session.is_active
