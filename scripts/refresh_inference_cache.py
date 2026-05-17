#!/usr/bin/env python3
"""Wipe the WormBase inference cache + emit an audit PEVR cycle.

Invoked by ``make refresh-inference-cache`` (Wave H Phase 1 1A H).

Behavior
--------

1. Resolve the cache path from ``WORMBASE_INFERENCE_CACHE_PATH`` env
   (or the supplied ``--cache-path``).
2. If the file exists, ``DELETE FROM inference_cache`` and capture the
   row count.
3. Optionally write an ``inference_cache_refreshed`` PEVR cycle to the
   ledger when ``WORMBASE_LEDGER_DSN`` + ``WORMBASE_TENANT_ID`` are
   set. When the ledger is unreachable, the wipe still happens; the
   audit row is the only thing skipped (and the script's exit code
   surfaces the failure to ops).

Usage examples
--------------

    # Default — uses env defaults; emits ledger row if env is wired.
    make refresh-inference-cache

    # Override the cache path:
    WORMBASE_INFERENCE_CACHE_PATH=/var/foo.sqlite \\
        make refresh-inference-cache

    # Skip ledger write (e.g., during local dev with no DB):
    python -m scripts.refresh_inference_cache --no-ledger
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID, uuid5

# Stable namespace shared with channel-adapter / voice-agent so the
# tenant slug → company UUID mapping is consistent across subsystems.
_WORMBASE_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _tenant_to_company_uuid(slug: str) -> UUID:
    return uuid5(_WORMBASE_TENANT_NAMESPACE, slug.strip().lower())


def _resolve_cache_path(arg: str | None) -> Path:
    raw = (
        arg
        or os.environ.get("WORMBASE_INFERENCE_CACHE_PATH")
        or "/tmp/wormbase-inference-cache.sqlite"
    )
    return Path(raw)


def _wipe_cache(path: Path) -> int:
    """Wipe via the SqliteInferenceCache surface.

    The wipe is idempotent — deleting a never-created cache is a no-op
    that returns 0 invalidated rows. The cache file (and its parent
    directory) are auto-created if missing, which keeps the post-wipe
    state consistent with the next call's expectations.
    """
    from wormbase_inference.cache import SqliteInferenceCache  # local import

    cache = SqliteInferenceCache(path)
    try:
        return cache.invalidate_all()
    finally:
        cache.close()


async def _emit_ledger_audit(
    *,
    cache_path: str,
    entries_invalidated: int,
    reason: str,
    refreshed_by: str,
) -> bool:
    """Write one PEVR cycle ending in ``inference_cache_refreshed``.

    Returns True on success, False when env is not configured. Raises
    only on hard ledger failure (so ops sees a non-zero exit code).
    """
    dsn = os.environ.get("WORMBASE_LEDGER_DSN")
    tenant = os.environ.get("WORMBASE_TENANT_ID")
    if not dsn or not tenant:
        print(
            "refresh-inference-cache: WORMBASE_LEDGER_DSN / "
            "WORMBASE_TENANT_ID not set; skipping audit row.",
            file=sys.stderr,
        )
        return False

    from wormbase_ledger import Ledger

    company_id = _tenant_to_company_uuid(tenant)
    ledger = Ledger(dsn)
    try:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "inference_cache_refreshed",
                "ref_id": cache_path,
                "reason": (
                    f"refresh-inference-cache: invalidated "
                    f"{entries_invalidated} entries"
                ),
                "proposed_by": refreshed_by,
            },
            execute_fn=lambda: {
                "tool": "inference_cache_refreshed",
                "args": {
                    "cache_path": cache_path,
                    "entries_invalidated": entries_invalidated,
                    "reason": reason,
                    "refreshed_by": refreshed_by,
                },
                "result_ref": cache_path,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "cache_refreshed", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": f"cache rotated by {refreshed_by}",
            },
            quadrant="active_deterministic",
        )
    finally:
        dispose = getattr(ledger, "dispose", None)
        if callable(dispose):
            try:
                await dispose()
            except Exception:  # noqa: BLE001
                pass
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-path",
        default=None,
        help="Override WORMBASE_INFERENCE_CACHE_PATH for this run.",
    )
    parser.add_argument(
        "--reason",
        default="manual refresh via make refresh-inference-cache",
        help="Intent-conveying prose recorded on the ledger row.",
    )
    parser.add_argument(
        "--refreshed-by",
        default=os.environ.get("USER", "ops"),
        help="Actor token recorded as `refreshed_by` on the ledger row.",
    )
    parser.add_argument(
        "--no-ledger",
        action="store_true",
        help="Skip the ledger audit row (useful for offline dev).",
    )
    args = parser.parse_args(argv)

    path = _resolve_cache_path(args.cache_path)
    invalidated = _wipe_cache(path)
    print(
        f"refresh-inference-cache: wiped {invalidated} entries from {path}",
    )

    if args.no_ledger:
        print("refresh-inference-cache: --no-ledger set; skipping audit row.")
        return 0

    try:
        wrote = asyncio.run(
            _emit_ledger_audit(
                cache_path=str(path),
                entries_invalidated=invalidated,
                reason=args.reason,
                refreshed_by=f"refresh-inference-cache:{args.refreshed_by}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"refresh-inference-cache: audit row write FAILED ({exc}); "
            "the cache wipe completed but the substrate is missing the "
            "audit trail. Investigate before relying on hash-stability.",
            file=sys.stderr,
        )
        return 2

    if wrote:
        print(
            "refresh-inference-cache: audit row inference_cache_refreshed "
            "landed on the ledger."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
