"""DEMO.1.B — Acme demo seed replay determinism.

The Acme SaaS demo tenant is seeded by replaying
``tests/fixtures/acme_demo_seed/events.jsonl`` through
:class:`WireReplayer`. This test enforces that two consecutive replays
of the JSONL produce byte-identical projections of the ledger row chain
— the demo cannot drift between rehearsal and live recording.

The mechanism mirrors :file:`test_wire_replay_byte_identical.py`:

* Seed every UUID and the wall-clock so the only stochastic source is
  the JSONL itself.
* Run the replay twice against fresh :class:`InMemoryLedger`
  instances.
* Canonicalize the row chain and compare hashes.

Per CLAUDE.md §1, the only deterministic backstop the repo permits is
wire-replay (no flow-bypass helpers). This test pins that contract for
the Acme demo specifically — if the JSONL or the wire-replay code path
diverges, this test fails before the demo does.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

from wormbase_channel_adapter.wire_replay import WireReplayer
from wormbase_ledger import InMemoryLedger


ACME_FIXTURE: Path = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "acme_demo_seed"
    / "events.jsonl"
)


# ---------------------------------------------------------------------------
# Determinism helpers (mirrors test_wire_replay_byte_identical.py)
# ---------------------------------------------------------------------------


class _DeterministicUUIDFactory:
    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> UUID:
        self._counter += 1
        return UUID(int=self._counter)


class _FrozenDatetime:
    _frozen = datetime(2026, 5, 1, 9, 0, 0)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        if tz is None:
            return cls._frozen
        return cls._frozen.replace(tzinfo=tz)

    def __new__(cls, *args: Any, **kwargs: Any) -> datetime:  # type: ignore[misc]
        return datetime(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(datetime, name)


def _canonical_row_summary(rows: list[dict[str, Any]]) -> str:
    summary: list[dict[str, Any]] = []
    for r in rows:
        summary.append(
            {
                "seq": r["seq"],
                "kind": r["kind"],
                "payload": r["payload"],
                "prev_hash": (
                    r["prev_hash"].hex()
                    if isinstance(r["prev_hash"], (bytes, bytearray))
                    else r["prev_hash"]
                ),
                "hash": (
                    r["hash"].hex()
                    if isinstance(r["hash"], (bytes, bytearray))
                    else r["hash"]
                ),
            }
        )
    return json.dumps(
        summary, sort_keys=True, separators=(",", ":"), default=str,
    )


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def _replay_to_hash() -> str:
    """One deterministic replay of the Acme JSONL → canonical row hash."""
    factory = _DeterministicUUIDFactory()
    company_id = UUID(int=0xACEACE)

    ledger = InMemoryLedger()
    replayer = WireReplayer(
        ledger=ledger, company_id=company_id, jsonl_path=ACME_FIXTURE,
    )
    with patch(
        "wormbase_channel_adapter.wire_replay.uuid4", new=factory,
    ), patch(
        "wormbase_ledger.ledger_api.uuid4", new=factory,
    ), patch(
        "wormbase_ledger.ledger_api.datetime", new=_FrozenDatetime,
    ):
        await replayer.run()
    rows = await ledger.fetch(company_id)
    return _sha256_hex(_canonical_row_summary(rows))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_acme_demo_fixture_exists() -> None:
    """The Acme demo fixture is checked in alongside the contract test."""
    assert ACME_FIXTURE.is_file(), (
        f"acme demo fixture missing at {ACME_FIXTURE}"
    )


def test_acme_demo_replay_byte_identical_across_two_runs() -> None:
    """Two consecutive replays produce the same canonical-row hash.

    This is the authoritative determinism contract for the Acme demo
    seed. Demo recording, eval-day re-runs, and CI all replay this
    fixture and must agree on the chain hash.
    """
    a = asyncio.run(_replay_to_hash())
    b = asyncio.run(_replay_to_hash())
    assert a == b, (
        "Acme demo seed replay is non-deterministic:\n"
        f"  run 1: {a}\n"
        f"  run 2: {b}\n"
        "Inspect the JSONL for non-canonical fields or the wire-replay "
        "PEVR primitive for un-seeded UUIDs / clocks."
    )


def test_acme_demo_fixture_is_pure_wire_format() -> None:
    """Every line in the JSONL is a recognised channel-adapter wire tool.

    Per CLAUDE.md §1 invariant: no flow-bypass shortcuts. Every demo
    seed entry must arrive via the production wire format so the
    dashboard cannot tell replayed entries from live ones.
    """
    permitted = {
        "channel_adapter.emit_chat_received",
        "channel_adapter.emit_chat_sent",
        "channel_adapter.emit_file_received",
    }
    with ACME_FIXTURE.open("r", encoding="utf-8") as f:
        for idx, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            rec = json.loads(line)
            tool = rec.get("tool")
            assert tool in permitted, (
                f"acme demo fixture line {idx} has non-wire tool {tool!r}; "
                f"only {permitted} are allowed."
            )


def test_acme_demo_fixture_covers_five_step_arc() -> None:
    """The fixture exercises every beat of the 5-step product arc.

    Acceptance gate: if a beat is dropped (e.g. an editor accidentally
    removes the schema-drift line), the demo loses an evaluator-
    convincing surface. Pin the beat coverage here.
    """
    text = ACME_FIXTURE.read_text(encoding="utf-8").lower()
    # Step 1 — connect / welcome
    assert "welcome" in text
    # Step 2 — grow the lake (file drop + DM credential + drift)
    assert "q3_revenue_actuals.csv" in text
    assert "postgres://" in text
    assert "schema changed" in text or "renamed to" in text
    # Step 3 — build concurrently (decisions, recurring question,
    # system-map mentions, position cue, resource owner cue)
    assert text.count("what's our q3 churn") + text.count("q3 churn") >= 4
    assert "maya is the sales lead" in text
    assert "bob owns the q3_revenue kpi" in text
    # Step 4 — produce (kpi mentions + data product publish)
    assert "active customer" in text
    assert "churn_rate" in text
    assert "process map" in text or "decision loop" in text
    # Step 5 — self-improve (phenomenon-gap + experiment + lesson)
    assert "high_value_customer" in text or "high-value customer" in text
    assert "experiment" in text
    assert "lesson" in text
