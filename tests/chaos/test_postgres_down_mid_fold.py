"""Chaos: Postgres connection drops mid-fold inside ProjectionRunner.

Failure mode
------------
``Ledger.fetch`` raises ``asyncpg.exceptions.ConnectionFailureError``
on the next polling cycle of ``ProjectionRunner.run_forever``.

Invariants the system MUST preserve
-----------------------------------
1. ``run_forever`` catches the exception and logs at WARNING (no crash,
   no silent swallow).
2. The poll loop survives — a follow-up cycle, once the ledger heals,
   completes successfully and the runner's cursor advances.
3. NO half-fold is persisted. The number of projection ``persist`` calls
   that occur during the failed cycle is zero. The ledger contents
   themselves remain unchanged.
4. ``GET /api/v1/ops/health`` reports ``postgres.status == "down"`` so
   the dashboard /ops red banner has truthful state to render.

Failure-injection point
-----------------------
We patch ``Ledger.fetch`` (the highest reasonable level — the dependency
boundary, not the wrapped function) on the runner's ledger to raise on
the second invocation. The first invocation seeds normal projections; the
second simulates Postgres dropping the connection mid-poll.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.projection_runner import ProjectionRunner
from wormbase_ledger import InMemoryLedger


API_TOKEN = "chaos-postgres-token"


class _SimulatedConnectionFailure(Exception):
    """Stand-in for ``asyncpg.exceptions.ConnectionFailureError``.

    We can't import asyncpg's symbol unconditionally — chaos tests must
    run on machines without asyncpg installed — so we synthesise an
    exception that flows through the same code path: any non-CancelledError
    raised by ``Ledger.fetch`` is caught, logged, and the runner keeps
    polling.
    """


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


# ---------------------------------------------------------------------------
# Invariant 1 + 2 + 3 — ProjectionRunner survives the drop
# ---------------------------------------------------------------------------


async def test_projection_runner_catches_postgres_drop_mid_fold_logs_warning(
    memory_ledger: InMemoryLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """The runner must catch the connection failure, log WARNING, retry.

    We patch ``session_scope`` and ``persist_projections`` in the
    projection_runner module so the test exercises only the
    fetch-failure code path without needing a real SQL engine. The
    InMemoryLedger has no ``engine`` attribute; the patches remove
    that dependency for chaos testing.
    """
    company_id = uuid4()

    # Seed one PEVR cycle so there's projection work to do.
    await memory_ledger.write(
        company_id=company_id,
        propose={"target_kind": "memory_written", "ref_id": str(uuid4()),
                 "reason": "seed", "proposed_by": "test"},
        execute_fn=lambda: {"tool": "emit_memory_written",
                            "args": {"memory_id": str(uuid4()),
                                     "content": "seed",
                                     "source_message_ids": []},
                            "result_ref": "seed"},
        verify_fn=lambda _e: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )

    # Stub out the SQL-engine bits so the InMemoryLedger path works.
    @contextlib.asynccontextmanager  # type: ignore[name-defined]  # set below
    async def _noop_session_scope(_engine: Any) -> AsyncIterator[Any]:
        yield None

    async def _noop_build_projections(_session: Any, _company_id: UUID) -> Any:
        return object()

    @contextlib.asynccontextmanager  # type: ignore[name-defined]
    async def _noop_engine_begin() -> AsyncIterator[Any]:
        yield None

    async def _noop_persist_projections(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _FakeEngine:
        def begin(self) -> Any:
            return _noop_engine_begin()
        def connect(self) -> Any:
            return _noop_engine_begin()

    memory_ledger.engine = _FakeEngine()  # type: ignore[attr-defined]

    runner = ProjectionRunner(
        memory_ledger, company_id, poll_interval_s=0.01,
    )

    persist_calls = {"count": 0}

    async def _track_persist(*_args: Any, **_kwargs: Any) -> None:
        persist_calls["count"] += 1

    with patch(
        "wormbase_core.projection_runner.session_scope", _noop_session_scope,
    ), patch(
        "wormbase_core.projection_runner.build_projections",
        _noop_build_projections,
    ), patch(
        "wormbase_core.projection_runner.persist_projections",
        _track_persist,
    ):
        # First run_once — should succeed (cursor advances).
        n = await runner.run_once()
        assert n >= 1
        cursor_after_first = runner.last_seq
        assert cursor_after_first > 0
        assert persist_calls["count"] == 1, "first cycle persists once"

        # Inject the failure: patch fetch on this ledger to raise.
        real_fetch = memory_ledger.fetch
        raised = {"count": 0}

        async def _failing_fetch(*args: Any, **kwargs: Any) -> Any:
            raised["count"] += 1
            raise _SimulatedConnectionFailure(
                "asyncpg connection dropped: server closed the connection",
            )

        with patch.object(memory_ledger, "fetch", _failing_fetch):
            # Drive run_forever for one cycle so the WARNING-log path
            # executes exactly the way it does in production.
            with caplog.at_level(
                logging.WARNING, logger="wormbase_core.projection_runner",
            ):
                task = asyncio.create_task(runner.run_forever())
                # Let the loop run long enough to hit the failing fetch.
                await asyncio.sleep(0.15)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Invariant 1: WARNING was logged. The runner did not crash.
        warnings = [
            rec for rec in caplog.records
            if rec.levelno >= logging.WARNING
            and "wormbase_core.projection_runner" == rec.name
        ]
        assert warnings, (
            "ProjectionRunner must log WARNING on Ledger.fetch failure, "
            "not silently swallow"
        )
        assert any(
            "cycle failed" in rec.getMessage()
            or "fetch" in rec.getMessage().lower()
            or "initial run failed" in rec.getMessage()
            for rec in warnings
        )

        # Invariant 2: at least one failed fetch happened (the runner
        # kept polling rather than dying on the first error).
        assert raised["count"] >= 1

        # Invariant 3: cursor did NOT advance during the failure.
        assert runner.last_seq == cursor_after_first, (
            "no half-fold: cursor must not advance when fetch fails"
        )
        # Invariant 3 cont'd: persist was NOT called during the failure.
        assert persist_calls["count"] == 1, (
            "persist count must not change while fetch is failing"
        )

        # Invariant 2 cont'd: once the ledger heals, the next cycle
        # works. (The ``patch.object(... fetch)`` is out of scope; the
        # real fetch is back. We verify by behaviour: a fresh fetch
        # returns the seeded rows without raising.)
        rows_after_heal = await memory_ledger.fetch(company_id)
        assert len(rows_after_heal) >= 4
        n2 = await runner.run_once()
        # No new ledger rows since the seed → run_once returns 0 but
        # does NOT raise, proving the runner is alive after the chaos.
        assert n2 == 0


# ---------------------------------------------------------------------------
# Invariant 3 — no half-fold leaks into the projection_* tables
# ---------------------------------------------------------------------------


async def test_postgres_drop_does_not_persist_a_half_fold(
    memory_ledger: InMemoryLedger,
) -> None:
    """When fetch raises, persist_projections is never called."""
    company_id = uuid4()

    runner = ProjectionRunner(
        memory_ledger, company_id, poll_interval_s=0.01,
    )

    persist_calls = {"count": 0}

    async def _track_persist(*args: Any, **kwargs: Any) -> None:
        persist_calls["count"] += 1

    # NB: build_projections / session_scope are NEVER reached because
    # the failing fetch short-circuits run_once. We still patch them
    # defensively in case the implementation reorders code.
    @contextlib.asynccontextmanager
    async def _noop_session_scope(_engine: Any) -> AsyncIterator[Any]:
        yield None

    async def _noop_build(*_args: Any, **_kwargs: Any) -> Any:
        return object()

    with patch(
        "wormbase_core.projection_runner.persist_projections",
        new=_track_persist,
    ), patch(
        "wormbase_core.projection_runner.session_scope",
        _noop_session_scope,
    ), patch(
        "wormbase_core.projection_runner.build_projections",
        _noop_build,
    ), patch.object(
        memory_ledger,
        "fetch",
        AsyncMock(side_effect=_SimulatedConnectionFailure("postgres down")),
    ):
        with pytest.raises(_SimulatedConnectionFailure):
            await runner.run_once()

    # Invariant 3: zero persists during a failed fetch — the projection
    # tables stay byte-stable when Postgres is wobbling.
    assert persist_calls["count"] == 0


# ---------------------------------------------------------------------------
# Invariant 4 — /ops/health reports postgres: down honestly
# ---------------------------------------------------------------------------


async def test_ops_health_reports_postgres_down_when_engine_raises(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """A broken engine surfaces as ``postgres.status == 'down'`` so the
    /ops red banner has truthful state to render."""
    # Attach a fake engine that raises on connect — this is exactly what
    # an asyncpg connection-failure looks like to the health probe.
    class _BrokenEngine:
        def connect(self) -> Any:
            raise _SimulatedConnectionFailure(
                "asyncpg.exceptions.ConnectionFailureError: server gone",
            )

    memory_ledger.engine = _BrokenEngine()  # type: ignore[attr-defined]

    resp = await client.get("/api/v1/ops/health", headers=_auth())
    assert resp.status == 200, await resp.text()
    body = await resp.json()

    assert body["postgres"]["status"] == "down"
    assert "ConnectionFailure" in body["postgres"]["message"] or "server gone" in body["postgres"]["message"]
    assert body["postgres"]["latencyMs"] is None
