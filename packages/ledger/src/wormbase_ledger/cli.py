"""WormBase ledger CLI — `wormbase verify` and `wormbase replay`.

Commands
--------
``wormbase verify --company-id <UUID> [--json]``
    Walk the hash chain for the given company. Exit code 0 if intact,
    1 if broken. With ``--json``, emit a machine-parseable report.

``wormbase replay --company-id <UUID> --until-ts <RFC3339>``
    Rebuild projections to ``until_ts`` and emit
    ``{hash_of_projections, source_count, memory_count}``.

Configuration
-------------
``WORMBASE_DB_URL`` env var must be set to a SQLAlchemy URL pointing at
either Postgres (production) or SQLite (testing).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

import click

from wormbase_ledger.db import get_engine
from wormbase_ledger.replay import replay
from wormbase_ledger.verify import verify_company_chain


@click.group()
def main() -> None:
    """WormBase ledger CLI."""


def _db_url() -> str:
    try:
        return os.environ["WORMBASE_DB_URL"]
    except KeyError:
        click.echo("WORMBASE_DB_URL not set", err=True)
        sys.exit(2)


@main.command()
@click.option("--company-id", "company_id", required=True, type=str)
@click.option("--json", "as_json", is_flag=True, default=False)
def verify(company_id: str, as_json: bool) -> None:
    """Verify the hash chain for a company."""

    async def _run() -> int:
        engine = get_engine(_db_url())
        report = await verify_company_chain(engine, UUID(company_id))
        payload = {
            "ok": report.ok,
            "entries_checked": report.entries_checked,
            "broken_at": report.broken_at,
            "company_id": company_id,
        }
        if as_json:
            click.echo(json.dumps(payload, sort_keys=True))
        else:
            label = "OK" if report.ok else f"BROKEN at {report.broken_at}"
            click.echo(f"{label} ({report.entries_checked} entries)")
        return 0 if report.ok else 1

    sys.exit(asyncio.run(_run()))


@main.command("replay")
@click.option("--company-id", "company_id", required=True, type=str)
@click.option(
    "--until-ts",
    "until_ts",
    required=True,
    type=str,
    help="RFC 3339 timestamp; trailing 'Z' is accepted.",
)
def replay_cmd(company_id: str, until_ts: str) -> None:
    """Replay projections up to until_ts."""

    async def _run() -> None:
        engine = get_engine(_db_url())
        ts = datetime.fromisoformat(until_ts.replace("Z", "+00:00")).astimezone(UTC)
        snap = await replay(engine, UUID(company_id), ts)
        click.echo(
            json.dumps(
                {
                    "hash_of_projections": snap.hash_of_projections.hex(),
                    "source_count": len(snap.projections.sources),
                    "memory_count": len(snap.projections.memory),
                },
                sort_keys=True,
            )
        )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
