"""Wire-replay byte-identical conformance (W6.A4).

The deterministic backstop for the production wire. Every recorded
JSONL fixture in :file:`apps/sim-harness/fixtures/` is replayed through
:class:`WireReplayer` against an empty :class:`InMemoryLedger`. The
resulting ledger row sequence is canonicalized + hashed, and the
hash is compared to a checked-in expected value next to the fixture.

This is the strongest production determinism check the suite has:
if a code path silently changes how a `chat_received` payload is
shaped, or how the PEVR primitive orders entries, or how
``canonical_json`` serializes any field, the hash diverges and this
test fails.

Determinism approach:

The :class:`InMemoryLedger` writer uses ``uuid4()`` and
``datetime.now()`` internally; both are non-deterministic. The replay
harness substitutes both:

* ``uuid4`` — a counter-seeded ``UUID`` factory replaces every site
  that mints entry-ids and replay-refs (the WireReplayer + the
  in-memory ledger). Counter starts at 1 per replay.
* ``datetime.now`` — every entry's ``ts`` is set to the JSONL's
  recorded timestamp via ``timestamp=`` (the InMemoryLedger uses
  the kwarg when present); we patch a frozen wall-clock for the
  PEVR step that doesn't carry a JSONL ts.

The hash is computed over the canonical JSON of the
``(seq, kind, prev_hash, hash)`` tuple per row — robust to any
transient metadata (timestamps, entry_ids) we've already pinned.

The expected-hash files live next to the fixtures, named
``<fixture>.expected_hash``. They're checked in. First-run regen is
gated by the ``WORMBASE_REGEN_WIRE_REPLAY_HASHES=1`` env var; CI
fails-loud when an unexpected hash is produced.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from wormbase_channel_adapter.wire_replay import WireReplayer
from wormbase_ledger import InMemoryLedger


FIXTURES_DIR = Path(
    __file__
).resolve().parents[2] / "apps" / "sim-harness" / "fixtures"


# ---------------------------------------------------------------------------
# UUID + clock seeding
# ---------------------------------------------------------------------------


class _DeterministicUUIDFactory:
    """A counter-driven UUID factory.

    Each call returns ``UUID(int=counter)``. The factory is shared
    between the wire-replay module and the in-memory ledger module via
    monkeypatch — every UUID minted during a single replay is therefore
    determined by the order in which it was minted.
    """

    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> UUID:
        self._counter += 1
        return UUID(int=self._counter)

    def reset(self) -> None:
        self._counter = 0


# ---------------------------------------------------------------------------
# Hashing the canonical row sequence
# ---------------------------------------------------------------------------


def _canonical_row_summary(rows: list[dict[str, Any]]) -> str:
    """Build a canonical-JSON string summarizing the ledger rows.

    We hash a stable subset of fields per row:

    * ``seq``       — order
    * ``kind``      — ``propose``/``execute``/``verify``/``resolve``
    * ``payload``   — the entry payload (the actual write contents)
    * ``prev_hash`` — chain integrity
    * ``hash``      — entry integrity

    These fields are derived from the input JSONL deterministically
    (modulo the seeded UUIDs + frozen clock). ``entry_id`` and
    ``company_id`` are intentionally excluded — they're cosmetic
    handles, not chain semantics.
    """
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
    return json.dumps(summary, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Replay harness
# ---------------------------------------------------------------------------


class _FrozenDatetime:
    """Drop-in for the imported ``datetime`` name in ledger_api.

    Only ``now()`` is exercised by the InMemoryLedger write path; we
    return a frozen instant. All other attributes proxy through to the
    real ``datetime.datetime`` so any incidental call still works.
    """

    _frozen = datetime(2026, 1, 1, 0, 0, 0)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        if tz is None:
            return cls._frozen
        return cls._frozen.replace(tzinfo=tz)

    def __new__(cls, *args: Any, **kwargs: Any) -> datetime:  # type: ignore[misc]
        return datetime(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(datetime, name)


async def _replay_one_to_hash(jsonl_path: Path) -> str:
    """Replay a JSONL fixture against a fresh InMemoryLedger and hash the result.

    Seeds determinism via:
    1. UUID factory replacing :func:`uuid.uuid4` in both the
       wire_replay module and the ledger_api module.
    2. Fixed company_id (UUID(int=0xC0FFEE)).
    3. ``datetime.now`` in the in-memory ledger frozen to a fixed
       instant, so every row's ``ts`` is the same and the chain hash
       stays deterministic.
    """
    factory = _DeterministicUUIDFactory()
    company_id = UUID(int=0xC0FFEE)

    ledger = InMemoryLedger()
    replayer = WireReplayer(
        ledger=ledger, company_id=company_id, jsonl_path=jsonl_path,
    )

    with patch(
        "wormbase_channel_adapter.wire_replay.uuid4", new=factory
    ), patch(
        "wormbase_ledger.ledger_api.uuid4", new=factory
    ), patch(
        "wormbase_ledger.ledger_api.datetime", new=_FrozenDatetime
    ):
        await replayer.run()

    rows = await ledger.fetch(company_id)
    return _sha256_hex(_canonical_row_summary(rows))


# ---------------------------------------------------------------------------
# Fixture discovery + expected-hash management
# ---------------------------------------------------------------------------


def _all_jsonl_fixtures() -> list[Path]:
    """Return every ``*.jsonl`` fixture in the sim-harness fixtures dir."""
    return sorted(FIXTURES_DIR.glob("*.jsonl"))


def _expected_hash_path(jsonl_path: Path) -> Path:
    return jsonl_path.with_suffix(jsonl_path.suffix + ".expected_hash")


def _fixture_ids() -> list[str]:
    return [p.name for p in _all_jsonl_fixtures()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "jsonl_path", _all_jsonl_fixtures(), ids=_fixture_ids()
)
def test_wire_replay_hash_matches_checked_in_expected(jsonl_path: Path) -> None:
    """Invariant: wire-replay produces a byte-identical ledger across runs.

    For every recorded JSONL fixture, the canonicalized + hashed ledger
    row sequence equals the checked-in ``.expected_hash`` file. If they
    diverge, the wire-replay code path is no longer deterministic — a
    production-determinism regression that breaks the demo backstop.

    First-run hash regeneration is gated:
        WORMBASE_REGEN_WIRE_REPLAY_HASHES=1 pytest tests/contract/test_wire_replay_byte_identical.py

    CI must NEVER run with that flag set; the env var is a developer-
    affordance only.
    """
    actual = asyncio.run(_replay_one_to_hash(jsonl_path))

    expected_path = _expected_hash_path(jsonl_path)
    if (
        os.environ.get("WORMBASE_REGEN_WIRE_REPLAY_HASHES") == "1"
        or not expected_path.exists()
    ):
        expected_path.write_text(actual + "\n")
        # Read it back to assert we wrote what we computed (paranoid).
        recorded = expected_path.read_text().strip()
        assert recorded == actual, (
            "regen mismatch: wrote one hash, read another"
        )
        return

    expected = expected_path.read_text().strip()
    assert actual == expected, (
        f"wire-replay byte-identical FAILED for {jsonl_path.name}:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        f"if the divergence is intentional, run:\n"
        f"  WORMBASE_REGEN_WIRE_REPLAY_HASHES=1 pytest "
        f"tests/contract/test_wire_replay_byte_identical.py"
    )


def test_at_least_three_jsonl_fixtures_available() -> None:
    """Invariant: per W6.A4 acceptance, ≥3 JSONL fixtures exist for replay.

    Drift gate: if a fixture is deleted or moved, this test fails so
    the conformance suite never silently shrinks.
    """
    fixtures = _all_jsonl_fixtures()
    assert len(fixtures) >= 3, (
        f"expected ≥3 JSONL fixtures in {FIXTURES_DIR}, found {len(fixtures)}: "
        f"{[p.name for p in fixtures]}"
    )


def test_every_fixture_has_an_expected_hash_file() -> None:
    """Invariant: every JSONL fixture carries a checked-in expected hash.

    Drift gate: a fixture without a hash file is an unprotected wire
    seam — the conformance suite would silently auto-generate the hash
    on first run without flagging it. This test forces the hash file
    to be tracked alongside the fixture.
    """
    fixtures = _all_jsonl_fixtures()
    missing = [
        p.name for p in fixtures if not _expected_hash_path(p).exists()
    ]
    assert not missing, (
        f"missing .expected_hash files for: {missing} "
        f"(run WORMBASE_REGEN_WIRE_REPLAY_HASHES=1 pytest to generate)"
    )
