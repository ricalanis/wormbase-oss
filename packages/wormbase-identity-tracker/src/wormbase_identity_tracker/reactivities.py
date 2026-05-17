# > AUTHORED 2026-05-03: lifts IdentityDiscoveryReactivity from
# > apps/worm-core/src/wormbase_core/identity_discovery.py:299-449 with
# > five mechanical renames (class, id constant, name, description,
# > logger). The fire() body is preserved verbatim. Helpers
# > _rehydrate_known_set + _safe_lookup_static lift unchanged.
"""Identity-tracker Reactivities.

The package's headline Reactivity — `UnknownPlatformIdReactivity` —
auto-discovers Persons from unknown `(platform, platform_user_id)`
tuples in chat / file events. It writes `emit_person_proposed` PEVR
cycles via `wormbase_core.write_actions.propose_person` (the same code
path the dashboard's Person API uses).

Predicate: any execute envelope whose tool is the chat-received or
file-received emitter.
Condition: AlwaysAllow — dedup happens inside fire() via the known-set
rebuild.
Fire: known-set lookup → member_lookup callback → propose_person.

Renamed from `IdentityDiscoveryReactivity` (legacy id
``"identity_discovery"``) to `UnknownPlatformIdReactivity`
(new id ``"unknown_platform_id"``) per the worm-decomposition portfolio
plan §V. Historical `emit_reactivity_fired` entries with the legacy
reactivity_id remain in the chain (Rule 1); see
`LEGACY_REACTIVITY_ID` re-export below.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    Or,
    ReactivityContext,
    ReactivityResult,
)

from wormbase_identity_tracker.types import MemberLookup

logger = logging.getLogger("wormbase_identity_tracker.reactivities")


# Module constants — preserve from identity_discovery.py:81-88.
_TARGET_TOOLS = (
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_file_received",
)
_KNOWN_TOOLS = (
    "emit_person_proposed",
    "emit_identity_linked",
)


# Renamed: was "identity_discovery"; preserved as LEGACY_REACTIVITY_ID
# for trace-UI consumers that need to alias historical entries.
_REACTIVITY_ID = "unknown_platform_id"
LEGACY_REACTIVITY_ID = "identity_discovery"


class UnknownPlatformIdReactivity:
    """Reactivity-Protocol facade over identity-discovery's logic.

    Drop-in replacement for the legacy ``IdentityDiscoveryLoop`` when
    used with `ReactivityRunner`. Produces byte-equivalent
    `emit_person_proposed` ledger entries; see
    ``tests/test_unknown_platform_id_reactivity.py``::test_legacy_loop_byte_equivalent
    for the regression proof.

    Construction takes the same ``member_lookup`` callable the legacy
    Loop expected so existing wiring code (Slack adapter shims) is
    unchanged at the call site — only the class name and id changed.
    """

    id = _REACTIVITY_ID
    name = "Unknown Platform ID"
    description = (
        "Auto-discover Persons from unknown platform_user_ids in chat / "
        "file events. Calls platform member_lookup for workspace metadata "
        "and proposes a Person via the same write_actions.propose_person "
        "path the dashboard's Person API uses."
    )
    scope = "company"

    def __init__(self, *, member_lookup: MemberLookup) -> None:
        self._member_lookup = member_lookup
        # Predicate: any execute envelope whose tool is the chat-received
        # or file-received emitter.
        self.predicate = Or(
            EntryKind("chat_received"),
            EntryKind("file_received"),
        )
        # Condition: AlwaysAllow — dedup inside fire() via known-set.
        self.condition = AlwaysAllow()

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Mirror IdentityDiscoveryLoop.run_once for ONE entry.

        (Body preserved verbatim from identity_discovery.py:374-449.)
        """
        payload = entry.get("payload") or {}
        tool = payload.get("tool") or ""
        if tool not in _TARGET_TOOLS:
            return ReactivityResult(fired=False)
        args = payload.get("args") or {}
        platform = args.get("platform")
        platform_user_id = args.get("platform_user_id")
        if not platform or not platform_user_id:
            return ReactivityResult(fired=False)

        known = await _rehydrate_known_set(
            context.ledger, context.company_id,
        )
        key = (str(platform), str(platform_user_id))
        if key in known:
            return ReactivityResult(fired=False)

        member = await _safe_lookup_static(
            self._member_lookup, *key,
        )
        if not member:
            return ReactivityResult(fired=False)

        name = (member.get("name") or "").strip() or "Unknown"
        email = member.get("email")
        try:
            from wormbase_core import write_actions

            _, write_result = await write_actions.propose_person(
                context.ledger,
                context.company_id,
                name=name,
                email=email,
                platform=key[0],
                platform_user_id=key[1],
                position=None,
                proposed_by="worm",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "UnknownPlatformIdReactivity: propose_person failed "
                "for %s/%s: %s",
                key[0], key[1], exc,
            )
            return ReactivityResult(fired=False)

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="person_proposed")],
            novelty_key=f"{key[0]}:{key[1]}",
            budget_used={"per_tenant": 1},
        )


