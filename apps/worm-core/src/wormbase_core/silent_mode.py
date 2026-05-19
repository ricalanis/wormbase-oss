"""WORMBASE_SILENT_MODE — process-global listen-only flag.

See docs/superpowers/specs/2026-05-18-silent-mode-design.md for the
contract. Boot-time only; cached after first read; failure to parse
defaults to off and logs WARN once.
"""

from __future__ import annotations

import logging
import os
from typing import Final

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


__all__ = ["ENV_VAR", "is_silent_mode_enabled"]
