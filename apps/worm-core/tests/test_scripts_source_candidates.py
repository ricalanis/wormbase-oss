"""Tests for wormbase_core.scripts.source_candidates — wormbase-source-candidates CLI.

Test cases
----------
1.  list empty ledger             → "0 pending, 0 promoted, 0 rejected"
2.  list with 3 candidates        → correct grouping + status column
3.  list --status pending         → filters correctly
4.  list --strategy channel_mention → filters correctly
5.  list --json                   → emits parseable JSONL
6.  promote happy path -y         → writes promoted entry + seq reported
7.  promote already-promoted      → clear error, no double-write
8.  promote unknown candidate_id  → clear error, exit 1
9.  reject happy path -y --reason duplicate → writes rejected entry
10. reject --reason nonsense      → validates against Literal, exit 1 with reasons list
11. Tenant→uuid mapping           → same helper as ledger_recent.py
12. Missing DSN AND no ledger     → clear error, exit 1
"""
from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_core.scripts.source_candidates import (
    WORMBASE_TENANT_NAMESPACE,
    _fold_candidates,
    _summary_line,
    _tenant_to_company_uuid,
    _valid_reject_reasons,
    main,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALTIS_SLUG = "altis"
ALTIS_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), ALTIS_SLUG)

# Stable candidate IDs for tests (32-char hex-ish strings, like make_candidate_id output).
_CAND_NOTION = "aa11bb22cc33dd44ee55ff66aa11bb22"
_CAND_STRIPE = "bb22cc33dd44ee55ff66aa11bb22cc33"
_CAND_POSTGRES = "cc33dd44ee55ff66aa11bb22cc33dd44"


# ---------------------------------------------------------------------------
# Helpers: seed ledger rows directly via InMemoryLedger.write
# ---------------------------------------------------------------------------

async def _seed_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    candidate_id: str,
    proposed_kind: str = "notion",
    proposed_identifier: str = "notion-altis",
    strategy: str = "channel_mention",
    confidence: float = 0.75,
    reasoning: str = "Notion mentioned in chat",
    evidence: dict | None = None,
) -> None:
    """Write a source_candidate_proposed PEVR cycle into the InMemoryLedger."""
    if evidence is None:
        evidence = {
            "message_refs": ["msg-001"],
            "matched_text_excerpt": "Poncho dijo que usaremos Notion para todo",
        }
    args = {
        "candidate_id": candidate_id,
        "proposed_kind": proposed_kind,
        "proposed_identifier": proposed_identifier,
        "strategy": strategy,
        "confidence": confidence,
        "reasoning": reasoning,
        "evidence": evidence,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_proposed",
            "ref_id": candidate_id,
            "reason": "L1 strategy proposed source candidate",
            "proposed_by": "agent-l1-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_proposed",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=lambda _: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _: {"outcome": "keep", "rationale": "proposed"},
    )


async def _seed_promoted(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    candidate_id: str,
    promoted_by: str = "operator-cli",
) -> None:
    """Write a source_candidate_promoted PEVR cycle into the InMemoryLedger."""
    args = {
        "candidate_id": candidate_id,
        "promoted_by_person_id": promoted_by,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_promoted",
            "ref_id": candidate_id,
            "reason": "admin promoted",
            "proposed_by": promoted_by,
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_promoted",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=lambda _: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _: {"outcome": "keep", "rationale": "promoted"},
    )


async def _seed_rejected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    candidate_id: str,
    reason: str = "duplicate",
    rejected_by: str = "operator-cli",
) -> None:
    """Write a source_candidate_rejected PEVR cycle into the InMemoryLedger."""
    args = {
        "candidate_id": candidate_id,
        "rejected_by_person_id": rejected_by,
        "reason": reason,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_rejected",
            "ref_id": candidate_id,
            "reason": "admin rejected",
            "proposed_by": rejected_by,
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_rejected",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=lambda _: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _: {"outcome": "keep", "rationale": "rejected"},
    )


# ---------------------------------------------------------------------------
# Test 1: list — empty ledger
# ---------------------------------------------------------------------------


