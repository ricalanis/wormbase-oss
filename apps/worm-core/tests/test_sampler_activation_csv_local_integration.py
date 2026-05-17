"""Sampler activation Wave — Phase 4 end-to-end integration test.

Drives the full bridge: tmp CSV file → csv_local connector → real ledger
write of source_proposed + source_connected → LedgerSourceHandleProvider
lookup → ConnectorSampler.sample_column → assert returned set of
distinct email values matches what's in the file.

This proves the bridge wires together end-to-end against the real
csv_local connector + real ledger (InMemoryLedger; same hash semantics
as the DB-backed Ledger). No mocks for the connector, the provider, or
the parser.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    SourceConnectedPayload,
    SourceProposedPayload,
)

from wormbase_core.connector_sampler import ConnectorSampler
from wormbase_core.source_handle_provider import LedgerSourceHandleProvider


_TENANT = UUID("00000000-0000-0000-0000-0000beef0001")


@pytest.mark.asyncio
async def test_csv_local_end_to_end_roundtrip(tmp_path: Path) -> None:
    """csv_local connector + ledger handle provider + ConnectorSampler roundtrip.

    The end-to-end shape we're pinning:

      1. Write a 50-row CSV with ``email,name,signup_date`` columns to
         disk.
      2. Emit ``source_proposed`` + ``source_connected`` for the file
         under tenant ``_TENANT``.
      3. Construct ``ConnectorSampler`` with the production
         ``LedgerSourceHandleProvider``.
      4. Call ``sample_column(table_id=<csv_path>, column="email",
         n=10)`` — assert the returned set contains 10 distinct emails
         drawn from the file.
    """
    # ------------------------------------------------------------------
    # Phase 1 — seed the file
    # ------------------------------------------------------------------
    csv_path = tmp_path / "users.csv"
    rows = ["email,name,signup_date"]
    for i in range(50):
        rows.append(f"user{i:02d}@example.com,User {i:02d},2026-05-{(i % 28) + 1:02d}")
    csv_path.write_text("\n".join(rows) + "\n")

    # ------------------------------------------------------------------
    # Phase 2 — seed the ledger (source_proposed → source_connected)
    # ------------------------------------------------------------------
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000beef0010")
    proposed = SourceProposedPayload(
        source_id=source_id,
        source_kind="csv_local",
        uri=str(csv_path),
        added_via_flow="drop_and_profile",
        suggested_domain="growth",
        suggested_classification="internal",
    )
    await ledger.write(
        company_id=_TENANT,
        propose={
            "target_kind": "source_proposed",
            "ref_id": str(source_id),
            "reason": "integration test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": proposed.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )
    connected = SourceConnectedPayload(
        source_id=source_id,
        connection_ref=str(csv_path),
        connected_at=datetime.now(UTC),
    )
    await ledger.write(
        company_id=_TENANT,
        propose={
            "target_kind": "source_connected",
            "ref_id": str(source_id),
            "reason": "integration test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_connected",
            "args": connected.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )

    # ------------------------------------------------------------------
    # Phase 3 — construct the bridge with PRODUCTION provider + registry
    # ------------------------------------------------------------------
    # NB: must import csv_local connector module so its
    # @register_surface_driver decorator runs.
    from wormbase_lake_surfaces import csv_local  # noqa: F401

    provider = LedgerSourceHandleProvider(ledger=ledger)
    sampler = ConnectorSampler(
        handle_provider=provider,
        company_id=_TENANT,
        # connector_registry=None → default global registry
    )

    # ------------------------------------------------------------------
    # Phase 4 — call sample_column and assert the roundtrip
    # ------------------------------------------------------------------
    # The L3/L5/L8 strategies pass the catalog-mirror's table_id token,
    # which for csv_local IS the same path used as both URI and
    # connection_ref. The handle provider's resource_map maps
    # ``{csv_path: csv_path}`` and the connector returns rows for the
    # resource_id verbatim.
    out = await sampler.sample_column(
        table_id=str(csv_path), column="email", n=10,
    )

    # Must return a set of distinct values.
    assert isinstance(out, set)
    # We requested n=10 and the file has 50 distinct rows; the bridge
    # must respect the cap.
    assert len(out) == 10
    # Each value must be a real email drawn from the file.
    for email in out:
        assert email.endswith("@example.com")
        assert email.startswith("user")


@pytest.mark.asyncio
async def test_csv_local_missing_column_returns_empty(
    tmp_path: Path,
) -> None:
    """When the requested column is not in the CSV header → honest empty.

    Pins the per-source honest-stub posture: missing column → no
    exception, no crash; just an empty set the strategy treats as
    "no samples".
    """
    csv_path = tmp_path / "names_only.csv"
    csv_path.write_text("name\nAlice\nBob\n")

    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000beef0020")
    proposed = SourceProposedPayload(
        source_id=source_id,
        source_kind="csv_local",
        uri=str(csv_path),
        added_via_flow="drop_and_profile",
        suggested_domain="growth",
        suggested_classification="internal",
    )
    await ledger.write(
        company_id=_TENANT,
        propose={
            "target_kind": "source_proposed",
            "ref_id": str(source_id),
            "reason": "integration test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": proposed.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )
    connected = SourceConnectedPayload(
        source_id=source_id,
        connection_ref=str(csv_path),
        connected_at=datetime.now(UTC),
    )
    await ledger.write(
        company_id=_TENANT,
        propose={
            "target_kind": "source_connected",
            "ref_id": str(source_id),
            "reason": "integration test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_connected",
            "args": connected.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )

    from wormbase_lake_surfaces import csv_local  # noqa: F401

    sampler = ConnectorSampler(
        handle_provider=LedgerSourceHandleProvider(ledger=ledger),
        company_id=_TENANT,
    )
    out = await sampler.sample_column(
        table_id=str(csv_path), column="absent_column", n=10,
    )
    assert out == set()