async def _rehydrate_known_set(
    ledger: Ledger | InMemoryLedger, company_id: UUID,
) -> set[tuple[str, str]]:
    """Build the (platform, platform_user_id) known-set from the ledger.

    (Body preserved verbatim from identity_discovery.py:452-475.)
    """
    rows = await ledger.fetch(company_id)
    known: set[tuple[str, str]] = set()
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
            known.add((str(platform), str(platform_user_id)))
    return known


async def _safe_lookup_static(
    lookup: MemberLookup, platform: str, platform_user_id: str,
) -> dict[str, Any] | None:
    """Module-level mirror of IdentityDiscoveryLoop._safe_lookup.

    (Body preserved verbatim from identity_discovery.py:478-505.)
    """
    try:
        result = lookup(platform, platform_user_id)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "unknown_platform_id: member_lookup raised for %s/%s: %s",
            platform, platform_user_id, exc,
        )
        return None
    if not result:
        return None
    if not isinstance(result, dict):
        logger.warning(
            "unknown_platform_id: member_lookup returned non-dict "
            "for %s/%s: %r",
            platform, platform_user_id, type(result).__name__,
        )
        return None
    return result


# ---------------------------------------------------------------------------
# Wave B.5 G.4 — PositionInferenceReactivity
# ---------------------------------------------------------------------------


_POSITION_REACTIVITY_ID = "position_inference"
_POSITION_THRESHOLD = 0.5


class PositionInferenceReactivity:
    """Greenfield Reactivity — propose Person.position from chatter signal.

    Subscribes to ``chat_received``. On every fire(), reads the recent
    chat history of the message's ``sender_person`` from the ledger,
    runs ``positions.score_signals`` over the texts, and — if the best
    position's confidence ≥ ``_POSITION_THRESHOLD`` AND that Person does
    not already have a position assigned (or pending) — emits a
    ``emit_position_proposed`` PEVR cycle via
    ``write_actions.propose_position``.

    Sister class to ``UnknownPlatformIdReactivity``: same predicate
    family (chat events), same Pydantic-payload-validated PEVR shape,
    same dedup posture (rehydrate-known-set on every fire to keep the
    Reactivity stateless across tenant resets — see
    ``_rehydrate_known_positions``).

    Per Doctrine Addendum 2 §E, ``position_proposed`` is the propose-step
    kind for this Reactivity; admin confirmation flows through the
    confirm-step ``emit_position_assigned`` (already present pre-Wave A).

    Lake-maintainer's ``_emit_signal`` is the canonical reference for
    threshold-gated PEVR emission; we follow the same shape.
    """

    id = _POSITION_REACTIVITY_ID
    name = "Position Inference"
    description = (
        "Propose Person.position from chat-history signal scoring. Fires "
        "an emit_position_proposed PEVR cycle when score crosses 0.5 and "
        "the Person does not already have a position assigned."
    )
    scope = "company"

    def __init__(self, *, threshold: float = _POSITION_THRESHOLD) -> None:
        self._threshold = threshold
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        tool = payload.get("tool") or ""
        # Predicate already gates on EntryKind("chat_received"), but
        # double-check the tool to skip non-channel-adapter chat entries.
        if tool != "channel_adapter.emit_chat_received":
            return ReactivityResult(fired=False)

        args = payload.get("args") or {}
        sender_person = args.get("sender_person")
        if not sender_person:
            return ReactivityResult(fired=False)

        # Idempotency: skip if this Person already carries a position
        # (assigned, proposed-and-kept, or proposed-pending).
        known = await _rehydrate_known_positions(
            context.ledger, context.company_id,
        )
        if sender_person in known:
            return ReactivityResult(fired=False)

        # Aggregate texts from this Person's chat_received history
        # (current + prior). Stateless — re-folded every fire.
        texts = await _collect_person_chat_texts(
            context.ledger, context.company_id, person_id=sender_person,
        )
        if not texts:
            return ReactivityResult(fired=False)

        # Local import: positions.score_signals lives next to this module.
        from wormbase_identity_tracker.positions import score_signals

        best_position, confidence, signals = score_signals(texts)
        if best_position is None or confidence < self._threshold:
            return ReactivityResult(fired=False)

        try:
            from wormbase_core import write_actions
            from uuid import UUID as _UUID

            await write_actions.propose_position(
                context.ledger,
                context.company_id,
                person_id=_UUID(sender_person),
                position=best_position,
                confidence=confidence,
                signals=signals,
                proposed_by="worm",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PositionInferenceReactivity: propose_position failed "
                "for person=%s position=%s: %s",
                sender_person, best_position, exc,
            )
            return ReactivityResult(fired=False)

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="position_proposed")],
            novelty_key=f"position:{sender_person}",
            budget_used={"per_tenant": 1},
        )


