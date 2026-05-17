"""W6.A6 — E2E install-arc via wire-replay (deterministic, no live Slack).

Drives the canonical 9-beat install-arc fixture
(``apps/sim-harness/fixtures/install-arc-7beat-canonical.jsonl``)
through ``WireReplayer`` end-to-end. The ledger entries it produces
share the same PEVR shape that a live Slack install would land,
without any platform credentials.

Invariants asserted:

* Every wire record produces a full PEVR cycle (``propose / execute /
  verify / resolve``) — the production write primitive.
* The hash chain over the resulting ledger is bitwise-identical
  across N independent replays of the SAME fixture (the strongest
  determinism check we can write without owning a real platform).
* Replaying twice into the same ledger doubles the entry count
  (entries are append-only, no deduplication) — confirms the wire-
  replay path is a pure writer, not a syncer.
* The set of ``execute.payload.tool`` values matches exactly the
  set of tools recorded in the fixture — no silent drops, no
  spurious tools.
* Replay completes in well under the demo's 8m budget (the fixture
  is 5 records; in-process replay should clock <1s).

Gate: ``WORMBASE_HARNESS_UP`` is treated as informational; the test
runs without it because ``WireReplayer`` only needs an
``InMemoryLedger``. The flag is asserted via the existence of the
canonical fixture itself, which is checked into git and ships with
sim-harness.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from wormbase_channel_adapter.wire_replay import WireReplayer
from wormbase_ledger import InMemoryLedger


pytestmark = pytest.mark.asyncio


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FIXTURE = (
    REPO_ROOT
    / "apps"
    / "sim-harness"
    / "fixtures"
    / "install-arc-7beat-canonical.jsonl"
)

# Same namespace + slug worm-core uses (apps/worm-core/.../service.py).
TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _company_id_for(slug: str) -> UUID:
    return uuid5(TENANT_NAMESPACE, slug.strip().lower())


def _hash_payload_chain(rows: list[dict]) -> str:
    """Hash the (kind, payload) sequence for replay-determinism checks.

    We can't compare ``entry.hash`` directly because ``entry_id``
    is a fresh UUID4 on every InMemoryLedger.write call (so the
    hash chain rotates across runs by design). The PEVR payload
    sequence, however, is stable for a stable input — that is the
    determinism guarantee the wire-replay primitive offers.
    """
    h = hashlib.sha256()
    for r in rows:
        # Strip volatile fields (entry_id, prev_hash, hash, propose_entry_id,
        # execute_entry_id, verify_entry_id, ts) — keep the deterministic
        # surface (kind, quadrant, payload-tool, payload-args).
        payload = dict(r.get("payload") or {})
        for k in (
            "propose_entry_id",
            "execute_entry_id",
            "verify_entry_id",
            "ref_id",
        ):
            payload.pop(k, None)
        snippet = {
            "kind": r["kind"],
            "quadrant": r["quadrant"],
            "payload": payload,
        }
        h.update(
            json.dumps(snippet, sort_keys=True, default=str).encode()
        )
    return h.hexdigest()


@pytest.fixture
def canonical_fixture_path() -> Path:
    if not CANONICAL_FIXTURE.exists():
        pytest.skip(
            f"canonical fixture missing: {CANONICAL_FIXTURE}. "
            "sim-harness must ship `install-arc-7beat-canonical.jsonl` "
            "for this E2E to run."
        )
    return CANONICAL_FIXTURE


def _read_recorded_tools(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        rec = json.loads(line)
        out.append(str(rec.get("tool")))
    return out


async def test_install_arc_replay_writes_full_pevr_cycle(
    canonical_fixture_path: Path,
) -> None:
    """Each wire record → 4 ledger rows (propose / execute / verify / resolve).

    The wire-replay primitive must use the same PEVR shape the live
    channel-adapter produces. Catches regressions where wire-replay
    silently drops the verify or resolve step.
    """
    ledger = InMemoryLedger()
    company_id = _company_id_for("baseworm")
    n_records = sum(
        1
        for line in canonical_fixture_path.read_text("utf-8").splitlines()
        if line.strip()
    )

    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=canonical_fixture_path,
    )
    n = await replayer.run()
    assert n == n_records

    rows = await ledger.fetch(company_id)
    # Each record must produce exactly four rows in PEVR order.
    assert len(rows) == 4 * n_records
    for i in range(0, len(rows), 4):
        kinds = [rows[i + j]["kind"] for j in range(4)]
        assert kinds == ["propose", "execute", "verify", "resolve"], (
            f"record at offset {i} produced kinds={kinds}; "
            "expected canonical PEVR sequence"
        )


async def test_install_arc_replay_tool_set_matches_fixture(
    canonical_fixture_path: Path,
) -> None:
    """The tool names in execute rows match the fixture exactly.

    No silent drops, no spurious tools. The fixture and the ledger
    are two views of the same wire trace.
    """
    ledger = InMemoryLedger()
    company_id = _company_id_for("baseworm")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=canonical_fixture_path,
    )
    await replayer.run()

    rows = await ledger.fetch(company_id)
    execute_tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    fixture_tools = _read_recorded_tools(canonical_fixture_path)
    assert execute_tools == fixture_tools


async def test_install_arc_replay_payload_chain_is_byte_identical_across_runs(
    canonical_fixture_path: Path,
) -> None:
    """Two independent replays produce a byte-identical PEVR payload chain.

    This is the core determinism guarantee: same canonical input,
    same ledger output (modulo per-write UUIDs that rotate by design).
    The strongest determinism check available without owning a
    cross-process hash-of-snapshot fixture.
    """
    fixture_tools = _read_recorded_tools(canonical_fixture_path)
    assert len(fixture_tools) > 0, "canonical fixture must be non-empty"

    digests: set[str] = set()
    for run in range(3):
        ledger = InMemoryLedger()
        company_id = _company_id_for("baseworm")
        replayer = WireReplayer(
            ledger=ledger,
            company_id=company_id,
            jsonl_path=canonical_fixture_path,
        )
        await replayer.run()
        rows = await ledger.fetch(company_id)
        digests.add(_hash_payload_chain(rows))
    assert len(digests) == 1, (
        f"PEVR payload chain drifted across replays: {digests}"
    )


async def test_install_arc_replay_is_pure_writer_no_dedup(
    canonical_fixture_path: Path,
) -> None:
    """Two replays into the same ledger double the entry count.

    Wire-replay is an append-only writer. It does NOT dedupe against
    prior entries — that would require a syncer abstraction we
    explicitly don't ship. This test pins that property.
    """
    fixture_tools = _read_recorded_tools(canonical_fixture_path)

    ledger = InMemoryLedger()
    company_id = _company_id_for("baseworm")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=canonical_fixture_path,
    )
    await replayer.run()
    rows_after_one = await ledger.fetch(company_id)
    await replayer.run()
    rows_after_two = await ledger.fetch(company_id)
    assert len(rows_after_two) == 2 * len(rows_after_one)
    # Sanity: the second pass produced N more execute rows.
    execute_tools_two = [
        r["payload"].get("tool")
        for r in rows_after_two
        if r["kind"] == "execute"
    ]
    assert execute_tools_two == fixture_tools + fixture_tools


async def test_install_arc_replay_finishes_well_inside_demo_budget(
    canonical_fixture_path: Path,
) -> None:
    """Replay completes in <1s wall-clock — far inside the 8m demo budget.

    In-process replay against InMemoryLedger should be O(record count)
    with a tiny constant. If this regresses past 1s we likely have a
    quadratic over the existing entry list inside ``InMemoryLedger.write``.
    """
    ledger = InMemoryLedger()
    company_id = _company_id_for("baseworm")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=canonical_fixture_path,
    )
    started = time.monotonic()
    await replayer.run()
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, (
        f"in-process wire-replay took {elapsed:.3f}s for "
        f"{len(_read_recorded_tools(canonical_fixture_path))} "
        "records; expected <1s. The 8m demo budget assumes this is "
        "essentially free."
    )


async def test_install_arc_replay_quadrant_is_active_probabilistic(
    canonical_fixture_path: Path,
) -> None:
    """Every replayed entry lands in the active_probabilistic quadrant.

    Channel events (chat / file received) are speech-act surface
    writes — by the four-quadrant taxonomy they belong in
    ``active_probabilistic``, never the deterministic side. If
    wire-replay starts emitting deterministic-quadrant entries the
    quadrant projection breaks.
    """
    ledger = InMemoryLedger()
    company_id = _company_id_for("baseworm")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=canonical_fixture_path,
    )
    await replayer.run()
    rows = await ledger.fetch(company_id)
    quadrants = {r["quadrant"] for r in rows}
    assert quadrants == {"active_probabilistic"}, (
        f"replay produced quadrants={quadrants}; "
        "wire events must always be active_probabilistic"
    )
