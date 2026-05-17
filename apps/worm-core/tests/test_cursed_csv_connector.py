"""Connector-level coverage for ``fixtures/cursed_finance_export.csv`` (P4).

The cursed CSV is the demo's worst-case-realistic finance export — see
``scripts/generate_cursed_csv.py`` for the full curse list. This module
asserts the ``csv_local`` connector survives every curse without crashing
and surfaces the right metadata for downstream silver normalization +
classification.

Each test names the curse it pins. If the connector regresses on any of
these (e.g. someone "fixes" the dedup at bronze), the offending curse
becomes findable from the test name alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_connectors.csv_local import CsvLocalConnector, detect_encoding
from wormbase_connectors.types import SecretBundle


# Resolve the fixture path once. The repo-root fixtures dir is the
# canonical location; the connector reads bytes from disk so the path
# must be real, not synthesized.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _REPO_ROOT / "fixtures" / "cursed_finance_export.csv"


def test_cursed_csv_fixture_exists() -> None:
    """The fixture must be checked into the repo at the canonical path.

    Sanity check before all the per-curse assertions below — if the
    fixture went missing, every other test would fail with a file-not-
    found error and the curse-specific signal would be lost.
    """
    assert _FIXTURE_PATH.exists(), (
        f"cursed CSV missing at {_FIXTURE_PATH}; "
        f"run `python scripts/generate_cursed_csv.py` to regenerate."
    )
    assert _FIXTURE_PATH.stat().st_size > 0


def test_detect_encoding_picks_cp1252_for_cursed_csv() -> None:
    """Curse: encoding is Windows-1252, not UTF-8.

    ``detect_encoding`` must fall back to cp1252 after UTF-8 fails.
    The pure detector libraries are unstable across cp1252/cp1257 for
    short Latin-1 sequences; the connector commits to cp1252 because
    it is the dominant Western-Excel-export encoding.
    """
    raw = _FIXTURE_PATH.read_bytes()
    # UTF-8 must fail on this file (the headline curse).
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    # cp1252 must succeed.
    raw.decode("cp1252")
    # And the connector's deterministic rule must report cp1252.
    assert detect_encoding(raw) == "cp1252"


@pytest.mark.asyncio
async def test_csv_local_profiles_cursed_file_without_crashing() -> None:
    """Curse-blanket assertion: the file profiles end-to-end.

    Cursed bytes used to crash strict CSV readers at ``José Álvarez``
    (byte 0xe9 in cp1252). The connector must complete a profile call
    and return a populated :class:`Profile`.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    assert profile.row_count is not None and profile.row_count > 0
    assert profile.column_count is not None and profile.column_count > 0
    assert profile.columns, "profile must surface columns"


@pytest.mark.asyncio
async def test_cursed_csv_profile_reports_windows_1252_encoding() -> None:
    """Curse: profile.extra['encoding'] == 'cp1252'.

    Downstream silver needs the original encoding so re-emit /
    re-export round-trips bytes correctly.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    assert profile.extra.get("encoding") == "cp1252", (
        f"expected cp1252; got {profile.extra.get('encoding')!r}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_surfaces_duplicate_header_rows() -> None:
    """Curse: two header rows. Bronze surfaces the count; silver dedups.

    The connector reports the number of contiguous duplicate header rows
    on ``profile.extra['duplicate_header_rows']``. A clean file would
    return 0; the cursed export returns ≥1.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    duplicate_count = profile.extra.get("duplicate_header_rows", 0)
    assert duplicate_count >= 1, (
        "expected ≥1 duplicate header row; cursed CSV ships with 1 "
        "(2 total header rows including the canonical one)"
    )


