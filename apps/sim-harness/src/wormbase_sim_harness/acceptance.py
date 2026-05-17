"""Post-run acceptance — confirm Path 3 captured what the harness drove.

The harness is a black-box driver; it knows it sent N messages from M
personas with K file drops. After the run, we read the ledger and check
that the expected ``execute`` entries landed:

  - At least one ``channel_adapter.emit_chat_received`` per persona that
    actually said something (or — relaxed — at least N total messages).
  - At least one ``channel_adapter.emit_file_received`` if any beat had
    a file drop.
  - At least one ``emit_source_proposed`` (proves DropAndProfileFlow
    fired off the file drop).
  - At least one ``channel_adapter.emit_chat_sent`` (proves the worm
    replied to @-mentions).

We use the public Ledger fetch + filter on ``ts`` >= scenario_started_at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class _LedgerLike(Protocol):
    """Minimal protocol so tests can pass an in-process fake."""

    async def fetch(
        self, company_id: UUID, until_ts: datetime | None = ...
    ) -> list[dict[str, Any]]: ...


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class AcceptanceReport:
    """Aggregated pass/fail per check."""

    checks: list[CheckResult] = field(default_factory=list)
    entries_scanned: int = 0

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "entries_scanned": self.entries_scanned,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _execute_tool(entry: dict[str, Any]) -> str | None:
    """Return the ``tool`` of an execute entry, or None."""
    if entry.get("kind") != "execute":
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool")
    return tool if isinstance(tool, str) else None


async def assert_demo_invariants(
    ledger: _LedgerLike,
    company_id: UUID,
    scenario_started_at: datetime,
    *,
    expect_chat_in: bool = True,
    expect_file_in: bool = True,
    expect_source_proposed: bool = True,
    expect_chat_out: bool = True,
) -> AcceptanceReport:
    """Read the ledger and assert the demo's externally-observable invariants.

    The flags let callers tighten or relax the gate per scenario; defaults
    match ``demo-c-plus-b.yml`` which exercises all four.
    """
    rows = await ledger.fetch(company_id)
    fresh = [
        r
        for r in rows
        if isinstance(r.get("ts"), datetime) and r["ts"] >= scenario_started_at
    ]

    chat_in = sum(
        1 for r in fresh if _execute_tool(r) == "channel_adapter.emit_chat_received"
    )
    file_in = sum(
        1 for r in fresh if _execute_tool(r) == "channel_adapter.emit_file_received"
    )
    source_proposed = sum(1 for r in fresh if _execute_tool(r) == "emit_source_proposed")
    chat_out = sum(
        1 for r in fresh if _execute_tool(r) == "channel_adapter.emit_chat_sent"
    )

    report = AcceptanceReport(entries_scanned=len(fresh))
    if expect_chat_in:
        report.checks.append(
            CheckResult(
                name="chat_received >= 1",
                passed=chat_in >= 1,
                detail=f"observed={chat_in}",
            )
        )
    if expect_file_in:
        report.checks.append(
            CheckResult(
                name="file_received >= 1",
                passed=file_in >= 1,
                detail=f"observed={file_in}",
            )
        )
    if expect_source_proposed:
        report.checks.append(
            CheckResult(
                name="source_proposed >= 1",
                passed=source_proposed >= 1,
                detail=f"observed={source_proposed}",
            )
        )
    if expect_chat_out:
        report.checks.append(
            CheckResult(
                name="chat_sent >= 1",
                passed=chat_out >= 1,
                detail=f"observed={chat_out}",
            )
        )
    return report


__all__ = ["assert_demo_invariants", "AcceptanceReport", "CheckResult"]
