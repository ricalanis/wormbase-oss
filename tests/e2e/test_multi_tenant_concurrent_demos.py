"""W6.A6 — concurrent multi-tenant demo arcs.

Two tenants (``baseworm`` + ``democorp``) run the canonical
install arc concurrently via ``asyncio.gather``. The invariants:

* Zero cross-tenant ledger writes — every entry's company_id must
  match the tenant that produced it. (The SaaS-first deployment
  posture in CLAUDE.md hinges on this; a single bleed-through
  here is a P0 regression.)
* Both arcs complete within 10 minutes wall-clock (single-tenant
  budget is 8m; concurrent budget allows for some asyncio scheduling
  slowdown).
* Hash chains are independent: tenant A's ledger does not reference
  any of tenant B's entry hashes (no shared prev_hash linkage).

The test runs against the in-process ``InMemoryLedger`` and
``WireReplayer`` — same code path as production minus the live
Slack wire. Multi-tenant safety is a write-time invariant, not a
network invariant; in-process fully exercises it.
"""

from __future__ import annotations

import asyncio
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
TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")

# Single-tenant baseline = 8m; two-tenant concurrent budget allows
# the asyncio scheduler some slack but must still come in under 10m.
TWO_TENANT_BUDGET_S = 600


def _company_id_for(slug: str) -> UUID:
    return uuid5(TENANT_NAMESPACE, slug.strip().lower())


@pytest.fixture
def fixture_path() -> Path:
    if not CANONICAL_FIXTURE.exists():
        pytest.skip(f"canonical fixture missing: {CANONICAL_FIXTURE}")
    return CANONICAL_FIXTURE


async def _run_arc_for(
    ledger: InMemoryLedger, slug: str, fixture: Path
) -> tuple[str, list[dict]]:
    company_id = _company_id_for(slug)
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    await replayer.run()
    rows = await ledger.fetch(company_id)
    return slug, rows


async def test_concurrent_demos_zero_cross_tenant_writes(
    fixture_path: Path,
) -> None:
    """Run two demos concurrently; assert every row carries its own tenant.

    The SHARED ledger is the worst case — it forces the test to detect
    even a single mis-routed entry. (In production each tenant has its
    own SaaS-tenancy partition; this test is paranoid against the case
    where a code path forgets to scope.)
    """
    shared_ledger = InMemoryLedger()
    baseworm_id = _company_id_for("baseworm")
    democorp_id = _company_id_for("democorp")

    started = time.monotonic()
    results = await asyncio.gather(
        _run_arc_for(shared_ledger, "baseworm", fixture_path),
        _run_arc_for(shared_ledger, "democorp", fixture_path),
    )
    elapsed = time.monotonic() - started

    assert elapsed < TWO_TENANT_BUDGET_S, (
        f"two-tenant concurrent run took {elapsed:.1f}s; over the "
        f"{TWO_TENANT_BUDGET_S}s ceiling."
    )

    by_slug = dict(results)
    assert "baseworm" in by_slug and "democorp" in by_slug

    # Every row in baseworm's projection carries baseworm's company_id.
    for row in by_slug["baseworm"]:
        assert row["company_id"] == baseworm_id, (
            f"cross-tenant bleed: baseworm row carries company_id="
            f"{row['company_id']}; expected {baseworm_id}"
        )
    for row in by_slug["democorp"]:
        assert row["company_id"] == democorp_id, (
            f"cross-tenant bleed: democorp row carries company_id="
            f"{row['company_id']}; expected {democorp_id}"
        )


