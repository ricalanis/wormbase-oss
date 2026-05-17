"""DEMO.1.A — Acme SaaS demo seed.

Provides the loader half of the ``wormbase-sim acme-demo`` subcommand.
Reads :file:`tests/fixtures/acme_demo_seed/events.jsonl` and exposes
helpers the CLI uses to push the fixture through the production
:class:`WireReplayer` PEVR primitive.

Two design constraints (CLAUDE.md §1):

1. **No flow-bypass**: the seed writes ledger rows by replaying the
   wire fixture through the same code path the live channel-adapter
   uses. There are no direct-ledger-write helpers anywhere in this
   module.
2. **Production-shape**: every fixture line is a recognised
   ``channel_adapter.emit_*`` tool. The contract test
   :file:`tests/contract/test_acme_demo_seed_determinism.py` enforces
   that and the byte-identical determinism of the replay.

The CLI subcommand wires this module into ``wormbase_sim_harness.cli``
under ``demo acme-demo``; see that module for the user-facing flag set.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("wormbase.sim.seed_acme")


# Canonical demo tenant. Documented in the spec; pinned here so a
# rename surfaces as one diff.
ACME_TENANT_SLUG: str = "acme-saas"


# Anchor the fixture was written against. The Acme fixture intentionally
# uses a different epoch to install_arc_seed so the two demos do not
# share timestamps in the trace stream.
ACME_FIXTURE_EPOCH: datetime = datetime.fromisoformat(
    "2026-05-01T09:00:00+00:00",
)


def default_acme_fixture_path() -> Path:
    """Locate ``tests/fixtures/acme_demo_seed/events.jsonl`` from this module.

    Walks upward looking for a ``tests/fixtures/acme_demo_seed`` dir so
    the helper survives re-rooting under a different layout (mirrors
    ``seed_loader.default_fixture_dir``). Falls back to the canonical
    repo layout; a missing file surfaces as a clean FileNotFoundError
    when the CLI calls into the replayer.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = (
            parent / "tests" / "fixtures" / "acme_demo_seed" / "events.jsonl"
        )
        if candidate.is_file():
            return candidate
    return (
        here.parents[4]
        / "tests"
        / "fixtures"
        / "acme_demo_seed"
        / "events.jsonl"
    )


def acme_seed_summary(jsonl_path: Path | None = None) -> dict[str, Any]:
    """Return a small summary of the Acme fixture without replaying it.

    Used by the CLI's dry-run mode (``--dry-run``) so an operator can
    see what the seed *would* do without touching the ledger. The
    summary is read from the JSONL only — no LLM calls, no DB writes.
    """
    import json

    path = jsonl_path or default_acme_fixture_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"acme demo fixture missing at {path}. The fixture is "
            f"checked into tests/fixtures/acme_demo_seed/events.jsonl."
        )
    tools_count: dict[str, int] = {}
    beats: set[int] = set()
    channels: set[str] = set()
    senders: set[str] = set()
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            n += 1
            tool = str(rec.get("tool", ""))
            tools_count[tool] = tools_count.get(tool, 0) + 1
            beat = rec.get("beat_index")
            if isinstance(beat, int):
                beats.add(beat)
            args = rec.get("args") or {}
            ch = args.get("channel_id")
            if isinstance(ch, str):
                channels.add(ch)
            sp = args.get("sender_person")
            if isinstance(sp, str):
                senders.add(sp)
    return {
        "fixture_path": str(path),
        "tenant_slug": ACME_TENANT_SLUG,
        "events_total": n,
        "tools_count": tools_count,
        "distinct_beats": sorted(beats),
        "distinct_channels": sorted(channels),
        "distinct_senders": sorted(senders),
    }


__all__ = [
    "ACME_FIXTURE_EPOCH",
    "ACME_TENANT_SLUG",
    "acme_seed_summary",
    "default_acme_fixture_path",
]