async def _rehydrate_known_positions(
    ledger: Ledger | InMemoryLedger, company_id: UUID,
) -> set[str]:
    """Return the set of person_ids that already carry a position.

    A Person is considered "known" for inference dedup if any of:

      * ``emit_person_proposed`` carried a non-null ``position``
      * ``emit_position_assigned`` (admin confirm-step) landed
      * ``emit_position_proposed`` (worm propose-step) landed —
        regardless of resolve outcome, so we don't re-propose on every
        poll while the admin is still reviewing the first proposal.

    Stateless: re-folds the ledger on every call. Mirrors
    ``_rehydrate_known_set`` shape so tenant-reset semantics are
    inherited automatically.
    """
    rows = await ledger.fetch(company_id)
    known: set[str] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if tool == "emit_person_proposed":
            if args.get("position"):
                pid = args.get("person_id")
                if pid:
                    known.add(str(pid))
        elif tool in ("emit_position_assigned", "emit_position_proposed"):
            pid = args.get("person_id")
            if pid:
                known.add(str(pid))
    return known


async def _collect_person_chat_texts(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    person_id: str,
) -> list[str]:
    """Collect every ``chat_received`` text from ``person_id`` in fold order.

    Used by ``PositionInferenceReactivity`` to score signal density over
    the Person's full chat history; the count of patterns matched
    against patterns-in-position drives the confidence number written
    into the propose entry.
    """
    rows = await ledger.fetch(company_id)
    texts: list[str] = []
    for r in sorted(rows, key=lambda x: x["seq"]):
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "channel_adapter.emit_chat_received":
            continue
        args = payload.get("args") or {}
        if str(args.get("sender_person")) != str(person_id):
            continue
        text = args.get("text") or ""
        if text:
            texts.append(text)
    return texts


# ---------------------------------------------------------------------------
# Wave B.5 G.5 — ResourceOwnershipReactivity
# ---------------------------------------------------------------------------


_RESOURCE_OWNERSHIP_REACTIVITY_ID = "resource_ownership"
_RESOURCE_OWNERSHIP_THRESHOLD = 0.5
# Confidence is computed as min(1.0, signal_count / _RESOURCE_OWNERSHIP_DENOM).
# At 4.0 the threshold (≥ 0.5) requires ≥ 2 signals to fire — same posture as
# PositionInferenceReactivity (which requires ≥ 2 of 4 signal patterns).
_RESOURCE_OWNERSHIP_DENOM = 4.0
# Stable nil UUID for the worm's own Person identity. The
# resource_role_proposed payload requires a UUID for ``proposed_by`` (unlike
# position_proposed which accepts a free-form string), so this Reactivity
# uses UUID(int=0) to mean "the worm" until a per-tenant worm Person row is
# resolvable. Trace UI consumers should special-case this UUID for display.
_WORM_PERSON_ID = UUID(int=0)
# UUID regex (canonical 8-4-4-4-12 hex format). Substring-matches inside
# free-form chat text — matches the same UUID encoding the canonical
# Pydantic payloads emit (model_dump(mode="json")).
import re  # noqa: E402  (import grouped with the constant it backs)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
)


