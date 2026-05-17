"""Root-level pytest fixtures for the WormBase 6-layer QA env.

Layers covered here:

- L3 (contract)     — `test_ledger`, `slack_mock` (stubs)
- L4 (service)      — `test_postgres` via testcontainers + bootstrapped
                      `Ledger`
- L5 (integration)  — `compose_test` context manager that brings up
                      `infra/docker-compose.test.yml`

Every fixture is intentionally side-effect-free until first use, so
collection of L1/L2/L3 tests stays fast (no Docker probing).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Repository paths — make them importable everywhere.
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
COMPOSE_TEST_FILE: Path = REPO_ROOT / "infra" / "docker-compose.test.yml"
FIXTURES_ROOT: Path = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# L4: ephemeral Postgres via testcontainers.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_postgres():  # type: ignore[no-untyped-def]
    """A session-scoped throwaway Postgres reachable via SQLAlchemy DSN.

    Uses testcontainers-python so each CI run / each developer pytest
    invocation gets its own container. The container lives for the
    duration of the pytest session and is torn down at the end.

    On OrbStack: works out of the box — testcontainers reads
    DOCKER_HOST from the environment (OrbStack sets it automatically).
    On Docker Desktop / colima / podman: same story.

    Skips the test if Docker is not reachable rather than failing
    so that L1/L2/L3 contributors aren't forced to run Docker.
    """
    pytest.importorskip("testcontainers")

    from testcontainers.postgres import PostgresContainer

    try:
        container = PostgresContainer("postgres:16")
        container.with_env("POSTGRES_DB", "wormbase_test")
        container.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"testcontainers/Docker unavailable: {exc}")

    # Translate the JDBC-style URL the lib hands back into asyncpg form.
    raw = container.get_connection_url()
    # raw format: postgresql+psycopg2://user:pwd@host:port/wormbase_test
    asyncpg_dsn = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    sync_dsn = raw.replace("postgresql+psycopg2://", "postgresql://")

    obj: dict[str, Any] = {
        "container": container,
        "dsn": asyncpg_dsn,
        "sync_dsn": sync_dsn,
        "host": container.get_container_host_ip(),
        "port": int(container.get_exposed_port(5432)),
    }

    try:
        yield obj
    finally:
        with contextlib.suppress(Exception):
            container.stop()


# ---------------------------------------------------------------------------
# L4: bootstrapped real Ledger backed by `test_postgres`.
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_ledger(test_postgres) -> AsyncIterator[Any]:  # type: ignore[no-untyped-def]
    """Yields a `wormbase_ledger.Ledger` whose schema is freshly applied."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from wormbase_ledger import Ledger
    from wormbase_ledger.schema import metadata

    engine = create_async_engine(test_postgres["dsn"])
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    await engine.dispose()

    ledger = Ledger(test_postgres["dsn"])
    try:
        yield ledger
    finally:
        await ledger.dispose()


# ---------------------------------------------------------------------------
# L3+: Slack mock — currently a recording stub.
# ---------------------------------------------------------------------------


class SlackMock:
    """Minimal Slack mock surface for tests.

    Today: a recorder. Tests push synthetic Slack events at the worm via
    other entry points (the channel-adapter session JSONL fixture path,
    or by calling `SlackLurker._handle_event` directly), then assert
    against `mock.outbound` to see what the worm tried to send back.

    Tomorrow: this class will gain a real aiohttp test server that
    answers `chat.postMessage`, `auth.test`, etc. When that lands,
    integration tests can flip a flag instead of changing fixture
    plumbing.
    """

    def __init__(self) -> None:
        self.outbound: list[dict[str, Any]] = []
        self.inbound: list[dict[str, Any]] = []

    def record_outbound(self, payload: dict[str, Any]) -> None:
        self.outbound.append(dict(payload))

    def record_inbound(self, payload: dict[str, Any]) -> None:
        self.inbound.append(dict(payload))

    def reset(self) -> None:
        self.outbound.clear()
        self.inbound.clear()


@pytest.fixture
def slack_mock() -> SlackMock:
    """Stub Slack mock; deterministic and Docker-free."""
    return SlackMock()


# ---------------------------------------------------------------------------
# L5: docker-compose.test.yml lifecycle.
# ---------------------------------------------------------------------------


def _have_docker() -> bool:
    return shutil.which("docker") is not None


def _wait_for_port(host: str, port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


class _ComposeTest:
    """Context manager that runs the test compose stack."""

    def __init__(self, project: str = "wormbase-test-pytest") -> None:
        self.project = project
        self._up = False
        self.compose_file = COMPOSE_TEST_FILE
        self.postgres_dsn = (
            "postgresql+asyncpg://wormbase:wormbase@localhost:5433/wormbase_test"
        )

    def _cmd(self, *extra: str) -> list[str]:
        return [
            "docker", "compose",
            "--project-directory", str(REPO_ROOT),
            "--project-name", self.project,
            "-f", str(self.compose_file),
            *extra,
        ]

    def up(self, *, services: list[str] | None = None, wait_seconds: float = 60.0) -> None:
        args = ["up", "-d", "--remove-orphans"]
        if services:
            args.extend(services)
        subprocess.run(self._cmd(*args), check=True)  # noqa: S603,S607
        # Wait for postgres-test on 5433.
        ok = _wait_for_port("127.0.0.1", 5433, timeout_s=wait_seconds)
        if not ok:
            raise RuntimeError("postgres-test did not become reachable on :5433")
        self._up = True

    def down(self) -> None:
        if not self._up:
            return
        subprocess.run(  # noqa: S603,S607
            self._cmd("down", "-v", "--remove-orphans"),
            check=False,
        )
        self._up = False

    def exec(self, service: str, *cmd: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603,S607
            self._cmd("exec", "-T", service, *cmd),
            check=False,
            capture_output=True,
            text=True,
        )

    def logs(self, service: str | None = None, tail: int = 200) -> str:
        args = ["logs", f"--tail={tail}"]
        if service:
            args.append(service)
        result = subprocess.run(  # noqa: S603,S607
            self._cmd(*args), check=False, capture_output=True, text=True,
        )
        return result.stdout + "\n" + result.stderr


@pytest.fixture(scope="session")
def compose_test() -> Iterator[_ComposeTest]:
    """Session-scoped lifecycle for `infra/docker-compose.test.yml`.

    Tests that use this fixture are implicitly L5 (integration). They
    boot the test compose stack ONCE for the session, share it across
    tests, and tear it down at the end.

    Skips the whole session-fixture if Docker isn't present so that
    plain `pytest` on a Docker-less machine still completes.
    """
    if not _have_docker():
        pytest.skip("docker not available — skipping L5 compose tests")
    if os.environ.get("WORMBASE_SKIP_COMPOSE") == "1":
        pytest.skip("WORMBASE_SKIP_COMPOSE=1 — skipping L5 compose tests")

    ct = _ComposeTest()
    try:
        ct.up()
        yield ct
    finally:
        ct.down()


# ---------------------------------------------------------------------------
# Async loop fixture — all worm-core/governance/ledger tests are async.
# We register pytest-asyncio "auto" mode at the file level via markers.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Session-scoped event loop so testcontainers/compose can survive across tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