@pytest.mark.asyncio
async def test_cursed_csv_includes_q3_revenue_column_with_literal_label() -> None:
    """Curse: Seed-S1 chatter references the literal column name.

    The phenomenon-gap detector matches on this exact string, so any
    well-meaning rename ("normalize whitespace") would silently break
    Beat 6. Pin the label here.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    column_names = [c["name"] for c in profile.columns]
    assert "Q3 Rev (final)(USE THIS)" in column_names, (
        f"missing canonical Seed-S1 label; got columns {column_names}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_flags_minus_9999_sentinel() -> None:
    """Curse: ``-9999`` is the missing-value sentinel for ``customer_count``.

    The connector flags any column carrying ``-9999`` as an anomaly
    on ``profile.extra['anomalies']`` so silver can replace it with
    null before downstream stats. Without this flag, a naive mean()
    over ``customer_count`` would skew dramatically negative.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    anomalies = profile.extra.get("anomalies", [])
    sentinel_anomalies = [
        a for a in anomalies if a.get("kind") == "sentinel_value"
    ]
    assert any(
        a.get("column") == "customer_count" and a.get("sentinel") == "-9999"
        for a in sentinel_anomalies
    ), (
        f"expected -9999 sentinel flag on customer_count; got {anomalies!r}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_flags_excel_error_strings() -> None:
    """Curse: ``#REF!`` and ``#N/A`` appear in numeric columns.

    The connector emits an ``excel_error_strings`` anomaly per column
    so silver can null-out the bad cells without dropping the whole
    column to ``str`` dtype.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    anomalies = profile.extra.get("anomalies", [])
    excel_anomalies = [
        a for a in anomalies if a.get("kind") == "excel_error_strings"
    ]
    assert excel_anomalies, (
        f"expected at least one excel_error_strings anomaly; got {anomalies!r}"
    )
    # At least one of the offending columns must be a revenue-like one.
    columns_with_errors = {a.get("column") for a in excel_anomalies}
    assert columns_with_errors & {
        "Q3 Rev (final)(USE THIS)",
        "net_revenue",
    }, (
        f"expected error tokens in a revenue column; got {columns_with_errors!r}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_classifies_pii_column_by_name() -> None:
    """Curse: ``customer_email`` is PII by column-name heuristic.

    Independent of the filename rule (``cursed_finance_export.csv`` is
    not flagged by filename), the column-name heuristic must surface
    the email column as PII so the policy gate defaults the source to
    confidential-PII before any human confirms.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    hints = profile.extra.get("classification_hints", [])
    email_hints = [
        h for h in hints
        if h.get("column") == "customer_email" and h.get("hint") == "pii"
    ]
    assert email_hints, (
        f"expected PII hint for customer_email column; got {hints!r}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_has_at_least_200_data_rows() -> None:
    """Spec contract: ≥200 data rows so silver has KPI-proposal mass.

    Below 200, gold's KPI proposer can't reach a stable signal — the
    install-arc Beat 3 KPI fires from this file, and it fires from
    silver row count.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    assert profile.row_count is not None and profile.row_count >= 200, (
        f"cursed CSV must carry ≥200 data rows; profile reports "
        f"{profile.row_count}"
    )


@pytest.mark.asyncio
async def test_cursed_csv_carries_both_naive_and_tz_aware_datetime_columns() -> None:
    """Curse: ``recorded_at`` (tz-naïve) adjacent to ``recorded_at_utc`` (Z).

    Silver must learn to pick one; bronze surfaces both so the choice is
    explicit. We just assert the columns coexist here — silver's choice
    is asserted in the integration test.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    profile = await connector.profile(handle, str(_FIXTURE_PATH))
    column_names = [c["name"] for c in profile.columns]
    assert "recorded_at" in column_names
    assert "recorded_at_utc" in column_names


@pytest.mark.asyncio
async def test_cursed_csv_profile_is_idempotent() -> None:
    """Conformance: two profile calls return identical schema_hash.

    The cursed file must not break the W6.A4 conformance harness's
    idempotency invariant.
    """
    connector = CsvLocalConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"path": str(_FIXTURE_PATH)})
    )
    first = await connector.profile(handle, str(_FIXTURE_PATH))
    second = await connector.profile(handle, str(_FIXTURE_PATH))
    assert first.schema_hash == second.schema_hash
    assert first.columns == second.columns
    assert first.column_count == second.column_count


