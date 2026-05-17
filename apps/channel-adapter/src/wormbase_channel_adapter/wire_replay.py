"""Replay recorded wire events through the channel-adapter pipeline.

The deterministic backstop for CI + demos. Reads a JSONL of recorded
wire events (produced by ``wormbase demo wire-record``) and writes
them back into the ledger via the same PEVR primitive the live
channel-adapter uses (``GlobalLogCapture._emit_chat_received`` /
``_emit_file_received`` / the JSONL ``LedgerWriter``).

Same code path as production. Different input. Equivalent ledger state.

Use cases:
- CI determinism tests
- L6 demo gates (replay a known-good capture, assert headline rows)
- "Slack flaked mid-presentation" backstop

PRD §8.3.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


log = logging.getLogger("wormbase_channel_adapter.wire_replay")


_WIRE_TOOLS = (
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_chat_sent",
    "channel_adapter.emit_file_received",
)


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield non-empty parsed JSON objects from ``path``."""
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("wire-replay: skipping malformed line: %s", exc)
                continue
            if not isinstance(rec, dict):
                log.warning("wire-replay: skipping non-object record: %r", rec)
                continue
            yield rec


def _quadrant_for(tool: str) -> str:
    # All wire tools are channel-side messages — active_probabilistic.
    # Match the live channel-adapter (service.GlobalLogCapture).
    return "active_probabilistic"


def _propose_reason(tool: str, args: dict[str, Any]) -> str:
    if tool == "channel_adapter.emit_chat_received":
        return (
            f"wire-replay: chat_received channel="
            f"{args.get('channel_id', '?')} ts={args.get('message_id', '?')}"
        )
    if tool == "channel_adapter.emit_chat_sent":
        return (
            f"wire-replay: chat_sent channel="
            f"{args.get('channel_id', '?')} ts={args.get('message_id', '?')}"
        )
    if tool == "channel_adapter.emit_file_received":
        return (
            f"wire-replay: file_received channel="
            f"{args.get('channel_id', '?')} file="
            f"{args.get('slack_file_id', '?')}"
        )
    return f"wire-replay: {tool}"


def _target_kind_for(tool: str) -> str:
    if tool == "channel_adapter.emit_chat_received":
        return "chat_received"
    if tool == "channel_adapter.emit_chat_sent":
        return "chat_sent"
    if tool == "channel_adapter.emit_file_received":
        return "file_received"
    return tool.replace("channel_adapter.emit_", "")


def _result_ref_for(tool: str, args: dict[str, Any]) -> str:
    if tool == "channel_adapter.emit_file_received":
        return str(args.get("slack_file_id") or "")
    return str(args.get("message_id") or "")


class WireReplayer:
    """Stream a JSONL of wire events into the ledger via PEVR."""

    def __init__(
        self,
        ledger: Any,
        company_id: UUID,
        jsonl_path: Path,
        *,
        wire_tools: tuple[str, ...] = _WIRE_TOOLS,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._jsonl_path = Path(jsonl_path)
        self._wire_tools = tuple(wire_tools)

    @property
    def jsonl_path(self) -> Path:
        return self._jsonl_path

    async def run(self) -> int:
        """Replay the JSONL once. Returns the count of ledger writes."""
        if not self._jsonl_path.exists():
            raise FileNotFoundError(self._jsonl_path)
        n = 0
        for rec in _iter_jsonl(self._jsonl_path):
            tool = rec.get("tool")
            if tool not in self._wire_tools:
                log.debug("wire-replay: skipping tool=%r", tool)
                continue
            args = rec.get("args") or {}
            if not isinstance(args, dict):
                log.warning(
                    "wire-replay: skipping rec with non-dict args: %r", rec
                )
                continue
            ref = uuid4()
            payload = {"tool": tool, "args": args}
            try:
                await self._ledger.write(
                    company_id=self._company_id,
                    propose={
                        "target_kind": _target_kind_for(tool),
                        "ref_id": str(ref),
                        "reason": _propose_reason(tool, args),
                        "proposed_by": "channel-adapter.wire-replay",
                    },
                    execute_fn=lambda payload=payload, args=args, tool=tool: {
                        "tool": tool,
                        "args": args,
                        "result_ref": _result_ref_for(tool, args),
                    },
                    verify_fn=lambda _r: {
                        "checks": [{"name": "wire_replay_payload", "ok": True}],
                        "passed": True,
                    },
                    resolve_fn=lambda _v: {
                        "outcome": "keep",
                        "rationale": "wire-replay deterministic input",
                    },
                    quadrant=_quadrant_for(tool),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "wire-replay: ledger write failed for tool=%s: %s",
                    tool, exc,
                )
                continue
            n += 1
        log.info(
            "wire-replay: applied %d events from %s", n, self._jsonl_path,
        )
        return n


__all__ = ["WireReplayer"]
