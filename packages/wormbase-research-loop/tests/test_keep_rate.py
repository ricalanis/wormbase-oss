"""Tests for keep_rate_publisher (Demo-day P1).

Asserts:
  * publish_for_day writes one metrics_keep_rate_published entry per scope.
  * Re-running for the same day is a no-op (idempotent).
  * Replay-deterministic: same ledger row stream → same payloads.
  * Person/Team/Company audiences bucket correctly.
  * Synthetic-baseline tag fires when the day's resolution count is too low.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from wormbase_core.projections.keep_rate import keep_rate_for_window
from wormbase_ledger import InMemoryLedger
from wormbase_research_loop.keep_rate import publish_for_day


COMPANY = UUID("00000000-0000-0000-0000-000000000001")
PERSON_A = "00000000-0000-0000-0000-0000000000aa"
DOMAIN_X = "00000000-0000-0000-0000-0000000000bb"
DAY = date(2026, 4, 27)
DAY_TS = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)


async def _seed_resolution(
    ledger: InMemoryLedger,
    *,
    experiment_id: str,
    audience: str,
    outcome: str,
    ts: datetime,
) -> None:
    """Write a propose+resolve pair so the publisher sees a complete cycle."""
    await ledger.write(
        company_id=COMPANY,
        propose={
            "target_kind": "experiment_proposed",
            "ref_id": experiment_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_proposed",
            "args": {
                "experiment_id": experiment_id,
                "audience": audience,
                "headline_metric": "metric",
                "for_person_id": PERSON_A,
                "position": "cfo",
                "proposed_change": {},
                "expected_delta": -0.1,
                "proposed_at": ts.isoformat(),
            },
            "result_ref": experiment_id,
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed propose"},
        timestamp=ts,
    )
    await ledger.write(
        company_id=COMPANY,
        propose={
            "target_kind": "experiment_resolved",
            "ref_id": experiment_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_resolved",
            "args": {
                "experiment_id": experiment_id,
                "outcome": outcome,
                "observed_delta": -0.05,
                "rationale": "seed",
                "resolved_at": ts.isoformat(),
            },
            "result_ref": experiment_id,
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed resolve"},
        timestamp=ts,
    )


@pytest.mark.asyncio
async def test_publish_for_day_emits_one_entry_per_scope() -> None:
    ledger = InMemoryLedger()
    await _seed_resolution(
        ledger, experiment_id="e1", audience=f"person:{PERSON_A}",
        outcome="keep", ts=DAY_TS,
    )
    await _seed_resolution(
        ledger, experiment_id="e2", audience=f"team:{DOMAIN_X}",
        outcome="discard", ts=DAY_TS,
    )
    await _seed_resolution(
        ledger, experiment_id="e3", audience="company",
        outcome="keep", ts=DAY_TS,
    )

    published = await publish_for_day(ledger, COMPANY, day=DAY)
    assert len(published) == 3
    by_scope = {p.scope: p for p in published}
    assert by_scope["person"].kept == 1
    assert by_scope["person"].total == 1
    assert by_scope["person"].ratio == 1.0
    assert by_scope["team"].kept == 0
    assert by_scope["team"].total == 1
    assert by_scope["team"].ratio == 0.0
    assert by_scope["company"].kept == 1
    assert by_scope["company"].total == 1


@pytest.mark.asyncio
async def test_publish_for_day_is_idempotent() -> None:
    ledger = InMemoryLedger()
    await _seed_resolution(
        ledger, experiment_id="e1", audience="company",
        outcome="keep", ts=DAY_TS,
    )
    first = await publish_for_day(ledger, COMPANY, day=DAY)
    second = await publish_for_day(ledger, COMPANY, day=DAY)
    assert len(first) == 3  # one per scope
    assert second == [], "second publish must be a no-op"


@pytest.mark.asyncio
async def test_publish_for_day_carries_published_by_attribution() -> None:
    ledger = InMemoryLedger()
    await _seed_resolution(
        ledger, experiment_id="e1", audience="company",
        outcome="keep", ts=DAY_TS,
    )
    published = await publish_for_day(
        ledger, COMPANY, day=DAY, published_by="worm",
    )
    for p in published:
        assert p.published_by == "worm"
        assert p.published_at is not None
        assert p.published_at.tzinfo is not None  # tz-aware required


@pytest.mark.asyncio
async def test_keep_rate_window_replay_deterministic() -> None:
    """Same ledger row stream → same KeepRateRow tuple per (scope, day)."""
    ledger = InMemoryLedger()
    await _seed_resolution(
        ledger, experiment_id="e1", audience="company",
        outcome="keep", ts=DAY_TS,
    )
    await _seed_resolution(
        ledger, experiment_id="e2", audience="company",
        outcome="keep", ts=DAY_TS + timedelta(hours=1),
    )
    rows = await ledger.fetch(COMPANY)
    a = keep_rate_for_window(rows, day=DAY)
    b = keep_rate_for_window(list(rows), day=DAY)
    assert a == b


@pytest.mark.asyncio
async def test_keep_rate_synthetic_baseline_when_low_sample() -> None:
    ledger = InMemoryLedger()
    # Single resolution: total=1 < threshold (3) → synthetic=True
    await _seed_resolution(
        ledger, experiment_id="e1", audience="company",
        outcome="keep", ts=DAY_TS,
    )
    rows = await ledger.fetch(COMPANY)
    keep_rows = keep_rate_for_window(rows, day=DAY)
    by_scope = {r.scope: r for r in keep_rows}
    assert by_scope["company"].synthetic is True
    assert by_scope["person"].synthetic is True  # zero data → synthetic


@pytest.mark.asyncio
async def test_pre_w5a4_audience_less_rows_count_as_person() -> None:
    """Pre-W5.A4 entries without audience field default to person scope."""
    ledger = InMemoryLedger()
    # Manually craft a propose without audience field. Since the seeder
    # always sets audience, we drop in via direct execute_fn surgery.
    eid = "legacy-1"

    async def _seed_legacy() -> None:
        await ledger.write(
            company_id=COMPANY,
            propose={
                "target_kind": "experiment_proposed",
                "ref_id": eid,
                "reason": "legacy",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_experiment_proposed",
                "args": {
                    "experiment_id": eid,
                    # no audience — pre-W5.A4 row
                    "headline_metric": "metric",
                    "for_person_id": PERSON_A,
                    "position": "cfo",
                    "proposed_change": {},
                    "expected_delta": -0.1,
                    "proposed_at": DAY_TS.isoformat(),
                },
                "result_ref": eid,
            },
            verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
            timestamp=DAY_TS,
        )
        await ledger.write(
            company_id=COMPANY,
            propose={
                "target_kind": "experiment_resolved",
                "ref_id": eid,
                "reason": "legacy",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_experiment_resolved",
                "args": {
                    "experiment_id": eid,
                    "outcome": "keep",
                    "observed_delta": -0.05,
                    "rationale": "legacy",
                    "resolved_at": DAY_TS.isoformat(),
                },
                "result_ref": eid,
            },
            verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
            timestamp=DAY_TS,
        )

    await _seed_legacy()
    rows = await ledger.fetch(COMPANY)
    keep_rows = keep_rate_for_window(rows, day=DAY)
    by_scope = {r.scope: r for r in keep_rows}
    assert by_scope["person"].kept == 1
    assert by_scope["person"].total == 1
