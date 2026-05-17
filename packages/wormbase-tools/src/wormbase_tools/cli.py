"""``wormbase-tools`` command-line interface.

Exposes a single entrypoint, ``wormbase-tools replay``, that an auditor
runs from a clean venv to reproduce a KPI value bit-for-bit from a
frozen ledger snapshot. See ``docs/oss-audit-replay.md`` for the
auditor-facing usage guide.

Exit-code contract
==================

* 0 — success. KPI value (or ``null``) printed to stdout.
* 1 — replay aborted. Diagnostic written to stderr in pseudo-diff
       format. Sub-cases:

         * malformed snapshot (missing fields, bad JSON, bad hex)
         * hash chain break (recomputed hash != stored hash, or
           prev_hash mismatch)
         * tenant_id resolves to no entries
         * requested kpi_id not present in snapshot

* 2 — invalid CLI invocation (handled by Click).

Stdout is reserved for the KPI value; everything else (logs,
diagnostics, progress) goes to stderr. Auditor scripts therefore can
``DIFF=$(wormbase-tools replay snapshot.jsonl --to ...)`` cleanly.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

from wormbase_tools.replay import (
    ReplayError,
    emit_diff_to_stderr,
    emit_value_to_stdout,
    replay_snapshot,
)
from wormbase_tools.snapshot import SnapshotError


@click.group()
@click.version_option(package_name="wormbase-tools")
def main() -> None:
    """WormBase OSS audit toolkit.

    Reproduce a KPI value from a frozen ledger snapshot, without
    booting Postgres or any hosted service.
    """


@main.command("replay")
@click.argument(
    "snapshot",
    type=click.Path(
        exists=True, dir_okay=False, file_okay=True, readable=True, path_type=Path
    ),
)
@click.option(
    "--tenant",
    "tenant_id",
    type=str,
    default=None,
    help=(
        "Company/tenant id to pin replay to. Optional if the snapshot "
        "contains entries from exactly one tenant."
    ),
)
@click.option(
    "--to",
    "kpi_id",
    type=str,
    required=True,
    help=(
        "KPI identifier to look up. May be a stable string id "
        "(e.g. revenue.q3), a UUID from emit_kpi_proposed, or the "
        "demo-day shorthand (e.g. kpi_q3_revenue)."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help=(
        "Emit the full replay result as JSON instead of just the value. "
        "Includes terminal_hash, entry_count, and provenance trail."
    ),
)
@click.option(
    "--timing",
    is_flag=True,
    default=False,
    help="Print replay duration to stderr (auditor-friendly debugging).",
)
def replay_cmd(
    snapshot: Path,
    tenant_id: str | None,
    kpi_id: str,
    as_json: bool,
    timing: bool,
) -> None:
    """Replay SNAPSHOT and print the KPI value (or `null` if no value yet).

    SNAPSHOT is a JSONL file produced by the hosted plane's snapshot
    exporter. See `docs/oss-audit-replay.md` for the file format and a
    worked example.

    Exits 0 with the value on stdout if the KPI resolves; exits 1 with
    a diff-style diagnostic on stderr otherwise.
    """
    started = time.perf_counter()
    try:
        result = replay_snapshot(
            snapshot,
            tenant_id=tenant_id,
            kpi_id=kpi_id,
        )
    except SnapshotError as exc:
        emit_diff_to_stderr(snapshot, f"snapshot error: {exc}")
        sys.exit(1)
    except ReplayError as exc:
        emit_diff_to_stderr(snapshot, f"replay error: {exc}")
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.to_json(), sort_keys=True, separators=(",", ":")))
    else:
        emit_value_to_stdout(result)

    if timing:
        elapsed = time.perf_counter() - started
        sys.stderr.write(
            f"# replay: {result.entry_count} entries in {elapsed*1000:.1f}ms "
            f"(terminal_hash={result.terminal_hash_hex[:16]}…)\n"
        )

    sys.exit(0)


@main.group("mcp")
def mcp_group() -> None:
    """MCP-client helpers — Claude Desktop / Cursor / Cline config wiring.

    Reads the existing ``ConnectClaudeDesktopPanel`` shape from the
    dashboard (``apps/dashboard/components/mcp/ConnectClaudeDesktopPanel.tsx``)
    and emits an identical ``mcpServers`` config block. The CLI path
    is for operators who would rather paste a token via terminal than
    click through the dashboard — both flows write the same JSON.
    """


@mcp_group.command("connect")
@click.argument("tunnel_url", type=str)
@click.option(
    "--token",
    type=str,
    default=None,
    help=(
        "Bearer token to embed in the snippet. If omitted, falls back "
        "to the WORMBASE_LEDGER_API_TOKEN env var. The CLI does NOT "
        "issue a Person-scoped token — use the dashboard's /mcp tab "
        "for that. This flag is for the legacy flat-token path."
    ),
)
@click.option(
    "--name",
    "config_key",
    type=str,
    default="wormbase",
    help=(
        "Config-key name under ``mcpServers`` in Claude Desktop's "
        "claude_desktop_config.json. Defaults to ``wormbase``."
    ),
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
    default=None,
    help=(
        "Write the snippet to this path instead of stdout. The CLI does "
        "NOT touch the user's existing claude_desktop_config.json — it "
        "always writes a standalone snippet for the operator to merge."
    ),
)
def mcp_connect(
    tunnel_url: str,
    token: str | None,
    config_key: str,
    out_path: Path | None,
) -> None:
    """Emit a Claude Desktop config block for TUNNEL_URL.

    TUNNEL_URL is the public ``/mcp`` endpoint — a cloudflared tunnel
    URL, an Ngrok URL, or any reverse-proxy that fronts the worm-core
    MCP server. The snippet shape matches
    ``ConnectClaudeDesktopPanel.buildSnippet`` exactly, so a CLI-generated
    config and a dashboard-generated config are byte-identical.

    Example:

        \b
        wormbase-tools mcp connect https://worm-demo.example.com/mcp
        wormbase-tools mcp connect http://localhost:9911/mcp --token "$WORMBASE_LEDGER_API_TOKEN"

    Exit codes:
        0 on success (snippet on stdout, or written to --out).
        1 if no token is available (neither --token nor env var).
    """
    import os as _os

    effective_token = token or _os.environ.get("WORMBASE_LEDGER_API_TOKEN", "").strip()
    if not effective_token:
        sys.stderr.write(
            "error: no token provided. Pass --token <bearer> or set "
            "WORMBASE_LEDGER_API_TOKEN. For Person-scoped tokens, generate "
            "one via the dashboard's /mcp tab.\n"
        )
        sys.exit(1)

    snippet = build_claude_desktop_snippet(
        config_key=config_key,
        url=tunnel_url,
        token=effective_token,
    )

    if out_path is None:
        click.echo(snippet)
    else:
        out_path.write_text(snippet + "\n", encoding="utf-8")
        sys.stderr.write(
            f"# wrote {len(snippet)}-byte snippet to {out_path}\n"
            f"# merge into ~/Library/Application Support/Claude/"
            f"claude_desktop_config.json and restart Claude Desktop\n"
        )

    sys.exit(0)


def build_claude_desktop_snippet(
    *,
    config_key: str,
    url: str,
    token: str,
) -> str:
    """Build a Claude Desktop ``mcpServers`` config block.

    Mirrors ``ConnectClaudeDesktopPanel.buildSnippet`` byte-for-byte
    (2-space indent, sorted insertion-order keys via JS object literal).
    Tested in ``tests/test_cli.py::test_build_claude_desktop_snippet_matches_panel_shape``.
    """
    obj = {
        "mcpServers": {
            config_key: {
                "transport": "http",
                "url": url,
                "headers": {
                    "Authorization": f"Bearer {token}",
                },
            },
        },
    }
    return json.dumps(obj, indent=2)


if __name__ == "__main__":
    main()