def test_list_empty_ledger(capsys) -> None:
    """Empty ledger → 0 pending, 0 promoted, 0 rejected."""
    ledger = InMemoryLedger()

    main(
        argv=["list", "--tenant", ALTIS_SLUG, "--status", "all", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "0 pending, 0 promoted, 0 rejected" in out


# ---------------------------------------------------------------------------
# Test 2: list — 3 candidates in different states
# ---------------------------------------------------------------------------


def test_list_three_candidates_status_grouping(capsys) -> None:
    """3 candidates with distinct states → correct grouping + status column."""
    ledger = InMemoryLedger()

    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_STRIPE,
                               proposed_kind="stripe", proposed_identifier="stripe-altis"))
    asyncio.run(_seed_promoted(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_STRIPE))
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_POSTGRES,
                               proposed_kind="postgres", proposed_identifier="pg-altis",
                               strategy="kpi_gap"))
    asyncio.run(_seed_rejected(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_POSTGRES,
                               reason="low_value"))

    main(
        argv=["list", "--tenant", ALTIS_SLUG, "--status", "all", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    # Summary: 1 pending, 1 promoted, 1 rejected.
    assert "1 pending, 1 promoted, 1 rejected" in out
    # All three candidate IDs appear in output.
    assert _CAND_NOTION in out
    assert _CAND_STRIPE in out
    assert _CAND_POSTGRES in out
    # Status columns appear.
    assert "PENDING" in out
    assert "PROMOTED" in out
    assert "REJECTED" in out


# ---------------------------------------------------------------------------
# Test 3: list --status pending filters correctly
# ---------------------------------------------------------------------------


def test_list_status_pending_filter(capsys) -> None:
    """--status pending shows only pending candidates."""
    ledger = InMemoryLedger()

    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_STRIPE,
                               proposed_kind="stripe", proposed_identifier="stripe-altis"))
    asyncio.run(_seed_promoted(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_STRIPE))

    main(
        argv=["list", "--tenant", ALTIS_SLUG, "--status", "pending", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert _CAND_NOTION in out
    assert _CAND_STRIPE not in out  # PROMOTED, should be filtered out
    # Summary still covers all candidates.
    assert "1 pending" in out
    assert "1 promoted" in out


# ---------------------------------------------------------------------------
# Test 4: list --strategy channel_mention filters correctly
# ---------------------------------------------------------------------------


def test_list_strategy_filter(capsys) -> None:
    """--strategy channel_mention shows only matching candidates."""
    ledger = InMemoryLedger()

    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION,
                               strategy="channel_mention"))
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_STRIPE,
                               proposed_kind="stripe", proposed_identifier="stripe-altis",
                               strategy="kpi_gap"))

    main(
        argv=[
            "list", "--tenant", ALTIS_SLUG,
            "--status", "all",
            "--strategy", "channel_mention",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert _CAND_NOTION in out
    assert _CAND_STRIPE not in out  # kpi_gap strategy, filtered out


# ---------------------------------------------------------------------------
# Test 5: list --json emits parseable JSONL
# ---------------------------------------------------------------------------


def test_list_json_output(capsys) -> None:
    """--json flag emits valid JSONL with correct fields."""
    ledger = InMemoryLedger()

    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    main(
        argv=["list", "--tenant", ALTIS_SLUG, "--status", "all", "--json", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l.strip() and not l.startswith("0 ") and not l.startswith("1 ")]
    # The summary line "1 pending, 0 promoted, 0 rejected" is not JSON — separate it.
    json_lines = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            json_lines.append(obj)
        except json.JSONDecodeError:
            pass  # summary line

    assert len(json_lines) == 1
    obj = json_lines[0]
    assert obj["candidate_id"] == _CAND_NOTION
    assert obj["proposed_kind"] == "notion"
    assert obj["status"] == "PENDING"
    assert "confidence" in obj
    assert "strategy" in obj


# ---------------------------------------------------------------------------
# Test 6: promote happy path -y
# ---------------------------------------------------------------------------


def test_promote_happy_path(capsys) -> None:
    """Promote with -y writes promoted entry and reports seq."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    main(
        argv=[
            "promote", _CAND_NOTION,
            "--tenant", ALTIS_SLUG,
            "--yes",
            "--via", "test-operator",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "promoted" in out
    assert _CAND_NOTION in out
    assert "source_candidate_promoted" in out

    # Verify the ledger actually has the promoted entry.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    exec_rows = [r for r in rows if r.get("kind") == "execute"]
    promoted_rows = [
        r for r in exec_rows
        if (r.get("payload") or {}).get("tool") == "emit_source_candidate_promoted"
    ]
    assert len(promoted_rows) == 1
    args = promoted_rows[0]["payload"]["args"]
    assert args["candidate_id"] == _CAND_NOTION
    assert args["promoted_by_person_id"] == "test-operator"


# ---------------------------------------------------------------------------
# Test 7: promote already-promoted → clear error, no double-write
# ---------------------------------------------------------------------------


def test_promote_already_promoted(capsys) -> None:
    """Promoting an already-promoted candidate emits an error and exits 1."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))
    asyncio.run(_seed_promoted(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    with pytest.raises(SystemExit) as exc_info:
        main(
            argv=[
                "promote", _CAND_NOTION,
                "--tenant", ALTIS_SLUG,
                "--yes",
                "--dsn", "ignored",
            ],
            ledger=ledger,
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "already promoted" in err

    # No additional promoted rows should have been written.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    exec_rows = [r for r in rows if r.get("kind") == "execute"]
    promoted_rows = [
        r for r in exec_rows
        if (r.get("payload") or {}).get("tool") == "emit_source_candidate_promoted"
    ]
    assert len(promoted_rows) == 1  # Only the pre-seeded one.


# ---------------------------------------------------------------------------
# Test 8: promote unknown candidate_id → clear error, exit 1
# ---------------------------------------------------------------------------


def test_promote_unknown_candidate_id(capsys) -> None:
    """Promoting a candidate_id that has no proposed entry exits 1 with clear error."""
    ledger = InMemoryLedger()  # Empty ledger.

    with pytest.raises(SystemExit) as exc_info:
        main(
            argv=[
                "promote", "deadbeefdeadbeefdeadbeefdeadbeef",
                "--tenant", ALTIS_SLUG,
                "--yes",
                "--dsn", "ignored",
            ],
            ledger=ledger,
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower() or "deadbeef" in err


# ---------------------------------------------------------------------------
# Test 9: reject happy path -y --reason duplicate
# ---------------------------------------------------------------------------


def test_reject_happy_path(capsys) -> None:
    """Reject with -y and --reason duplicate writes rejected entry."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    main(
        argv=[
            "reject", _CAND_NOTION,
            "--tenant", ALTIS_SLUG,
            "--reason", "duplicate",
            "--yes",
            "--via", "test-operator",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "rejected" in out
    assert "duplicate" in out
    assert _CAND_NOTION in out

    # Verify the ledger actually has the rejected entry.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    exec_rows = [r for r in rows if r.get("kind") == "execute"]
    rejected_rows = [
        r for r in exec_rows
        if (r.get("payload") or {}).get("tool") == "emit_source_candidate_rejected"
    ]
    assert len(rejected_rows) == 1
    args = rejected_rows[0]["payload"]["args"]
    assert args["candidate_id"] == _CAND_NOTION
    assert args["reason"] == "duplicate"
    assert args["rejected_by_person_id"] == "test-operator"


# ---------------------------------------------------------------------------
# Test 10: reject --reason nonsense → exit 1 with valid-reasons list
# ---------------------------------------------------------------------------


def test_reject_invalid_reason(capsys) -> None:
    """Invalid --reason value exits 1 and prints the list of valid reasons."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    with pytest.raises(SystemExit) as exc_info:
        main(
            argv=[
                "reject", _CAND_NOTION,
                "--tenant", ALTIS_SLUG,
                "--reason", "nonsense-reason",
                "--yes",
                "--dsn", "ignored",
            ],
            ledger=ledger,
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "invalid" in err.lower() or "nonsense-reason" in err
    # Valid reasons should be listed in the error.
    for reason in _valid_reject_reasons():
        assert reason in err


# ---------------------------------------------------------------------------
# Test 11: Tenant→uuid mapping uses same helper as ledger_recent.py
# ---------------------------------------------------------------------------


def test_tenant_uuid_mapping() -> None:
    """Tenant slug 'altis' resolves to the canonical UUID 7f032a92-..."""
    company_id = _tenant_to_company_uuid("altis")
    # The expected UUID is documented in ledger_recent.py known-slugs comment.
    assert str(company_id) == "7f032a92-7036-5126-a957-8d2607126169"


def test_tenant_uuid_empty_raises() -> None:
    """Empty slug raises ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        _tenant_to_company_uuid("")


def test_tenant_uuid_whitespace_raises() -> None:
    """Whitespace-only slug raises ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        _tenant_to_company_uuid("   ")


def test_tenant_uuid_case_insensitive() -> None:
    """Slug normalisation is case-insensitive (matches voice-agent behaviour)."""
    assert _tenant_to_company_uuid("ALTIS") == _tenant_to_company_uuid("altis")


# ---------------------------------------------------------------------------
# Test 12: Missing DSN AND no injected ledger → clear error
# ---------------------------------------------------------------------------


def test_missing_dsn_exits_with_error(monkeypatch, capsys) -> None:
    """No --dsn + no WORMBASE_LEDGER_DSN env + no injected ledger → exit 1."""
    monkeypatch.delenv("WORMBASE_LEDGER_DSN", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(
            argv=["list", "--tenant", ALTIS_SLUG, "--status", "all"],
            ledger=None,  # Force the DSN-resolution path.
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "DSN" in err or "dsn" in err.lower()


# ---------------------------------------------------------------------------
# Additional: _fold_candidates unit tests
# ---------------------------------------------------------------------------


def test_fold_candidates_empty() -> None:
    """Empty row list → empty candidate dict."""
    result = _fold_candidates([])
    assert result == {}


def test_fold_candidates_proposed_only() -> None:
    """A proposed-only entry folds to PENDING status."""
    rows = [
        {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_source_candidate_proposed",
                "args": {
                    "candidate_id": "abc123",
                    "proposed_kind": "notion",
                    "proposed_identifier": "notion-co",
                    "strategy": "channel_mention",
                    "confidence": 0.75,
                    "reasoning": "mention",
                    "evidence": {},
                },
            },
        }
    ]
    result = _fold_candidates(rows)
    assert "abc123" in result
    assert result["abc123"]["status"] == "PENDING"
    assert result["abc123"]["proposed_kind"] == "notion"


def test_fold_candidates_terminal_status_wins() -> None:
    """A promoted entry after a proposed entry → status=PROMOTED."""
    rows = [
        {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_source_candidate_proposed",
                "args": {
                    "candidate_id": "abc123",
                    "proposed_kind": "notion",
                    "proposed_identifier": "notion-co",
                    "strategy": "channel_mention",
                    "confidence": 0.75,
                    "reasoning": "mention",
                    "evidence": {},
                },
            },
        },
        {
            "kind": "execute",
            "seq": 5,
            "payload": {
                "tool": "emit_source_candidate_promoted",
                "args": {
                    "candidate_id": "abc123",
                    "promoted_by_person_id": "admin-1",
                },
            },
        },
    ]
    result = _fold_candidates(rows)
    assert result["abc123"]["status"] == "PROMOTED"
    assert result["abc123"]["seq"] == 5


def test_fold_candidates_rejected_status() -> None:
    """A rejected entry after a proposed entry → status=REJECTED with reason."""
    rows = [
        {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_source_candidate_proposed",
                "args": {
                    "candidate_id": "abc123",
                    "proposed_kind": "notion",
                    "proposed_identifier": "notion-co",
                    "strategy": "channel_mention",
                    "confidence": 0.75,
                    "reasoning": "mention",
                    "evidence": {},
                },
            },
        },
        {
            "kind": "execute",
            "seq": 7,
            "payload": {
                "tool": "emit_source_candidate_rejected",
                "args": {
                    "candidate_id": "abc123",
                    "rejected_by_person_id": "admin-1",
                    "reason": "duplicate",
                },
            },
        },
    ]
    result = _fold_candidates(rows)
    assert result["abc123"]["status"] == "REJECTED"
    assert result["abc123"]["reject_reason"] == "duplicate"
    assert result["abc123"]["seq"] == 7


# ---------------------------------------------------------------------------
# Additional: _summary_line unit tests
# ---------------------------------------------------------------------------


def test_summary_line_all_zeros() -> None:
    assert _summary_line([]) == "0 pending, 0 promoted, 0 rejected"


def test_summary_line_mixed() -> None:
    candidates = [
        {"status": "PENDING"},
        {"status": "PENDING"},
        {"status": "PROMOTED"},
        {"status": "REJECTED"},
        {"status": "REJECTED"},
        {"status": "REJECTED"},
    ]
    assert _summary_line(candidates) == "2 pending, 1 promoted, 3 rejected"


# ---------------------------------------------------------------------------
# Additional: _valid_reject_reasons includes the known L1 values
# ---------------------------------------------------------------------------


def test_valid_reject_reasons_contains_l1_values() -> None:
    """SourceCandidateRejectReason Literal includes all 5 L1 values."""
    reasons = _valid_reject_reasons()
    for expected in ("duplicate", "false_positive", "low_value", "out_of_scope", "other"):
        assert expected in reasons, f"{expected!r} not in valid reasons {reasons}"


# ---------------------------------------------------------------------------
# Additional: interactive confirm — monkeypatch builtins.input
# ---------------------------------------------------------------------------


def test_promote_interactive_confirm_yes(monkeypatch, capsys) -> None:
    """Interactive confirm answering 'y' proceeds with promotion."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    main(
        argv=[
            "promote", _CAND_NOTION,
            "--tenant", ALTIS_SLUG,
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "promoted" in out


def test_promote_interactive_confirm_no(monkeypatch, capsys) -> None:
    """Interactive confirm answering 'n' aborts without writing."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    main(
        argv=[
            "promote", _CAND_NOTION,
            "--tenant", ALTIS_SLUG,
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "aborted" in out

    # No promoted entry written.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    exec_rows = [r for r in rows if r.get("kind") == "execute"]
    promoted_rows = [
        r for r in exec_rows
        if (r.get("payload") or {}).get("tool") == "emit_source_candidate_promoted"
    ]
    assert len(promoted_rows) == 0


def test_reject_interactive_confirm_yes(monkeypatch, capsys) -> None:
    """Interactive confirm answering 'y' proceeds with rejection."""
    ledger = InMemoryLedger()
    asyncio.run(_seed_proposed(ledger, company_id=ALTIS_COMPANY_ID, candidate_id=_CAND_NOTION))

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    main(
        argv=[
            "reject", _CAND_NOTION,
            "--tenant", ALTIS_SLUG,
            "--reason", "out_of_scope",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "rejected" in out
    assert "out_of_scope" in out
