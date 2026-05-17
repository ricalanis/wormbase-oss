"""Tests for the pgvector >=0.6 boot-time pre-flight (Item #8 final wave).

The pre-flight wires into the worm-core CLI before projection migrations
run. It refuses to start when:

* WORMBASE_GATHER_VIA_PROJECTION=true (Phase 3c gather), OR
* WORMBASE_EMBEDDING_ENABLED=true on a Postgres dialect (Phase 3b
  write-time embedding)

...and the ``vector`` extension is missing or older than 0.6.

These tests cover the eight scenarios called out in the dispatch:

1. SQLite skips entirely
2. Postgres without pgvector → install hint
3. Postgres with pgvector 0.5.0 → upgrade hint
4. Postgres with pgvector 0.6.0 → OK
5. Postgres with pgvector 0.7.4 → OK
6. Env knobs OFF + no pgvector → skip
7. Version-parsing edge cases (suffixes)
8. DB-unavailable → surface underlying error

All DB interaction is mocked at the SQLAlchemy ``engine.connect()`` layer
so the suite stays deterministic and doesn't require a live Postgres.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from wormbase_core.preflight import (
    EXIT_PGVECTOR_MISSING,
    EXIT_PGVECTOR_QUERY_FAILED,
    EXIT_PGVECTOR_TOO_OLD,
    PgVectorPreflightError,
    PgVectorVersion,
    check_pgvector,
    is_pgvector_required,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, value: Any) -> None:
        self._value = value

    def __getitem__(self, idx: int) -> Any:
        if idx != 0:
            raise IndexError(idx)
        return self._value


class _FakeResult:
    def __init__(self, row: _FakeRow | None) -> None:
        self._row = row

    def first(self) -> _FakeRow | None:
        return self._row


class _FakeConn:
    def __init__(
        self,
        *,
        version: str | None,
        execute_error: Exception | None = None,
    ) -> None:
        self._version = version
        self._execute_error = execute_error
        self.executed_sql: list[str] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        if self._execute_error is not None:
            raise self._execute_error
        self.executed_sql.append(str(stmt))
        if self._version is None:
            return _FakeResult(None)
        return _FakeResult(_FakeRow(self._version))


class _FakeEngine:
    def __init__(
        self,
        *,
        dialect_name: str,
        version: str | None = None,
        execute_error: Exception | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        # SQLAlchemy's Engine exposes ``dialect.name`` — match that shape.
        self.dialect = type("_D", (), {"name": dialect_name})()
        self._version = version
        self._execute_error = execute_error
        self._connect_error = connect_error
        self.last_conn: _FakeConn | None = None

    def connect(self) -> Any:
        # Mirror SQLAlchemy's ``async with engine.connect() as conn`` API.
        engine = self

        @asynccontextmanager
        async def _ctx():
            if engine._connect_error is not None:
                raise engine._connect_error
            conn = _FakeConn(
                version=engine._version,
                execute_error=engine._execute_error,
            )
            engine.last_conn = conn
            try:
                yield conn
            finally:
                pass

        return _ctx()


class _FakeLedger:
    def __init__(self, engine: _FakeEngine | None) -> None:
        self.engine = engine


# ---------------------------------------------------------------------------
# Env fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Strip both env knobs at the start of every test so default-off is
    # the baseline and individual tests opt into truthy values.
    monkeypatch.delenv("WORMBASE_GATHER_VIA_PROJECTION", raising=False)
    monkeypatch.delenv("WORMBASE_EMBEDDING_ENABLED", raising=False)


def _enable_gather(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")


def _enable_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_EMBEDDING_ENABLED", "true")


# ---------------------------------------------------------------------------
# 1) SQLite skips entirely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_skips_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even with both env knobs on, a SQLite dialect short-circuits to OK
    # and never executes the pg_extension query.
    _enable_gather(monkeypatch)
    _enable_embedding(monkeypatch)
    engine = _FakeEngine(dialect_name="sqlite", version=None)
    ledger = _FakeLedger(engine)

    assert is_pgvector_required(ledger) is False
    result = await check_pgvector(ledger)
    assert result is None
    # The pre-flight must not have opened a connection on SQLite.
    assert engine.last_conn is None


# ---------------------------------------------------------------------------
# 2) Postgres without pgvector → install hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_without_pgvector_raises_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_gather(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version=None)
    ledger = _FakeLedger(engine)

    with pytest.raises(PgVectorPreflightError) as excinfo:
        await check_pgvector(ledger)
    assert excinfo.value.exit_code == EXIT_PGVECTOR_MISSING
    msg = str(excinfo.value)
    assert "CREATE EXTENSION vector" in msg
    assert "WORMBASE_GATHER_VIA_PROJECTION" in msg


# ---------------------------------------------------------------------------
# 3) Postgres with pgvector 0.5.0 → upgrade hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_with_pgvector_0_5_0_raises_upgrade_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_embedding(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version="0.5.0")
    ledger = _FakeLedger(engine)

    with pytest.raises(PgVectorPreflightError) as excinfo:
        await check_pgvector(ledger)
    assert excinfo.value.exit_code == EXIT_PGVECTOR_TOO_OLD
    msg = str(excinfo.value)
    assert "0.5.0" in msg
    assert "ALTER EXTENSION vector UPDATE" in msg


# ---------------------------------------------------------------------------
# 4) Postgres with pgvector 0.6.0 → OK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_with_pgvector_0_6_0_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_gather(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version="0.6.0")
    ledger = _FakeLedger(engine)

    result = await check_pgvector(ledger)
    assert result is not None
    assert result.major == 0
    assert result.minor == 6
    assert result.patch == 0
    assert result.raw == "0.6.0"


# ---------------------------------------------------------------------------
# 5) Postgres with pgvector 0.7.4 → OK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_with_pgvector_0_7_4_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_embedding(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version="0.7.4")
    ledger = _FakeLedger(engine)

    result = await check_pgvector(ledger)
    assert result is not None
    assert (result.major, result.minor, result.patch) == (0, 7, 4)


# ---------------------------------------------------------------------------
# 6) Env knobs OFF + no pgvector → pre-flight skips
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_knobs_off_skips_preflight_even_on_postgres() -> None:
    # Neither env knob set (fixture cleans them). The pre-flight must
    # NOT open a connection or query pg_extension — Phase 3a Postgres
    # deploys with no embedding wire enabled stay byte-identical to
    # pre-Phase-3 boots.
    engine = _FakeEngine(dialect_name="postgresql", version=None)
    ledger = _FakeLedger(engine)

    assert is_pgvector_required(ledger) is False
    result = await check_pgvector(ledger)
    assert result is None
    assert engine.last_conn is None


# ---------------------------------------------------------------------------
# 7) Version-parsing edge cases (suffixes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.6.0-dev", (0, 6, 0)),
        ("0.6.0+release", (0, 6, 0)),
        ("0.6", (0, 6, 0)),
        ("0.6.0rc1", (0, 6, 0)),
        ("1.0.0", (1, 0, 0)),
        ("0.10.2", (0, 10, 2)),
    ],
)
def test_version_parse_handles_suffixes(
    raw: str,
    expected: tuple[int, int, int],
) -> None:
    parsed = PgVectorVersion.parse(raw)
    assert (parsed.major, parsed.minor, parsed.patch) == expected
    assert parsed.satisfies_minimum() is True


def test_version_parse_rejects_unparseable() -> None:
    with pytest.raises(ValueError):
        PgVectorVersion.parse("not-a-version")


@pytest.mark.asyncio
async def test_postgres_with_suffixed_0_6_0_dev_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Round-trip the suffix case through the full check (the most
    # likely real-world failure mode if version parsing is too strict).
    _enable_gather(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version="0.6.0-dev")
    ledger = _FakeLedger(engine)

    result = await check_pgvector(ledger)
    assert result is not None
    assert result.raw == "0.6.0-dev"
    assert (result.major, result.minor) == (0, 6)


@pytest.mark.asyncio
async def test_postgres_with_malformed_version_surfaces_query_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The DB returned a row but the string is garbage — surface as
    # QUERY_FAILED (not MISSING / TOO_OLD), so operators investigate
    # the upstream packaging problem instead of "upgrading" away.
    _enable_gather(monkeypatch)
    engine = _FakeEngine(dialect_name="postgresql", version="garbage")
    ledger = _FakeLedger(engine)

    with pytest.raises(PgVectorPreflightError) as excinfo:
        await check_pgvector(ledger)
    assert excinfo.value.exit_code == EXIT_PGVECTOR_QUERY_FAILED


# ---------------------------------------------------------------------------
# 8) DB-unavailable surfaces underlying error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_unreachable_surfaces_underlying_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate asyncpg connection failure. The pre-flight must not
    # mislabel this as "pgvector missing" — operators need to see the
    # connect-side error to diagnose.
    _enable_gather(monkeypatch)
    connect_error = ConnectionRefusedError(
        "connection refused: 5432",
    )
    engine = _FakeEngine(
        dialect_name="postgresql",
        connect_error=connect_error,
    )
    ledger = _FakeLedger(engine)

    with pytest.raises(PgVectorPreflightError) as excinfo:
        await check_pgvector(ledger)
    assert excinfo.value.exit_code == EXIT_PGVECTOR_QUERY_FAILED
    msg = str(excinfo.value)
    assert "ConnectionRefusedError" in msg
    assert "5432" in msg
    # Underlying exception chain preserved so traceback shows the real
    # cause (asyncpg / driver layer).
    assert excinfo.value.__cause__ is connect_error


@pytest.mark.asyncio
async def test_query_permission_error_surfaces_underlying_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Surface the case where the connection works but the role lacks
    # SELECT on pg_extension. The execute call raises; we should
    # preserve the message so the operator knows it's a permission
    # problem, not a missing-extension problem.
    _enable_embedding(monkeypatch)
    execute_error = PermissionError(
        "permission denied for table pg_extension",
    )
    engine = _FakeEngine(
        dialect_name="postgresql",
        execute_error=execute_error,
    )
    ledger = _FakeLedger(engine)

    with pytest.raises(PgVectorPreflightError) as excinfo:
        await check_pgvector(ledger)
    assert excinfo.value.exit_code == EXIT_PGVECTOR_QUERY_FAILED
    assert "permission denied" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Required-detection coverage
# ---------------------------------------------------------------------------


def test_required_detection_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    pg = _FakeLedger(_FakeEngine(dialect_name="postgresql"))
    lite = _FakeLedger(_FakeEngine(dialect_name="sqlite"))

    # Default-off: required on neither.
    assert is_pgvector_required(pg) is False
    assert is_pgvector_required(lite) is False

    # Gather knob on: required on PG, not on SQLite.
    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    assert is_pgvector_required(pg) is True
    assert is_pgvector_required(lite) is False

    monkeypatch.delenv("WORMBASE_GATHER_VIA_PROJECTION")

    # Embedding knob on: required on PG, not on SQLite.
    monkeypatch.setenv("WORMBASE_EMBEDDING_ENABLED", "yes")
    assert is_pgvector_required(pg) is True
    assert is_pgvector_required(lite) is False


def test_ledger_without_engine_skips_preflight() -> None:
    # InMemoryLedger lacks an ``engine`` attribute — must short-circuit
    # to "not required" (we don't crash boot for in-memory test ledgers).
    class _NoEngineLedger:
        pass

    ledger = _NoEngineLedger()
    assert is_pgvector_required(ledger) is False
