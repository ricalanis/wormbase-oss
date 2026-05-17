"""End-to-end test of the `wormbase verify` CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_cli_verify_reports_ok(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {"memory_id": str(uuid4()), "content": "c", "tags": []},
                "result_ref": "r",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )
    # Make sure the engine commits + closes before subprocess opens its own connection
    # (sqlite single-writer; commit is implicit via session_scope).
    await engine.dispose()

    env = {**os.environ, "WORMBASE_DB_URL": test_database_url}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "wormbase_ledger.cli",
            "verify",
            "--company-id",
            str(company_id),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"stdout: {r.stdout}\nstderr: {r.stderr}"
    out = json.loads(r.stdout)
    assert out == {
        "ok": True,
        "entries_checked": 4,
        "broken_at": None,
        "company_id": str(company_id),
    }


def test_cli_help_lists_verify_and_replay() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "wormbase_ledger.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "verify" in r.stdout
    assert "replay" in r.stdout