def test_detect_encoding_prefers_utf8_when_possible() -> None:
    """Regression guard: cp1252 fallback only fires after UTF-8 fails.

    A clean UTF-8 file must be reported as utf-8, not silently
    downgraded.
    """
    text = "row_id,customer_name\n1,Sofía Martínez\n"
    raw = text.encode("utf-8")
    assert detect_encoding(raw) == "utf-8"


def test_detect_encoding_returns_latin1_for_unknown_bytes() -> None:
    """Latin-1 is the safety belt — every byte is a valid latin-1 codepoint.

    The connector must not raise on adversarial input. The ordered
    candidate list ends in latin-1; the function returns it.
    """
    # 0xfe is invalid utf-8 mid-stream; cp1252 maps 0x81/0x8d/0x8f/0x90/0x9d as undefined.
    raw = b"\x81\x8d\x8f\x90\x9d"
    enc = detect_encoding(raw)
    assert enc in ("cp1252", "latin-1"), (
        f"expected cp1252 or latin-1 fallback; got {enc!r}"
    )


# ---------------------------------------------------------------------------
# Default-cascade wiring tests
# ---------------------------------------------------------------------------


def test_default_local_source_resolves_to_cursed_csv() -> None:
    """The onboarding helper resolves to the canonical fixture path.

    Pins the ``apps/worm-core → fixtures/`` resolution rule. If the
    repo layout shifts (an unlikely but possible refactor), this test
    catches it before the install flow blows up at provisioning time.
    """
    from wormbase_core.onboarding import (
        CURSED_CSV_FIXTURE_FILENAME,
        cursed_csv_path,
    )

    resolved = cursed_csv_path()
    assert resolved.name == CURSED_CSV_FIXTURE_FILENAME
    assert resolved.is_file()


def test_default_local_source_silver_normalizes_cursed_bytes() -> None:
    """``cursed_csv_silver_bytes`` produces utf-8, dedups headers, nulls errors.

    Sanity-checking the silver primitive that ``run_default_local_cascade``
    relies on. We assert (a) output decodes cleanly as utf-8, (b) the
    duplicate header row is gone, (c) no Excel error tokens survive.
    """
    from wormbase_core.onboarding import cursed_csv_silver_bytes

    silver = cursed_csv_silver_bytes()
    text = silver.decode("utf-8")  # round-trips as utf-8
    lines = text.splitlines()
    # First two lines no longer identical (silver dedup removed the dupe).
    assert lines[0] != lines[1]
    # No surviving Excel-error tokens.
    for token in ("#REF!", "#N/A", "#VALUE!", "#DIV/0!"):
        assert token not in text, (
            f"silver layer should null Excel-error token {token!r}"
        )


@pytest.mark.asyncio
async def test_run_default_local_cascade_writes_medallion_entries() -> None:
    """Onboarding cascade writes bronze + silver + gold + KPI ledger entries.

    The install flow calls ``run_default_local_cascade`` to materialize
    the cursed CSV into ledger truth. We exercise it on an in-memory
    ledger and assert the four canonical execute tools all fire.
    """
    from uuid import UUID

    from wormbase_core.onboarding import run_default_local_cascade
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    company_id = UUID("00000000-0000-0000-0000-000000000099")
    summary = await run_default_local_cascade(ledger, company_id)
    assert "source_id" in summary
    assert "fixture_path" in summary

    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_source_bronzed" in tools
    assert "emit_source_silvered" in tools
    assert "emit_source_golded" in tools
    assert "emit_kpi_proposed" in tools, (
        f"expected emit_kpi_proposed in tools; got {tools}"
    )