class ResourceOwnershipReactivity:
    """Greenfield Reactivity — propose resource maintainer roles from chatter.

    Sister to ``PositionInferenceReactivity``: signal-driven proposer that
    aggregates per-(person, resource) chatter and consumption events and,
    on threshold crossing, emits a ``emit_resource_role_proposed`` PEVR
    cycle via ``write_actions.propose_resource_role``.

    Subscribes to BOTH:
      * ``chat_received`` — text mentioning a resource UUID counts as a
        ``chat_mention`` signal (one per message; same resource mentioned
        twice in the same message dedupes to a single signal).
      * ``data_product_consumed`` — a Person consuming a data product
        counts as a ``data_product_consumed`` signal (one per
        consumption event).

    Confidence is ``min(1.0, signal_count / 4.0)``; threshold ≥ 0.5 means
    at least 2 signals are required before the worm proposes the
    maintainer role. This matches the conservative posture of
    ``PositionInferenceReactivity`` (≥ 2 of 4-5 patterns).

    Idempotency: skip (person, resource) pairs that already carry an
    ``emit_resource_role_proposed`` OR ``emit_resource_role_assigned``
    entry — same posture as ``PositionInferenceReactivity`` (Doctrine
    Rule 4: idempotent fold semantics).

    Novelty key: ``resource_role:{person_id}:{resource_id}`` so the
    Reactivity-runner dedupes per pair.
    """

    id = _RESOURCE_OWNERSHIP_REACTIVITY_ID
    name = "Resource Ownership"
    description = (
        "Propose resource maintainer roles from chatter + consumption "
        "signals. Fires emit_resource_role_proposed PEVR cycle when "
        "aggregate confidence crosses 0.5 and the (person, resource) "
        "pair has no proposal in flight."
    )
    scope = "company"

    def __init__(
        self, *, threshold: float = _RESOURCE_OWNERSHIP_THRESHOLD,
    ) -> None:
        self._threshold = threshold
        self.predicate = Or(
            EntryKind("chat_received"),
            EntryKind("data_product_consumed"),
        )
        self.condition = AlwaysAllow()

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        tool = payload.get("tool") or ""
        args = payload.get("args") or {}

        # Pull (person, resource) candidates from this entry.
        if tool == "channel_adapter.emit_chat_received":
            sender = args.get("sender_person")
            text = args.get("text") or ""
            if not sender or not text:
                return ReactivityResult(fired=False)
            mentioned = _extract_resource_ids(text)
            if not mentioned:
                return ReactivityResult(fired=False)
            # First mentioned resource drives this fire(); the runner will
            # re-fire on subsequent chat_received entries that mention
            # other resources.
            person_id = str(sender)
            resource_id = mentioned[0]
        elif tool == "emit_data_product_consumed":
            consumer = args.get("consumed_by_person_id")
            data_product_id = args.get("data_product_id")
            if not consumer or not data_product_id:
                return ReactivityResult(fired=False)
            person_id = str(consumer)
            resource_id = str(data_product_id)
        else:
            return ReactivityResult(fired=False)

        # Idempotency: skip if this (person, resource) already has an
        # in-flight or assigned role.
        known = await _rehydrate_known_resource_roles(
            context.ledger, context.company_id,
        )
        if (person_id, resource_id) in known:
            return ReactivityResult(fired=False)

        # Aggregate signal counts across the full ledger. Stateless —
        # re-folded every fire so tenant resets are honored.
        signals = await _aggregate_resource_signals(
            context.ledger,
            context.company_id,
            person_id=person_id,
            resource_id=resource_id,
        )
        signal_count = sum(signals.values())
        if signal_count == 0:
            return ReactivityResult(fired=False)

        confidence = min(1.0, signal_count / _RESOURCE_OWNERSHIP_DENOM)
        if confidence < self._threshold:
            return ReactivityResult(fired=False)

        # Order signals deterministically for replay byte-equivalence.
        signal_tokens = tuple(sorted(signals.keys()))

        try:
            from wormbase_core import write_actions
            from uuid import UUID as _UUID

            await write_actions.propose_resource_role(
                context.ledger,
                context.company_id,
                person_id=_UUID(person_id),
                resource_id=_UUID(resource_id),
                role="maintainer",
                confidence=confidence,
                signals=signal_tokens,
                proposed_by=_WORM_PERSON_ID,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ResourceOwnershipReactivity: propose_resource_role failed "
                "for person=%s resource=%s: %s",
                person_id, resource_id, exc,
            )
            return ReactivityResult(fired=False)

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="resource_role_proposed")],
            novelty_key=f"resource_role:{person_id}:{resource_id}",
            budget_used={"per_tenant": 1},
        )


