"""Tests for ``TenantQuotaConsumedPayload`` — final wave item #7 (2026-05-13).

Pins the new ledger entry kind that backs the opt-in ``LedgerQuotaTracker``
emission cadence:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* ``triggered_by`` is a closed Literal — count_threshold / time_threshold
  / quota_exhausted only.
* ``window_*_ts`` must be tz-aware (defensive — the same invariant the
  envelope enforces on ``LedgerEntry.ts``).
* All numeric fields enforce non-negative bounds; ``quota_limit`` >= 1.

KIND_REGISTRY grew 104 → 105 (additive per schema-evolution doctrine
Rule 2; under the 120-kind Wave F Addendum 1 ceiling). 7th case of
Optional-Effect Injection doctrine §6.4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    TenantQuotaConsumedPayload,
)


def test_tenant_quota_consumed_kind_registered() -> None:
    """Auto-registration via EntryPayload.__init_subclass__ — the kind
    appears in ``KIND_REGISTRY`` and maps back to the payload class."""
    assert "tenant_quota_consumed" in KIND_REGISTRY
    assert KIND_REGISTRY["tenant_quota_consumed"] is TenantQuotaConsumedPayload


def test_tenant_quota_consumed_roundtrip_count_threshold() -> None:
    """Periodic count-threshold emission round-trips byte-equivalently."""
    now = datetime.now(timezone.utc)
    p = TenantQuotaConsumedPayload(
        tenant_slug="acme",
        consumption_count=100,
        quota_limit=100_000,
        quota_remaining=99_900,
        window_start_ts=now - timedelta(minutes=2),
        window_end_ts=now,
        triggered_by="count_threshold",
    )
    assert TenantQuotaConsumedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "tenant_quota_consumed"


def test_tenant_quota_consumed_roundtrip_time_threshold() -> None:
    """Periodic time-threshold emission round-trips byte-equivalently."""
    now = datetime.now(timezone.utc)
    p = TenantQuotaConsumedPayload(
        tenant_slug="beta",
        consumption_count=7,
        quota_limit=100_000,
        quota_remaining=99_993,
        window_start_ts=now - timedelta(minutes=5),
        window_end_ts=now,
        triggered_by="time_threshold",
    )
    assert TenantQuotaConsumedPayload.model_validate(p.model_dump()) == p


def test_tenant_quota_consumed_quota_exhausted_immediate_emission() -> None:
    """The deny-moment emission carries ``triggered_by="quota_exhausted"``
    and ``quota_remaining=0`` — captured immediately, not amortized."""
    now = datetime.now(timezone.utc)
    p = TenantQuotaConsumedPayload(
        tenant_slug="overflow",
        consumption_count=3,
        quota_limit=100,
        quota_remaining=0,
        window_start_ts=now - timedelta(seconds=12),
        window_end_ts=now,
        triggered_by="quota_exhausted",
    )
    assert p.triggered_by == "quota_exhausted"
    assert p.quota_remaining == 0
    assert TenantQuotaConsumedPayload.model_validate(p.model_dump()) == p


def test_tenant_quota_consumed_rejects_invalid_triggered_by() -> None:
    """``triggered_by`` is a closed Literal; arbitrary strings rejected."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantQuotaConsumedPayload(
            tenant_slug="acme",
            consumption_count=1,
            quota_limit=100,
            quota_remaining=99,
            window_start_ts=now - timedelta(seconds=1),
            window_end_ts=now,
            triggered_by="not_a_real_trigger",  # type: ignore[arg-type]
        )


def test_tenant_quota_consumed_rejects_naive_ts() -> None:
    """``window_*_ts`` must be tz-aware — same invariant as ``LedgerEntry.ts``."""
    naive_now = datetime.utcnow()  # naive — no tzinfo
    aware_now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantQuotaConsumedPayload(
            tenant_slug="acme",
            consumption_count=1,
            quota_limit=100,
            quota_remaining=99,
            window_start_ts=naive_now,
            window_end_ts=aware_now,
            triggered_by="count_threshold",
        )


def test_tenant_quota_consumed_requires_positive_quota_limit() -> None:
    """``quota_limit`` must be at least 1 — a zero limit would be
    nonsensical (no requests would ever pass)."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantQuotaConsumedPayload(
            tenant_slug="acme",
            consumption_count=0,
            quota_limit=0,  # invalid
            quota_remaining=0,
            window_start_ts=now,
            window_end_ts=now,
            triggered_by="count_threshold",
        )


def test_tenant_quota_consumed_requires_nonempty_slug() -> None:
    """Empty tenant_slug rejected — every emission must be attributable."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantQuotaConsumedPayload(
            tenant_slug="",
            consumption_count=1,
            quota_limit=100,
            quota_remaining=99,
            window_start_ts=now,
            window_end_ts=now,
            triggered_by="count_threshold",
        )
