# > AUTHORED 2026-05-03: lifts the legacy IdentityDiscoveryLoop class +
# > module-level helpers (`_TARGET_TOOLS`, `_KNOWN_TOOLS`, MemberLookup
# > forwarding) for the existing test suite. Production never imports
# > this module.
"""Legacy identity-discovery loop — preserved for byte-equivalence tests.

The legacy ``IdentityDiscoveryLoop`` is preserved here — and ONLY here
— so the byte-equivalence regression test
`test_unknown_platform_id_reactivity.py::test_legacy_loop_byte_equivalent`
can keep asserting that the Reactivity facade and the legacy Loop
produce identical ledger entries.

Production wires `UnknownPlatformIdReactivity` (in `reactivities.py`)
exclusively. Importing this module emits a `DeprecationWarning`.
Drop in v2 once the byte-equivalence regression retires.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import warnings
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

from wormbase_identity_tracker.types import MemberLookup

warnings.warn(
    "wormbase_identity_tracker.legacy.IdentityDiscoveryLoop is deprecated; "
    "use UnknownPlatformIdReactivity instead. The legacy class is preserved "
    "only for the byte-equivalence regression test.",
    DeprecationWarning,
    stacklevel=2,
)


logger = logging.getLogger("wormbase_identity_tracker.legacy")


# Module-level constants — verbatim from identity_discovery.py:81-88.
_TARGET_TOOLS = (
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_file_received",
)
_KNOWN_TOOLS = (
    "emit_person_proposed",
    "emit_identity_linked",
)


class IdentityDiscoveryLoop:
    """Auto-discover Persons from unknown ``platform_user_id``s.

    Args:
        ledger: A live :class:`Ledger` (Postgres-backed) or an
            :class:`InMemoryLedger`. Both expose ``fetch(company_id)``
            and ``write(...)`` (the latter is reached transitively via
            :func:`write_actions.propose_person`).
        company_id: Tenant scope for the read + write.
        member_lookup: ``Callable[[platform, platform_user_id], dict |
            None]``. May be sync or async. ``None`` / empty dict means
            "skip — we don't know this user yet"; the loop will retry
            on the next cycle when more info is hopefully available.
        poll_interval_s: How long to sleep between ``run_once`` cycles
            in :meth:`run_forever`. Defaults to 30s — Person proposals
            are not latency-critical; admins confirm them on a
            human-typing cadence anyway.
    """

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        *,
        member_lookup: MemberLookup,
        poll_interval_s: float = 30.0,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._member_lookup = member_lookup
        self._poll_interval_s = poll_interval_s
        self._known: set[tuple[str, str]] = set()
        self._last_seq: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Periodic loop wrapper. Cancel-safe."""
        logger.info(
            "identity_discovery starting: company_id=%s interval=%.1fs",
            self._company_id, self._poll_interval_s,
        )
        while True:
            try:
                n = await self.run_once()
                if n:
                    logger.info(
                        "identity_discovery proposed %d new Person%s",
                        n, "" if n == 1 else "s",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("identity_discovery cycle failed: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise

    async def run_once(self) -> int:
        """Scan the ledger once; propose any newly-seen identities.

        Returns the count of Persons proposed this cycle.
        """
        # Imported lazily so the module is import-safe even in tests
        # that stub out wormbase_core.
        from wormbase_core import write_actions

        rows = await self._ledger.fetch(self._company_id)
        rows = sorted(rows, key=lambda r: int(r.get("seq", 0)))

        # Tenant-reset detection. We track the *highest* seq we have
        # ever seen (``self._last_seq``) — including rows the loop
        # itself wrote (e.g. ``emit_person_proposed`` PEVR cycles,
        # which advance the chain by 4 every time we propose). If the
        # current ledger's MAX(seq) is below that high-water mark, the
        # ledger has been wiped (e.g. ``wormbase demo seed
        # --reset-first``) and we need to rebuild from scratch.
        max_seq = int(rows[-1]["seq"]) if rows else 0
        if max_seq < self._last_seq:
            logger.info(
                "identity_discovery: tenant reset detected (max=%d < last=%d); "
                "clearing known set",
                max_seq, self._last_seq,
            )
            self._last_seq = 0
            self._known.clear()

        # 1) Refresh the known-set from every prior link/propose row.
        #    This is idempotent — adding the same tuple twice is fine.
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            tool = payload.get("tool")
            if tool not in _KNOWN_TOOLS:
                continue
            args = payload.get("args") or {}
            platform = args.get("platform")
            platform_user_id = args.get("platform_user_id")
            if platform and platform_user_id:
                self._known.add((str(platform), str(platform_user_id)))

        # Snapshot the cursor for this cycle so the proposes we write
        # below (which advance the ledger seq) don't accidentally show
        # up as "new" rows on a later iteration of the same cycle.
        cycle_cursor = self._last_seq

        # 2) Walk only NEW rows for chat / file events with raw native
        #    ids; propose a Person for each unknown identity.
        proposed = 0
        for r in rows:
            seq = int(r.get("seq", 0))
            if seq <= cycle_cursor:
                continue
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            tool = payload.get("tool")
            if tool not in _TARGET_TOOLS:
                continue
            args = payload.get("args") or {}
            platform = args.get("platform")
            platform_user_id = args.get("platform_user_id")
            if not platform or not platform_user_id:
                continue
            key = (str(platform), str(platform_user_id))
            if key in self._known:
                continue

            member = await self._safe_lookup(*key)
            if not member:
                # None / {} / lookup-failed — try again next cycle.
                continue

            name = (member.get("name") or "").strip() or "Unknown"
            email = member.get("email")
            try:
                await write_actions.propose_person(
                    self._ledger,
                    self._company_id,
                    name=name,
                    email=email,
                    platform=key[0],
                    platform_user_id=key[1],
                    position=None,
                    proposed_by="worm",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "identity_discovery: propose_person failed for %s/%s: %s",
                    key[0], key[1], exc,
                )
                continue

            self._known.add(key)
            proposed += 1

        # Advance the cursor to the global max_seq we observed at the
        # start of the cycle PLUS whatever we just wrote. We refetch
        # max_seq so the cursor reflects the post-write state — this
        # is what makes the tenant-reset comparison robust on the next
        # cycle (the wiped ledger's max_seq < this high-water mark).
        if rows:
            self._last_seq = max(max_seq, self._last_seq)
        # If we proposed Persons this cycle, our own writes pushed the
        # max higher; capture that too so a same-process restart sees
        # the right baseline.
        if proposed:
            post_rows = await self._ledger.fetch(self._company_id)
            if post_rows:
                post_max = max(int(r.get("seq", 0)) for r in post_rows)
                if post_max > self._last_seq:
                    self._last_seq = post_max
        return proposed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _safe_lookup(
        self, platform: str, platform_user_id: str,
    ) -> dict[str, Any] | None:
        """Call ``member_lookup`` with full exception isolation.

        The adapter may be sync or async; we accept both. Any exception
        is logged + swallowed so a flaky platform API never wedges the
        discovery loop.
        """
        try:
            result = self._member_lookup(platform, platform_user_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "identity_discovery: member_lookup raised for %s/%s: %s",
                platform, platform_user_id, exc,
            )
            return None
        if not result:
            return None
        if not isinstance(result, dict):
            logger.warning(
                "identity_discovery: member_lookup returned non-dict for %s/%s: %r",
                platform, platform_user_id, type(result).__name__,
            )
            return None
        return result


__all__ = ["IdentityDiscoveryLoop", "MemberLookup"]
