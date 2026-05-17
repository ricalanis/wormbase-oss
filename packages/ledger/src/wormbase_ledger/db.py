"""Async SQLAlchemy engine + session_scope.

Backend-agnostic: works against Postgres (production) or SQLite (tests).
Engines are cached by URL so repeated calls reuse pools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engines: dict[str, AsyncEngine] = {}


def get_engine(url: str) -> AsyncEngine:
    if url not in _engines:
        # SQLite needs `check_same_thread=False`-equivalent + no pool_pre_ping.
        if url.startswith("sqlite"):
            _engines[url] = create_async_engine(url, future=True)
        else:
            _engines[url] = create_async_engine(url, future=True, pool_pre_ping=True)
    return _engines[url]


@asynccontextmanager
async def session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yields an AsyncSession; commits on success, rolls back on exception."""
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
