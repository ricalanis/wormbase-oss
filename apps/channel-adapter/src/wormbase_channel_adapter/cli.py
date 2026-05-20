"""``wormbase-channel-adapter`` CLI.

Two commands:

``run``        — start the long-running tail+emit loop (the docker-compose
                 entrypoint).

``inspect``    — one-shot ledger query: list recent ``chat_received`` and
                 ``chat_sent`` entries for the configured tenant. Useful
                 as the integration-test smoke check (``wormbase verify``
                 covers hash-chain integrity but not the kind filter we
                 care about here).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import click

from wormbase_channel_adapter.service import run_service
from wormbase_channel_adapter.tenant import tenant_to_company_uuid


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        click.echo(f"{name} not set", err=True)
        sys.exit(2)
    return val


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(verbose: bool) -> None:
    """WormBase channel-ledger adapter."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )


@main.command("run")
@click.option(
    "--sessions-path",
    default=lambda: os.environ.get(
        "OPENCLAW_SESSIONS_PATH", "/openclaw-state/agents/main/sessions"
    ),
    show_default=True,
)
@click.option(
    "--state-path",
    default=lambda: os.environ.get(
        "WORMBASE_ADAPTER_STATE_PATH", "/var/lib/wormbase-channel-adapter/state.json"
    ),
    show_default=True,
)
@click.option(
    "--tenant",
    default=lambda: os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
    show_default=True,
)
@click.option("--poll-interval", default=0.5, type=float, show_default=True)
@click.option(
    "--openclaw-log-dir",
    default=lambda: os.environ.get("OPENCLAW_LOG_DIR"),
    show_default=True,
    help="Path to OpenClaw's global log directory (e.g. /tmp/openclaw).",
)
def run_cmd(
    sessions_path: str,
    state_path: str,
    tenant: str,
    poll_interval: float,
    openclaw_log_dir: str | None,
) -> None:
    """Tail OpenClaw sessions and append chat ledger entries."""
    dsn = _env("WORMBASE_LEDGER_DSN")
    # Slack bot token enables the OpenClaw-log capture path. Prefer the
    # observer-app token so the lurker and channel-adapter don't both
    # consume the same SocketMode connection budget; fall back to the
    # OpenClaw bot token (single-app dev setups).
    slack_bot_token = (
        os.environ.get("SLACK_BOT_TOKEN_OBSERVER_BASEWORM")
        or os.environ.get("SLACK_BOT_TOKEN_BASEWORM")
    )
    # Optional WhatsApp account — Phase 3 of the 2026-05-05
    # WhatsApp+provenance build. When set, the WhatsAppChannelAdapter
    # is wired into the openclaw-log dispatch table; absent, the dispatch
    # logs "no adapter registered" for whatsapp lines (graceful drop).
    whatsapp_account_id = os.environ.get("WHATSAPP_ACCOUNT_ID")
    from wormbase_core import silent_mode
    silent_mode.log_boot_state("channel-adapter")
    asyncio.run(
        run_service(
            ledger_dsn=dsn,
            sessions_path=sessions_path,
            state_path=state_path,
            tenant_slug=tenant,
            poll_interval_s=poll_interval,
            openclaw_log_dir=openclaw_log_dir,
            slack_bot_token=slack_bot_token,
            whatsapp_account_id=whatsapp_account_id,
        )
    )


