"""P14 — two-tenant determinism stage demo (driver).

This is the engine behind ``make stage-replay-demo`` and
``scripts/stage_replay_demo.sh``. It answers council Q8 (McKinney):

    "Wire-replay t=0→460s on two clean tenants — show hashes match
     on stage."

Determinism strategy
====================

Two **fresh** tenants spin up in-process. Each tenant is an isolated
``InMemoryLedger`` carrying a distinct ``company_id``. The same
canonical wire-event JSONL (``tests/fixtures/install_arc.jsonl``) is
streamed into both tenants via the production ``WireReplayer`` —
**the same code path the live channel-adapter uses**, no demo seam,
no flow-bypass. Once both replays settle we compute each tenant's
terminal projection hash via ``InMemoryLedger.replay`` and compare.

If two clean tenants, fed the same wire, produce byte-identical
projection hashes, the C2 (deterministic output) Triad criterion
is tactile.

Why in-process and not two ``docker compose --project-name`` stacks?
The PRD invites either; the in-process variant is what makes the
demo land in <2 min on a stock laptop without Postgres/Docker
warm-up. The hash compared here is the same hash the DB-backed
``Ledger.replay`` produces for the same projection bundle (same
``hash_of_projections`` body in ``packages/ledger/src/wormbase_ledger
/replay.py``). Both backends share the projection builder. The
production-only docker variant is documented in ``stage_replay_demo
.sh`` as a flag for the operator who wants to prove this on the
real wire.

TTY output
==========

The output frame is ASCII-banner-large so the back row of the
auditorium can read both terminal hashes side by side. Hashes are
rendered in two colour-free 16-character chunks separated by an
ASCII pipe so they line up under projector colour-distortion.

Exit codes
==========

* 0 — hashes match.
* 1 — hashes diverge (the determinism thesis is broken; show the
  diagnostic and stop the show).
* 2 — fixture missing or malformed; pre-flight failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ensure the workspace packages are importable when run via plain
# ``python scripts/stage_replay_demo.py`` (i.e. without ``uv run``).
# Mirrors the ``sys.path`` layout that ``uv run`` would establish.
_PKG_PATHS = [
    REPO_ROOT / "packages" / "ledger" / "src",
    REPO_ROOT / "apps" / "channel-adapter" / "src",
]
for p in _PKG_PATHS:
    s = str(p)
    if p.exists() and s not in sys.path:
        sys.path.insert(0, s)

from wormbase_channel_adapter.wire_replay import WireReplayer  # noqa: E402
from wormbase_ledger import InMemoryLedger  # noqa: E402

DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "install_arc.jsonl"

# Two byte-distinct UUIDs so the company_id namespacing is visibly
# different on stage. The hashes of *projections* must still match —
# company_id does not enter the projection bundle.
TENANT_A_ID = UUID("00000000-0000-0000-0000-000000000a1a")
TENANT_B_ID = UUID("00000000-0000-0000-0000-000000000b2b")


def _print_banner_line(text: str, width: int = 80, fill: str = "═") -> None:
    """Print a banner line padded with the fill character."""
    pad = max(0, width - len(text) - 2)
    left = pad // 2
    right = pad - left
    print(f"{fill * left} {text} {fill * right}", flush=True)


def _print_hash_split(label: str, hash_hex: str) -> None:
    """Print HASH split into 16-char halves so it lines up under projection.

    A 64-char hex hash is hard to read at presentation distance. Two
    16-char chunks separated by ``│`` keep the visual cadence even when
    a projector dims the trailing characters.
    """
    halves = [hash_hex[i : i + 16] for i in range(0, len(hash_hex), 16)]
    rendered = "  ".join(halves)
    print(f"  {label:<10s} │ {rendered}", flush=True)


def _print_two_column_block(
    a_label: str,
    a_hash: str,
    b_label: str,
    b_hash: str,
) -> None:
    """Render the two terminal hashes side by side, large enough for stage."""
    print()
    _print_banner_line("TENANT A", width=78, fill="─")
    _print_hash_split(a_label, a_hash)
    print()
    _print_banner_line("TENANT B", width=78, fill="─")
    _print_hash_split(b_label, b_hash)
    print()


def _verdict_banner(matched: bool) -> None:
    print()
    if matched:
        # ASCII-art verdict. Block-letters keep the back row readable.
        print("╔══════════════════════════════════════════════════════════════════════════╗")
        print("║                                                                          ║")
        print("║   ██   ██  █████  ███████ ██   ██     ███    ███  █████  ████████ ██  ██ ║")
        print("║   ██   ██ ██   ██ ██      ██   ██     ████  ████ ██   ██    ██    ██  ██ ║")
        print("║   ███████ ███████ ███████ ███████     ██ ████ ██ ███████    ██    ██████ ║")
        print("║   ██   ██ ██   ██      ██ ██   ██     ██  ██  ██ ██   ██    ██    ██  ██ ║")
        print("║   ██   ██ ██   ██ ███████ ██   ██     ██      ██ ██   ██    ██    ██  ██ ║")
        print("║                                                                          ║")
        print("║                BYTE-IDENTICAL DETERMINISM CONFIRMED                      ║")
        print("║                                                                          ║")
        print("╚══════════════════════════════════════════════════════════════════════════╝")
    else:
        print("╔══════════════════════════════════════════════════════════════════════════╗")
        print("║                                                                          ║")
        print("║   ██   ██  █████  ███████ ██   ██     ██████  ██ ███████ ███████         ║")
        print("║   ██   ██ ██   ██ ██      ██   ██     ██   ██ ██ ██      ██              ║")
        print("║   ███████ ███████ ███████ ███████     ██   ██ ██ █████   █████           ║")
        print("║   ██   ██ ██   ██      ██ ██   ██     ██   ██ ██ ██      ██              ║")
        print("║   ██   ██ ██   ██ ███████ ██   ██     ██████  ██ ██      ██              ║")
        print("║                                                                          ║")
        print("║                  HASHES DIVERGED — DETERMINISM BROKEN                    ║")
        print("║                                                                          ║")
        print("╚══════════════════════════════════════════════════════════════════════════╝")
    print()


async def _replay_into_tenant(
    fixture_path: Path,
    company_id: UUID,
) -> tuple[InMemoryLedger, int]:
    """Replay ``fixture_path`` into a fresh ledger; return (ledger, count)."""
    ledger = InMemoryLedger()
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture_path,
    )
    n = await replayer.run()
    return ledger, n


async def _terminal_hash(ledger: InMemoryLedger, company_id: UUID) -> str:
    """Compute the hex of the ledger's terminal projection hash.

    ``until_ts`` is set far in the future so every replayed entry is
    folded into the projection bundle.
    """
    far_future = datetime.now(UTC) + timedelta(days=365 * 10)
    snap = await ledger.replay(company_id, until_ts=far_future)
    return snap.hash_of_projections.hex()


async def _run(fixture_path: Path) -> int:
    """Drive the demo. Return process exit code."""
    if not fixture_path.exists():
        print(
            f"[stage-replay-demo] fixture missing: {fixture_path}",
            file=sys.stderr,
        )
        return 2

    line_count = sum(1 for line in fixture_path.read_text(encoding="utf-8").splitlines() if line.strip())
    if line_count == 0:
        print(
            f"[stage-replay-demo] fixture empty: {fixture_path}",
            file=sys.stderr,
        )
        return 2

    print()
    _print_banner_line("WORMBASE — TWO-TENANT DETERMINISM (P14)", width=80, fill="═")
    print()
    print(f"  fixture        : {fixture_path.relative_to(REPO_ROOT)}")
    print(f"  wire events    : {line_count}")
    print(f"  tenant A id    : {TENANT_A_ID}")
    print(f"  tenant B id    : {TENANT_B_ID}")
    print("  primitive      : channel_adapter.WireReplayer (production code path)")
    print()
    _print_banner_line("REPLAYING…", width=80, fill="─")

    started = time.perf_counter()

    # Run both replays concurrently — clean tenants, no shared state,
    # no cross-talk. ``InMemoryLedger`` is per-process state so the two
    # ledgers cannot collide.
    (a_ledger, a_count), (b_ledger, b_count) = await asyncio.gather(
        _replay_into_tenant(fixture_path, TENANT_A_ID),
        _replay_into_tenant(fixture_path, TENANT_B_ID),
    )

    a_hash = await _terminal_hash(a_ledger, TENANT_A_ID)
    b_hash = await _terminal_hash(b_ledger, TENANT_B_ID)

    elapsed = time.perf_counter() - started

    print(f"  tenant A       : replayed {a_count} events")
    print(f"  tenant B       : replayed {b_count} events")
    print(f"  wall-clock     : {elapsed*1000:.0f} ms")
    print()

    _print_two_column_block(
        a_label="hash",
        a_hash=a_hash,
        b_label="hash",
        b_hash=b_hash,
    )

    matched = a_hash == b_hash and a_count == b_count and a_count > 0
    _verdict_banner(matched)

    if not matched:
        # Diagnostic on stderr — auditor / operator gets a precise
        # account of what diverged. The stage frame above is the
        # moment that reads from the back row; this is the receipt.
        print(
            f"[stage-replay-demo] DIVERGED:\n"
            f"  tenant_a_count={a_count} hash={a_hash}\n"
            f"  tenant_b_count={b_count} hash={b_hash}",
            file=sys.stderr,
        )
        return 1

    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stage_replay_demo",
        description=(
            "WormBase P14 — replay the canonical install-arc JSONL into "
            "two fresh tenants in parallel and prove their terminal "
            "ledger-projection hashes are byte-identical."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help=f"Path to the wire-event JSONL (default: {DEFAULT_FIXTURE.relative_to(REPO_ROOT)}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_run(args.fixture))


if __name__ == "__main__":
    sys.exit(main())
