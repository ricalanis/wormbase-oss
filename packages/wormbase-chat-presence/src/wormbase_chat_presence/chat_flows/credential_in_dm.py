"""CredentialInDmFlow — DM with credential URI → connected-source proposal.

Lifted from flows.py:206-293 (URI patterns + class), plus
``_scrub_credential`` (line 223), ``_find_recent_proactive_offer``
(line 1047), ``link_credential_to_proactive_offer`` (line 1084) and
``credential_in_dm_with_offer_link`` (line 1145). Behavior unchanged.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from wormbase_chat_presence.chat_flows._shared import (
    CredentialLeakError,
    _BuilderHostingFlow,
    _PIIGateProto,
)
from wormbase_core.reactivity import InfraEvent
from wormbase_core.source_builder import (
    SourceBuilder,
    SourceProposal,
    build_full_sequence,
)
from wormbase_core.types import CorrelationId
from wormbase_ledger import InMemoryLedger, Ledger


_URI_PATTERNS: list[tuple[re.Pattern[str], Literal["database", "blob", "rest_api"]]] = [
    (re.compile(r"\bpostgres(?:ql)?://\S+", re.IGNORECASE), "database"),
    (re.compile(r"\bmysql://\S+", re.IGNORECASE), "database"),
    (re.compile(r"\bmongodb(?:\+srv)?://\S+", re.IGNORECASE), "database"),
    (re.compile(r"\bsqlite:///\S+", re.IGNORECASE), "database"),
    (re.compile(r"\bs3://\S+", re.IGNORECASE), "blob"),
    (
        re.compile(
            r"https?://[^\s]*(api|stripe|salesforce|hubspot|segment)[^\s]*",
            re.IGNORECASE,
        ),
        "rest_api",
    ),
    (re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"), "rest_api"),
]


def _scrub_credential(uri: str) -> str:
    """Strip user:pass before storing the URI.

    Local copy of the canonical helper in `wormbase_core.flows`, kept
    chat-worm-private to avoid a `chat-presence -> worm-core` reach for
    a one-line regex sub. Drift-pinned by the contract test in
    `tests/contract/test_helper_duplication_drift.py` (O-B5).
    """
    return re.sub(r"://[^@\s]+@", "://[REDACTED]@", uri)


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


class CredentialInDmFlow(_BuilderHostingFlow):
    """DM-only flow that recognizes a credential URI and runs the full sequence."""

    def __init__(
        self,
        builder: SourceBuilder,
        pii_gate: _PIIGateProto,
        connector_register: Callable[[str], Awaitable[str] | str] | None = None,
        credential_ref_resolver: (
            Callable[[str, str], Awaitable[str | None] | str | None] | None
        ) = None,
    ) -> None:
        """Initialise the credential-DM flow.

        ``credential_ref_resolver`` (additive 2026-06-10, default
        ``None``): optional callable ``(uri, scrubbed_uri) ->
        credential_ref`` invoked at connect-time so the host can map a
        DM-pasted credential to a broker slot (e.g. the host writes the
        secret payload to Vault under a freshly minted slot key, then
        returns that key as the ``credential_ref``). When ``None`` (the
        default — preserves byte-identical pre-2026-06-10 behavior), the
        flow connects without a credential_ref; the source_connected
        entry carries ``credential_ref=None`` and sampler-side
        reconstruction returns None for opaque-secret URIs.

        DM-pasted credentials reach this flow with the actual secret in
        the URI fragment (``postgres://user:pass@...``). The flow
        scrubs the secret before persisting and never logs the original;
        the resolver — when supplied — is the only seam where an
        application can capture the raw URI long enough to provision a
        broker slot. In the read-only broker model that ships today
        (operator-provisioned slots), this resolver is left None and
        opaque-secret DM credentials surface as honest-empty samples
        until the operator wires the slot out-of-band.
        """
        self._builder = builder
        self._pii_gate = pii_gate
        self._connector_register = connector_register
        self._credential_ref_resolver = credential_ref_resolver

    async def on_dm(self, event: InfraEvent) -> CorrelationId | None:
        if event.source != "dm":
            raise CredentialLeakError(
                "credential URI cannot be processed outside a DM"
            )
        text = event.text or ""
        for pat, kind in _URI_PATTERNS:
            m = pat.search(text)
            if not m:
                continue
            uri = m.group(0)
            scrubbed = _scrub_credential(uri)
            # Run PII gate side-effect for ledger.
            await self._pii_gate.check(text, {"source": "dm"})
            person_id = (
                UUID(event.person_id) if event.person_id and _is_uuid(event.person_id)
                else None
            )
            proposal = SourceProposal(
                proposed_uri=scrubbed,
                proposed_type=kind,
                proposed_domain="general",
                proposed_classification="confidential",
                proposed_owner_person_id=person_id,
                added_by_person_id=person_id,
                added_via_flow="credential_offered_in_dm",
                added_in_response_to=f"dm:{event.message_id}",
                company_id=event.company_id,
            )

            async def _connect() -> str:
                if self._connector_register is None:
                    return f"creds-{uuid4()}"
                res = self._connector_register(uri)
                if hasattr(res, "__await__"):
                    return await res  # type: ignore[no-any-return]
                return str(res)

            # Resolve credential_ref via the optional host hook. The raw
            # ``uri`` is intentionally NOT logged; only handed to the
            # resolver which is expected to provision a broker slot.
            credential_ref: str | None = None
            if self._credential_ref_resolver is not None:
                resolved = self._credential_ref_resolver(uri, scrubbed)
                if hasattr(resolved, "__await__"):
                    resolved = await resolved  # type: ignore[assignment]
                credential_ref = (
                    str(resolved) if resolved is not None else None
                )

            return await build_full_sequence(
                self._builder,
                proposal,
                confirmer_id=person_id or uuid4(),
                domain_id=uuid4(),
                classification="confidential",
                connection_fn=_connect,
                profile_fn=lambda: {
                    "row_count": 0,
                    "column_count": 0,
                    "schema_hash": "deferred",
                    "profile_ref": "deferred",
                },
                credential_ref=credential_ref,
            )
        return None


# ---------------------------------------------------------------------------
# Proactive-offer linking helpers
#
# Lifted from flows.py:1044-1199. When a credential lands in DM and a recent
# ``emit_proactive_offer`` exists from the same person, link them via
# ``correlation_id`` so the dashboard's onboarding panel can render the
# full trail (mention → offer → credential → connection → cascade).
# ---------------------------------------------------------------------------


_PROACTIVE_OFFER_LINK_WINDOW = timedelta(minutes=30)


async def _find_recent_proactive_offer(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    prompted_by_person: str | None,
    until: datetime,
    window: timedelta = _PROACTIVE_OFFER_LINK_WINDOW,
) -> dict[str, Any] | None:
    """Return the most-recent ``emit_proactive_offer`` from this person, if any.

    Scans the ledger for the latest matching offer within ``window`` of
    ``until``. Returns the args dict (or None). Used by the credential-DM
    flow to stitch the offer → credential trail.
    """
    if prompted_by_person is None:
        return None
    rows = await ledger.fetch(company_id, until_ts=until)
    threshold = until - window
    best: dict[str, Any] | None = None
    best_ts: datetime | None = None
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_proactive_offer":
            continue
        args = payload.get("args", {})
        if args.get("prompted_by_person") != prompted_by_person:
            continue
        if r["ts"] < threshold:
            continue
        if best_ts is None or r["ts"] > best_ts:
            best = args
            best_ts = r["ts"]
    return best


async def link_credential_to_proactive_offer(
    ledger: Ledger | InMemoryLedger,
    *,
    company_id: UUID,
    credential_correlation_id: str,
    prompted_by_person: str | None,
    now: datetime,
) -> dict[str, Any] | None:
    """Write a memory_written link entry tying a credential to its proactive offer.

    Returns the offer args (with the new ``correlation_id`` attached) or
    None if no recent offer was found. The link entry's tag set lets the
    dashboard reconstruct ``mention → offer → credential → connection``
    in a single ledger query.
    """
    offer = await _find_recent_proactive_offer(
        ledger, company_id, prompted_by_person=prompted_by_person, until=now,
    )
    if offer is None:
        return None
    link_id = str(uuid4())
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": link_id,
            "reason": "credential linked to proactive offer",
            "proposed_by": "credential_in_dm_flow",
        },
        execute_fn=lambda: {
            "tool": "emit_memory_written",
            "args": {
                "memory_id": link_id,
                "content": "proactive_offer_credential_link",
                "correlation_id": credential_correlation_id,
                "offer_id": offer.get("offer_id"),
                "archetype": offer.get("archetype"),
                "channel_id": offer.get("channel_id"),
                "tags": [
                    "proactive_offer_credential_link",
                    f"offer:{offer.get('offer_id')}",
                    f"correlation_id:{credential_correlation_id}",
                    f"archetype:{offer.get('archetype')}",
                ],
            },
            "result_ref": link_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "link_logged", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "credential linked to proactive offer",
        },
        timestamp=now,
        quadrant="active_deterministic",
    )
    return {**offer, "correlation_id": credential_correlation_id}


async def credential_in_dm_with_offer_link(
    flow: "CredentialInDmFlow",
    event: InfraEvent,
    *,
    cascade: Any | None = None,
) -> dict[str, Any] | None:
    """Run ``CredentialInDmFlow.on_dm`` and link to a recent proactive offer.

    Wraps ``on_dm`` and, on success:
      1. Looks up a recent ``emit_proactive_offer`` from the same person.
      2. Writes the link entry (``proactive_offer_credential_link``).
      3. Optionally fires ``MedallionCascade.run`` for the new source.

    Returns ``{correlation_id, linked_offer, cascade_summary}`` or None
    if the inbound DM didn't carry a recognized credential URI.
    """
    cid = await flow.on_dm(event)
    if cid is None:
        return None
    linked = await link_credential_to_proactive_offer(
        flow.builder.ledger,
        company_id=event.company_id,
        credential_correlation_id=str(cid),
        prompted_by_person=event.person_id,
        now=event.ts,
    )
    cascade_summary: dict[str, Any] | None = None
    if cascade is not None:
        source_id = flow.builder.get_source_id(str(cid))
        if source_id is not None:
            proposal = flow.builder.get_proposal(str(cid))
            raw_uri = (
                str(proposal.proposed_uri)
                if proposal is not None
                else f"unknown://source/{source_id}"
            )
            # Scrubbed credential URIs (e.g. ``postgres://[REDACTED]@...``)
            # are not parseable by ``urllib.parse`` due to the bracketed
            # placeholder. Substitute a parseable scheme-only URI for the
            # bronze sample read while keeping the original on the proposal
            # for trace fidelity. Bronze with empty bytes still produces a
            # deterministic profile (Triad C2).
            cascade_uri = raw_uri
            if "[REDACTED]" in raw_uri:
                cascade_uri = f"redacted://source/{source_id}"
            cascade_summary = await cascade.cascade(
                company_id=event.company_id,
                source_id=source_id,
                uri=cascade_uri,
            )
    return {
        "correlation_id": str(cid),
        "linked_offer": linked,
        "cascade_summary": cascade_summary,
    }


__all__ = [
    "CredentialInDmFlow",
    "credential_in_dm_with_offer_link",
    "link_credential_to_proactive_offer",
]
