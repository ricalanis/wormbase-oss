"""Unit tests for ``wormbase_sim_harness.seed_acme``.

Mirrors the structure of :file:`test_seed_loader.py` so the Acme demo
seed has parity coverage with the install-arc seed loader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from wormbase_sim_harness.cli import main as cli_main
from wormbase_sim_harness.seed_acme import (
    ACME_FIXTURE_EPOCH,
    ACME_TENANT_SLUG,
    acme_seed_summary,
    default_acme_fixture_path,
)


# ---------------------------------------------------------------------------
# default_acme_fixture_path
# ---------------------------------------------------------------------------


def test_default_acme_fixture_path_resolves_to_jsonl() -> None:
    """The default fixture lives at tests/fixtures/acme_demo_seed/events.jsonl."""
    path = default_acme_fixture_path()
    assert path.is_file(), f"expected acme fixture at {path}"
    assert path.name == "events.jsonl"
    assert path.parent.name == "acme_demo_seed"


def test_acme_tenant_slug_is_pinned() -> None:
    """The canonical demo tenant slug is acme-saas — pinned for the spec."""
    assert ACME_TENANT_SLUG == "acme-saas"


def test_acme_fixture_epoch_is_may_2026() -> None:
    """The fixture epoch is fixed at 2026-05-01T09:00:00 UTC."""
    assert ACME_FIXTURE_EPOCH.year == 2026
    assert ACME_FIXTURE_EPOCH.month == 5
    assert ACME_FIXTURE_EPOCH.day == 1


# ---------------------------------------------------------------------------
# acme_seed_summary
# ---------------------------------------------------------------------------


def test_acme_seed_summary_counts_events() -> None:
    summary = acme_seed_summary()
    assert summary["tenant_slug"] == ACME_TENANT_SLUG
    assert summary["events_total"] >= 25, (
        "Acme fixture should have at least 25 events to exercise the "
        "5-step product arc"
    )
    # The fixture exercises both chat and file wire tools.
    assert summary["tools_count"].get("channel_adapter.emit_chat_received", 0) > 0
    assert summary["tools_count"].get("channel_adapter.emit_file_received", 0) >= 1
    # Multiple distinct channels and senders.
    assert len(summary["distinct_channels"]) >= 3
    assert len(summary["distinct_senders"]) >= 4
    # Beat coverage spans the 5-step arc (≥ 8 distinct beats).
    assert len(summary["distinct_beats"]) >= 8


def test_acme_seed_summary_raises_when_fixture_missing(tmp_path: Path) -> None:
    bogus = tmp_path / "nope.jsonl"
    with pytest.raises(FileNotFoundError):
        acme_seed_summary(bogus)


def test_acme_seed_summary_returns_canonical_persona_uuids() -> None:
    """Every sender_person matches the canonical (Bob/Maya/Alice/Dave) UUIDs.

    The Acme fixture re-uses the install-arc canonical UUIDs for Bob
    (1...), Maya (2...), Alice (3...) and adds Dave (4...) — matching
    the persona registry. A drift here breaks the dashboard's people
    join.
    """
    expected = {
        "11111111-1111-1111-1111-111111111111",  # Bob
        "22222222-2222-2222-2222-222222222222",  # Maya
        "33333333-3333-3333-3333-333333333333",  # Alice
        "44444444-4444-4444-4444-444444444444",  # Dave
    }
    summary = acme_seed_summary()
    assert set(summary["distinct_senders"]) <= expected, (
        f"non-canonical senders detected: "
        f"{set(summary['distinct_senders']) - expected}"
    )


# ---------------------------------------------------------------------------
# CLI: dry-run path is offline-friendly (no ledger touch)
# ---------------------------------------------------------------------------


def test_acme_demo_cli_dry_run_emits_summary() -> None:
    """``wormbase demo acme-demo --dry-run`` prints the fixture summary
    without touching the ledger. Safe to invoke in offline / CI."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["demo", "acme-demo", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tenant_slug"] == ACME_TENANT_SLUG
    assert payload["events_total"] >= 25


def test_acme_demo_cli_dry_run_accepts_fixture_path_override(
    tmp_path: Path,
) -> None:
    """The ``--fixture-path`` flag points the dry-run at any JSONL."""
    p = tmp_path / "tiny.jsonl"
    p.write_text(
        json.dumps({
            "seq": 1,
            "ts": "2026-05-01T09:00:00+00:00",
            "tool": "channel_adapter.emit_chat_received",
            "args": {"channel_id": "C0", "text": "hi"},
        }) + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        ["demo", "acme-demo", "--dry-run", "--fixture-path", str(p)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["events_total"] == 1
    assert payload["fixture_path"] == str(p)