async def test_concurrent_demos_independent_hash_chains(
    fixture_path: Path,
) -> None:
    """Each tenant's hash chain is independent of the other's.

    Specifically, no entry in tenant A references a prev_hash that
    appears in tenant B's chain. The hash chain is the company-scoped
    auditability primitive; sharing prev_hash across tenants would
    break replay-to-timestamp determinism for both.
    """
    shared_ledger = InMemoryLedger()
    baseworm_id = _company_id_for("baseworm")
    democorp_id = _company_id_for("democorp")

    await asyncio.gather(
        _run_arc_for(shared_ledger, "baseworm", fixture_path),
        _run_arc_for(shared_ledger, "democorp", fixture_path),
    )

    rows_a = await shared_ledger.fetch(baseworm_id)
    rows_b = await shared_ledger.fetch(democorp_id)

    a_hashes = {r["hash"] for r in rows_a}
    b_hashes = {r["hash"] for r in rows_b}
    a_prev = {r["prev_hash"] for r in rows_a}
    b_prev = {r["prev_hash"] for r in rows_b}

    # No prev_hash in tenant A points at any tenant-B entry hash.
    bleed_a_to_b = a_prev & b_hashes
    bleed_b_to_a = b_prev & a_hashes
    assert not bleed_a_to_b, (
        f"tenant baseworm has prev_hashes pointing at tenant democorp: "
        f"{bleed_a_to_b}"
    )
    assert not bleed_b_to_a, (
        f"tenant democorp has prev_hashes pointing at tenant baseworm: "
        f"{bleed_b_to_a}"
    )


async def test_concurrent_demos_each_tenant_independently_complete(
    fixture_path: Path,
) -> None:
    """Both tenants land the same entry count, independently.

    Re-running the canonical fixture in isolation produces N entries.
    Two tenants run concurrently must each independently land that
    same N — neither short, neither bleeding into the other.
    """
    # Baseline: one-tenant run of the canonical fixture.
    solo_ledger = InMemoryLedger()
    solo_id = _company_id_for("solo")
    solo_replayer = WireReplayer(
        ledger=solo_ledger,
        company_id=solo_id,
        jsonl_path=fixture_path,
    )
    await solo_replayer.run()
    solo_rows = await solo_ledger.fetch(solo_id)
    expected_count = len(solo_rows)

    # Now two concurrent tenants on a shared ledger.
    shared_ledger = InMemoryLedger()
    baseworm_id = _company_id_for("baseworm")
    democorp_id = _company_id_for("democorp")
    await asyncio.gather(
        _run_arc_for(shared_ledger, "baseworm", fixture_path),
        _run_arc_for(shared_ledger, "democorp", fixture_path),
    )
    rows_a = await shared_ledger.fetch(baseworm_id)
    rows_b = await shared_ledger.fetch(democorp_id)

    assert len(rows_a) == expected_count, (
        f"tenant baseworm landed {len(rows_a)} rows; expected "
        f"{expected_count} (matches solo-tenant baseline)"
    )
    assert len(rows_b) == expected_count, (
        f"tenant democorp landed {len(rows_b)} rows; expected "
        f"{expected_count} (matches solo-tenant baseline)"
    )


async def test_concurrent_demos_seq_numbers_are_per_tenant(
    fixture_path: Path,
) -> None:
    """Sequence numbers reset per tenant; never collide across tenants.

    Per CLAUDE.md the ledger is "company-scoped, hash-chained." That
    implies the seq column is also per-company. Each tenant's seq
    must be a contiguous 1..N range.
    """
    shared_ledger = InMemoryLedger()
    await asyncio.gather(
        _run_arc_for(shared_ledger, "baseworm", fixture_path),
        _run_arc_for(shared_ledger, "democorp", fixture_path),
    )
    rows_a = await shared_ledger.fetch(_company_id_for("baseworm"))
    rows_b = await shared_ledger.fetch(_company_id_for("democorp"))
    seqs_a = [r["seq"] for r in rows_a]
    seqs_b = [r["seq"] for r in rows_b]
    assert seqs_a == list(range(1, len(seqs_a) + 1)), (
        f"baseworm seq is non-contiguous: {seqs_a[:10]}..."
    )
    assert seqs_b == list(range(1, len(seqs_b) + 1)), (
        f"democorp seq is non-contiguous: {seqs_b[:10]}..."
    )
