"""WORMBASE_SILENT_MODE — process-global listen-only flag.

See docs/superpowers/specs/2026-05-18-silent-mode-design.md for the
contract. Boot-time only; cached after first read; failure to parse
defaults to off and logs WARN once.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID, uuid4

_LOG = logging.getLogger(__name__)

ENV_VAR: Final[str] = "WORMBASE_SILENT_MODE"
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

_cached: bool | None = None


def is_silent_mode_enabled() -> bool:
    """Return True iff WORMBASE_SILENT_MODE is set to a truthy value.

    Cached after first call. Garbage values log a single WARN and return
    False (default is "talking" — failing safe to silence would create a
    different silent failure mode).
    """
    global _cached
    if _cached is not None:
        return _cached
    raw = os.environ.get(ENV_VAR, "")
    stripped = raw.strip().lower()
    if not stripped:
        _cached = False
        return _cached
    if stripped in _TRUTHY:
        _cached = True
        return _cached
    # Recognized falsey values pass through quietly; anything else WARNs.
    if stripped not in {"0", "false", "no", "off"}:
        _LOG.warning(
            "%s=%r not recognized, treating as off", ENV_VAR, raw
        )
    _cached = False
    return _cached


def _reset_for_tests() -> None:
    """Clear the cache — test-only hook."""
    global _cached
    _cached = None


__all__ = [
    "ENV_VAR",
    "SUPPRESSED_TARGET_KIND",
    "SuppressedResult",
    "SuppressedToolResult",
    "is_silent_mode_enabled",
    "record_suppressed",
]


# ---------------------------------------------------------------------------
# Suppressed-result types + ledger helper
# ---------------------------------------------------------------------------

Surface = Literal["chat", "voice", "mcp_write"]
SUPPRESSED_TARGET_KIND: Final[str] = "reply_suppressed"
_SILENT_MODE_SOURCE: Final[str] = "env"


@dataclass(frozen=True)
class SuppressedResult:
    """Returned by the chat / voice egress gates when silent mode suppresses a send."""

    ref_id: UUID
    ok: bool = True
    suppressed: bool = True

    @classmethod
    def new(cls) -> "SuppressedResult":
        return cls(ref_id=uuid4())


@dataclass(frozen=True)
class SuppressedToolResult:
    """Returned by `_pevr` when silent mode suppresses an MCP write tool."""

    ref_id: UUID
    ok: bool = True
    suppressed: bool = True

    @classmethod
    def new(cls) -> "SuppressedToolResult":
        return cls(ref_id=uuid4())


async def record_suppressed(
    ledger: Any,
    *,
    company_id: UUID,
    surface: Surface,
    tool: str,
    args: dict[str, Any],
    channel_id: str | None = None,
    tenant_id: UUID | None = None,
    presence_reason: str,
) -> None:
    """Write a reply_suppressed ledger entry capturing a would-have-been action.

    Best-effort: on ledger failure, logs ERROR with the payload and
    returns. Never raises into the egress path; never falls through to a
    real send.
    """
    ref_id = uuid4()
    payload = {
        "surface": surface,
        "tool": tool,
        "args": args,
        "channel_id": channel_id,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "presence_reason": presence_reason,
        "silent_mode_source": _SILENT_MODE_SOURCE,
        "ref_id": str(ref_id),
    }
    try:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": SUPPRESSED_TARGET_KIND,
                "ref_id": str(ref_id),
                "reason": f"silent_mode suppressed {surface}/{tool}",
                "proposed_by": "silent_mode",
            },
            execute_fn=lambda: {
                "tool": tool,
                "args": payload,
                "result_ref": str(ref_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "suppressed_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "silent_mode listen-only",
            },
            quadrant="active_deterministic",
        )
    except Exception as exc:  # broad on purpose: invariant > completeness
        _LOG.error(
            "record_suppressed failed: surface=%s tool=%s payload=%r err=%s",
            surface, tool, payload, exc,
        )
