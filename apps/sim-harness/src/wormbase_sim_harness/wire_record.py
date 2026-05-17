"""Record InfraEvent-shaped ledger entries into JSONL for wire-replay.

Captures the wire-driven entries the channel-adapter writes
(``channel_adapter.emit_chat_received``, ``channel_adapter.emit_chat_sent``,
``channel_adapter.emit_file_received``) into a JSONL file. Wire-replay
(see ``apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py``)
loads that file and feeds it through the channel-adapter pipeline at
production speed — same code path, deterministic input.

Identity entries (``emit_person_proposed`` etc.) are produced BY the
worm in response to wire events, NOT recorded here: wire-replay
re-runs them deterministically when the same wire events flow back
through.

PRD §8.3.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID


log = logging.getLogger("wormbase_sim_harness.wire_record")


# Tools captured by wire-record. These are the entries whose payloads
# wire-replay can reconstruct as ledger writes; the worm's downstream
# entries (emit_person_proposed, emit_source_proposed, ...) are
# regenerated on replay rather than recorded.
RECORD_TOOLS: tuple[str, ...] = (
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_chat_sent",
    "channel_adapter.emit_file_received",
)


def _row_kind(row: Mapping[str, Any]) -> str | None:
    """Return the row's kind, accepting either a dict or SQLAlchemy mapping."""
    return row.get("kind") if isinstance(row, Mapping) else None


def _row_seq(row: Mapping[str, Any]) -> int:
    return int(row["seq"]) if "seq" in row else 0


def _row_ts_iso(row: Mapping[str, Any]) -> str:
    """Best-effort isoformat timestamp from a ledger row.

    Accepts either a ``datetime`` (real Ledger / InMemoryLedger return
    tz-aware datetimes) or an ISO-8601 string for forward compatibility.
    """
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, str):
        return ts
    return ""


class WireRecorder:
    """Append wire-event ledger rows into a JSONL file.

    Stateful across calls — tracks ``last_seq`` so ``run_once()`` can be
    invoked from a follower loop without re-emitting captured rows. The
    output file is opened in append mode each tick; a long-running
    recorder + a parallel `tail -f`-style consumer therefore see new
    lines without buffering surprises.
    """

    def __init__(
        self,
        ledger: Any,
        company_id: UUID,
        out_path: Path,
        *,
        follow: bool = False,
        record_tools: tuple[str, ...] = RECORD_TOOLS,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._out_path = Path(out_path)
        self._follow = follow
        self._record_tools = tuple(record_tools)
        self._last_seq = 0
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        # Touch on init so wire-replay tooling can `tail -f` from cold start.
        if not self._out_path.exists():
            self._out_path.touch()

    @property
    def last_seq(self) -> int:
        return self._last_seq

    @property
    def out_path(self) -> Path:
        return self._out_path

    async def run_once(self) -> int:
        """Drain the ledger once. Returns the count of newly-written records."""
        rows = await self._ledger.fetch(self._company_id)
        rows = sorted(rows, key=_row_seq)
        n = 0
        with self._out_path.open("a") as f:
            for r in rows:
                seq = _row_seq(r)
                if seq <= self._last_seq:
                    continue
                if _row_kind(r) != "execute":
                    self._last_seq = max(self._last_seq, seq)
                    continue
                payload = r.get("payload") or {}
                if not isinstance(payload, Mapping):
                    self._last_seq = max(self._last_seq, seq)
                    continue
                tool = payload.get("tool")
                if tool not in self._record_tools:
                    self._last_seq = max(self._last_seq, seq)
                    continue
                rec: dict[str, Any] = {
                    "seq": seq,
                    "ts": _row_ts_iso(r),
                    "tool": tool,
                    "args": payload.get("args") or {},
                }
                f.write(json.dumps(rec) + "\n")
                self._last_seq = seq
                n += 1
        if n:
            log.info("wire-record captured %d events -> %s", n, self._out_path)
        return n

    async def run_forever(self, interval_s: float = 1.0) -> None:
        """Long-lived loop. Used by the CLI when ``--follow`` is set."""
        log.info("wire-record starting (follow) -> %s", self._out_path)
        while True:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("wire-record error: %s", exc)
            if not self._follow:
                return
            await asyncio.sleep(interval_s)


__all__ = ["WireRecorder", "RECORD_TOOLS"]
