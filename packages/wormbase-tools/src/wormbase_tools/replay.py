"""``wormbase-tools replay`` — load a frozen snapshot, recompute a KPI.

This is the single entrypoint the auditor calls from a clean venv:

::

    pip install wormbase-tools
    wormbase-tools replay snapshot.jsonl --tenant <id> --to kpi_q3_revenue

Behaviour (per the demo-day PRD §7 P8)
======================================

1. Load and validate the JSONL snapshot file (``snapshot.jsonl``).
2. Filter entries to ``--tenant`` (a UUID or string company_id).
3. Verify the hash chain end-to-end. Fail-closed on any break.
4. Fold ledger entries into KPI projection state in pure Python.
5. Look up ``--to <kpi_id>`` and emit the value on stdout.

Exit codes (machine-readable)::

    0  KPI value resolved successfully (printed to stdout)
    1  hash mismatch, malformed snapshot, missing tenant, or KPI not found
    2  invalid CLI invocation (handled by click)

The CLI wraps :func:`replay_snapshot`, which is also importable for
test suites + alternate runners that want structured access to the
provenance trail (e.g. the demo-day stage replay diff in P14).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wormbase_tools.projections import (
    ProjectionState,
    compute_kpi_value,
    fold_kpis,
)
from wormbase_tools.snapshot import (
    SnapshotError,
    filter_by_tenant,
    load_snapshot,
    verify_chain,
)


class ReplayError(Exception):
    """Raised when replay cannot produce a KPI value.

    Distinct from :class:`~wormbase_tools.snapshot.SnapshotError` so
    callers can disambiguate "snapshot file is bad" from "snapshot is
    fine, but the requested KPI is not in it."
    """


@dataclass(frozen=True)
class ReplayResult:
    """Structured result of a replay invocation.

    The CLI emits ``str(value)`` to stdout for shell-script consumers;
    callers that want the provenance trail (which ledger entries
    contributed to which KPI value) can hold onto the dataclass.
    """

    kpi_id: str
    value: float | int | str | None
    terminal_hash: bytes
    entry_count: int
    tenant_id: str | None
    contributing_entry_ids: list[str] = field(default_factory=list)
    state: ProjectionState | None = None

    @property
    def terminal_hash_hex(self) -> str:
        return self.terminal_hash.hex()

    def to_json(self) -> dict[str, Any]:
        return {
            "kpi_id": self.kpi_id,
            "value": self.value,
            "terminal_hash": self.terminal_hash_hex,
            "entry_count": self.entry_count,
            "tenant_id": self.tenant_id,
            "contributing_entry_ids": list(self.contributing_entry_ids),
        }


def replay_snapshot(
    snapshot_path: Path | str,
    *,
    tenant_id: str | None,
    kpi_id: str,
) -> ReplayResult:
    """Replay a JSONL ledger snapshot and resolve ``kpi_id``.

    Parameters
    ----------
    snapshot_path:
        Path to the JSONL snapshot file. One ledger entry per line, in
        the format described in :mod:`wormbase_tools.snapshot`.
    tenant_id:
        ``company_id`` to pin replay to. If ``None``, the snapshot must
        contain entries from exactly one tenant (or the call raises).
    kpi_id:
        The KPI identifier to look up. May be a stable string id
        (``revenue.q3``), a UUID-string from ``emit_kpi_proposed``, or
        the demo-day shorthand (``kpi_q3_revenue``) so long as the
        snapshot contains a matching emit.

    Returns
    -------
    :class:`ReplayResult`. Caller is responsible for catching
    :class:`ReplayError` / :class:`SnapshotError`.

    Raises
    ------
    SnapshotError:
        On malformed snapshot, missing fields, chain break, etc.
    ReplayError:
        On tenant ambiguity or KPI not found.
    """
    path = Path(snapshot_path)
    entries = load_snapshot(path)

    # Tenant pin — auto-detect if the snapshot is single-tenant.
    if tenant_id is None:
        tenants = {str(e.get("company_id")) for e in entries}
        tenants.discard("None")
        tenants.discard("")
        if len(tenants) == 1:
            tenant_id = tenants.pop()
        elif len(tenants) > 1:
            raise ReplayError(
                "snapshot contains entries from multiple tenants "
                f"({sorted(tenants)}); pass --tenant to disambiguate"
            )
        else:
            raise ReplayError("snapshot has no tenant id on any entry")

    scoped = filter_by_tenant(entries, tenant_id)
    if not scoped:
        raise ReplayError(
            f"no entries match tenant_id={tenant_id} in {path}"
        )

    terminal_hash, entry_count = verify_chain(scoped)
    state = fold_kpis(scoped)

    value, contributing = compute_kpi_value(state, kpi_id)

    if value is None and kpi_id not in state.kpis:
        raise ReplayError(
            f"kpi_id={kpi_id!r} not found in snapshot. "
            f"Known KPI ids: {sorted(state.kpis.keys())}"
        )

    return ReplayResult(
        kpi_id=kpi_id,
        value=value,
        terminal_hash=terminal_hash,
        entry_count=entry_count,
        tenant_id=str(tenant_id),
        contributing_entry_ids=list(contributing),
        state=state,
    )


def emit_value_to_stdout(result: ReplayResult) -> None:
    """Print the KPI value as a single line on stdout.

    Auditor scripts pipe this into ``diff`` against ``/kpis``; the
    output format is therefore the bare value (``str(value)``) plus a
    trailing newline. Numeric values keep their numeric repr (no
    formatting/rounding) so byte-equality comparisons hold.
    """
    if result.value is None:
        # The KPI exists in the snapshot but no gold artifact has
        # produced a value yet — emit a deterministic sentinel.
        print("null")
    elif isinstance(result.value, bool):
        # JSON-style booleans for shell consumers; bool is an int
        # subclass, so check bool BEFORE int.
        print("true" if result.value else "false")
    else:
        print(result.value)


def emit_diff_to_stderr(snapshot_path: Path | str, message: str) -> None:
    """Write a fail-closed diagnostic to stderr.

    Used when replay aborts (snapshot malformed, hash mismatch, KPI
    missing). Format is intentionally close to ``git diff`` so an
    auditor can paste it into a ticket without reformatting.
    """
    import sys

    sys.stderr.write(f"--- snapshot: {snapshot_path}\n")
    sys.stderr.write("+++ replay\n")
    sys.stderr.write(f"@@ {message} @@\n")


def replay_to_json(
    snapshot_path: Path | str,
    *,
    tenant_id: str | None,
    kpi_id: str,
) -> str:
    """Convenience wrapper: replay + return JSON string.

    Used by the ``--json`` CLI flag and by external runners (e.g. the
    P14 stage-replay demo) that want to persist the provenance trail
    in a structured form.
    """
    result = replay_snapshot(snapshot_path, tenant_id=tenant_id, kpi_id=kpi_id)
    return json.dumps(result.to_json(), sort_keys=True, separators=(",", ":"))


# Re-export SnapshotError so callers can import every failure mode
# from one place: ``from wormbase_tools.replay import SnapshotError``.
__all__ = [
    "ReplayError",
    "ReplayResult",
    "SnapshotError",
    "emit_diff_to_stderr",
    "emit_value_to_stdout",
    "replay_snapshot",
    "replay_to_json",
]