def _extract_resource_ids(text: str) -> list[str]:
    """Extract candidate resource UUIDs from free-form chat ``text``.

    Returns the deduplicated list in first-occurrence order so trace
    output is stable across replays.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _UUID_RE.findall(text):
        norm = match.lower()
        if norm not in seen_set:
            seen_set.add(norm)
            seen.append(norm)
    return seen


async def _rehydrate_known_resource_roles(
    ledger: Ledger | InMemoryLedger, company_id: UUID,
) -> set[tuple[str, str]]:
    """Return (person_id, resource_id) pairs that already have a role.

    A pair is "known" if any of:
      * ``emit_resource_role_proposed`` (worm propose-step) landed —
        regardless of resolve outcome (same belt-and-suspenders posture
        as ``_rehydrate_known_positions``).
      * ``emit_resource_role_assigned`` (admin confirm-step) landed.

    Stateless: re-folds the ledger on every call.
    """
    rows = await ledger.fetch(company_id)
    known: set[tuple[str, str]] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        if tool not in (
            "emit_resource_role_proposed",
            "emit_resource_role_assigned",
        ):
            continue
        args = payload.get("args") or {}
        pid = args.get("person_id")
        rid = args.get("resource_id")
        if pid and rid:
            known.add((str(pid), str(rid)))
    return known


async def _aggregate_resource_signals(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    person_id: str,
    resource_id: str,
) -> dict[str, int]:
    """Count per-signal occurrences for a (person, resource) pair.

    Returns a dict ``{signal_token: count}`` aggregated over the full
    ledger. Signal tokens:

      * ``chat_mention`` — count of distinct ``chat_received`` entries
        from ``person_id`` whose text mentions ``resource_id``.
      * ``data_product_consumed`` — count of ``data_product_consumed``
        entries with ``consumed_by_person_id == person_id`` and
        ``data_product_id == resource_id``.

    Used by ``ResourceOwnershipReactivity.fire`` to compute confidence.
    """
    rows = await ledger.fetch(company_id)
    counts: dict[str, int] = {}
    person_target = str(person_id)
    resource_target = str(resource_id).lower()
    for r in sorted(rows, key=lambda x: x["seq"]):
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if tool == "channel_adapter.emit_chat_received":
            if str(args.get("sender_person")) != person_target:
                continue
            text = args.get("text") or ""
            mentions = _extract_resource_ids(text)
            if resource_target in mentions:
                counts["chat_mention"] = counts.get("chat_mention", 0) + 1
        elif tool == "emit_data_product_consumed":
            if str(args.get("consumed_by_person_id")) != person_target:
                continue
            if str(args.get("data_product_id")).lower() != resource_target:
                continue
            counts["data_product_consumed"] = (
                counts.get("data_product_consumed", 0) + 1
            )
    return counts


__all__ = [
    "LEGACY_REACTIVITY_ID",
    "PositionInferenceReactivity",
    "ResourceOwnershipReactivity",
    "UnknownPlatformIdReactivity",
    "_aggregate_resource_signals",
    "_collect_person_chat_texts",
    "_extract_resource_ids",
    "_rehydrate_known_positions",
    "_rehydrate_known_resource_roles",
    "_rehydrate_known_set",
    "_safe_lookup_static",
]