@main.command("inspect")
@click.option(
    "--tenant",
    default=lambda: os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
    show_default=True,
)
@click.option("--limit", default=10, type=int, show_default=True)
@click.option(
    "--kinds",
    default="chat_received,chat_sent",
    show_default=True,
    help="Comma-separated ledger kinds to include.",
)
def inspect_cmd(tenant: str, limit: int, kinds: str) -> None:
    """List recent chat ledger entries for the configured tenant.

    Reads via wormbase_ledger.Ledger.fetch (no SQL); intended as the
    integration-test smoke check.
    """
    from wormbase_ledger import Ledger  # local import keeps CLI start cheap

    dsn = _env("WORMBASE_LEDGER_DSN")
    company_id = tenant_to_company_uuid(tenant)
    wanted = {k.strip() for k in kinds.split(",") if k.strip()}

    async def _run() -> None:
        ledger = Ledger(dsn)
        try:
            rows = await ledger.fetch(company_id)
        finally:
            await ledger.dispose()

        # We want the *execute* row of each chat PEVR group (that's where
        # the payload lives). Filter to executes whose payload.tool starts
        # with channel_adapter.emit_*.
        executes = [
            r
            for r in rows
            if r["kind"] == "execute"
            and isinstance(r["payload"], dict)
            and isinstance(r["payload"].get("tool"), str)
            and r["payload"]["tool"].startswith("channel_adapter.emit_")
        ]
        # Map back to the chat kind via the tool suffix.
        records = []
        for row in executes:
            tool = row["payload"]["tool"]
            kind = "chat_received" if tool.endswith("chat_received") else "chat_sent"
            if kind not in wanted:
                continue
            args = row["payload"].get("args", {})
            records.append(
                {
                    "seq": row["seq"],
                    "ts": row["ts"].isoformat(),
                    "kind": kind,
                    "channel_id": args.get("channel_id"),
                    "message_id": args.get("message_id"),
                    "text": (args.get("text") or "")[:160],
                }
            )
        # Tail the last `limit` entries (already in seq order).
        records = records[-limit:]
        click.echo(
            json.dumps(
                {
                    "tenant": tenant,
                    "company_id": str(company_id),
                    "count": len(records),
                    "entries": records,
                },
                indent=2,
                sort_keys=True,
            )
        )

    asyncio.run(_run())


@main.command("hermes-spike")
@click.option(
    "--sink-path",
    default=lambda: os.environ.get(
        "WORMBASE_HERMES_SPIKE_SINK",
        "/var/log/wormbase/hermes-spike.jsonl",
    ),
    show_default=True,
    help="Path to the JSONL file the spike endpoint appends to.",
)
@click.option(
    "--host",
    default=lambda: os.environ.get("WORMBASE_HERMES_SPIKE_HOST", "0.0.0.0"),
    show_default=True,
)
@click.option(
    "--port",
    default=lambda: int(os.environ.get("WORMBASE_HERMES_SPIKE_PORT", "18790")),
    type=int,
    show_default=True,
)
def hermes_spike_cmd(sink_path: str, host: str, port: int) -> None:
    """Run the Hermes H1 spike endpoint (POST /hermes-spike → JSONL).

    Block H Task H1 (docs/superpowers/specs/2026-04-27-openclaw-to-hermes-
    migration.md §5 Phase 0). This is a *spike-only* subcommand — it does
    not touch the ledger, does not read OpenClaw state, and is deleted
    when H2 lands the production HermesEventConsumer.
    """
    from wormbase_channel_adapter.spike_hermes import cli_entry

    cli_entry(sink_path=sink_path, host=host, port=port)


@main.command("wire-replay")
@click.option(
    "--tenant",
    default=lambda: os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
    show_default=True,
)
@click.option(
    "--jsonl",
    "jsonl_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a JSONL of recorded wire events.",
)
def wire_replay_cmd(tenant: str, jsonl_path: str) -> None:
    """Replay recorded InfraEvents into the ledger via PEVR.

    Same code path as the live channel-adapter — wire-replay is the
    deterministic backstop for CI + demo gates (PRD §8.3).
    """
    from pathlib import Path

    from wormbase_ledger import Ledger

    from wormbase_channel_adapter.wire_replay import WireReplayer

    dsn = _env("WORMBASE_LEDGER_DSN")
    company_id = tenant_to_company_uuid(tenant)

    async def _run() -> None:
        ledger = Ledger(dsn)
        try:
            replayer = WireReplayer(
                ledger=ledger,
                company_id=company_id,
                jsonl_path=Path(jsonl_path),
            )
            n = await replayer.run()
        finally:
            await ledger.dispose()
        click.echo(
            json.dumps(
                {"replayed": n, "jsonl": jsonl_path, "tenant": tenant},
                indent=2,
            )
        )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
