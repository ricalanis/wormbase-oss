"""High-level admin write actions for the worm-core HTTP write API.

Each function in this module accepts a ``Ledger | InMemoryLedger`` (any
object exposing the canonical ``write(**)`` async method), constructs a
full propose/execute/verify/resolve cycle, and calls ``ledger.write``.

The module is the single boundary between "Pydantic payload class" and
"hash-chained ledger entry sequence" for dashboard-driven admin writes.
A3.5 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``
removes the previous demo-seam pattern (``INSERT INTO ledger`` without
``seq``/``hash``/``quadrant``) by routing every dashboard write through
this module.

Style mirrors ``apps/channel-adapter/src/wormbase_channel_adapter/writer.py``
and ``apps/voice-agent/src/wormbase_voice_agent/audit.py``: build and
validate the canonical Pydantic payload up front (fail fast before
touching the ledger), then call ``ledger.write`` with closures that
return the four PEVR bodies.

Quadrant: ``active_deterministic`` — the dashboard is admin-driven and
deterministic. The verify step Pydantic-instantiates the payload again
to make the chain self-checking — if the payload class drifts away from
what the API accepts, verify fails and the transaction rolls back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import (
    AgentGrantPayload,
    AgentMetadataUpdatedPayload,
    AgentRegisteredPayload,
    CatalogColumnSpec,
    CatalogDriftAcknowledgedPayload,
    CatalogDriftRejectedPayload,
    CatalogTableImportedPayload,
    ColumnClassificationConfirmedPayload,
    ColumnClassificationRejectedPayload,
    ConceptConfirmedPayload,
    ConceptProposedPayload,
    DecisionRecordedPayload,
    DomainRoleAssignedPayload,
    EntityStitchConfirmedPayload,
    EntityStitchRejectedPayload,
    ExternalCatalogImportedPayload,
    ExternalLineageImportedPayload,
    ExternalMetricImportedPayload,
    IdentityLinkedPayload,
    IdentityUnlinkedPayload,
    InstallCompletedPayload,
    KpiProposedPayload,
    LineageEdgeConfirmedPayload,
    LineageEdgeRejectedPayload,
    MCPCallReceivedPayload,
    PersonArchivedPayload,
    PersonConfirmedPayload,
    PersonInvitedPayload,
    PersonProposedPayload,
    PositionConfirmedPayload,
    PositionProposedPayload,
    PositionRejectedPayload,
    ProcessMapProposedPayload,
    QualityCheckConfirmedPayload,
    QualityCheckRejectedPayload,
    SchemaImpactConfirmedPayload,
    SchemaImpactRejectedPayload,
    SemanticTypeConfirmedPayload,
    SemanticTypeRejectedPayload,
    ResourceRoleAssignedPayload,
    ResourceRoleProposedPayload,
    RoleAssignedPayload,
    RoleRevokedPayload,
    SemanticGapProposedPayload,
    SetupCompletedPayload,
    SetupModeChosenPayload,
    SetupStepAdvancedPayload,
    SourceCandidatePromotedPayload,
    SourceCandidateRejectedPayload,
    TenantSignupCompletedPayload,
    TenantSignupInitiatedPayload,
)
from wormbase_ledger.write_primitive import WriteResult

# Type alias — anything with the canonical async ``write`` surface works.
LedgerLike = Ledger | InMemoryLedger | Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pevr(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    target_kind: str,
    ref_id: UUID,
    reason: str,
    proposed_by: str,
    tool: str,
    args: dict[str, Any],
    result_ref: str,
    payload_cls: type,
    rationale: str,
):
    """Build the four PEVR closures and return the awaitable from ``ledger.write``.

    The verify step re-instantiates the payload via ``payload_cls(**args)``
    so any drift between the API surface and the canonical payload class
    fails the verify check (the surrounding write_primitive transaction
    rolls back).
    """

    def _verify(_exec_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            payload_cls(**args)
            return {
                "checks": [{"name": f"{tool}_payload_valid", "ok": True}],
                "passed": True,
            }
        except Exception as exc:
            return {
                "checks": [
                    {
                        "name": f"{tool}_payload_valid",
                        "ok": False,
                        "error": str(exc),
                    }
                ],
                "passed": False,
            }

    return ledger.write(
        company_id=company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": str(ref_id),
            "reason": reason,
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args,
            "result_ref": result_ref,
        },
        verify_fn=_verify,
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": rationale,
        },
        quadrant="active_deterministic",
    )


# ---------------------------------------------------------------------------
# Person lifecycle
# ---------------------------------------------------------------------------


async def propose_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID | None = None,
    tenant_id: UUID | None = None,
    name: str,
    email: str | None,
    platform: str,
    platform_user_id: str,
    position: str | None,
    proposed_by: str,
) -> tuple[UUID, WriteResult]:
    """Propose a new Person via emit_person_proposed.

    Returns ``(person_id, WriteResult)`` so callers can surface the new
    person id back to the dashboard. ``person_id`` is generated if not
    supplied; ``tenant_id`` defaults to ``company_id`` when omitted.
    """
    pid = person_id or uuid4()
    tid = tenant_id or company_id

    payload = PersonProposedPayload(
        person_id=pid,
        tenant_id=tid,
        name=name,
        email=email,
        platform=platform,
        platform_user_id=platform_user_id,
        proposed_by=proposed_by,
        position=position,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="person_proposed",
        ref_id=pid,
        reason=f"propose person {name!r} on {platform}",
        proposed_by=proposed_by,
        tool=f"emit_{PersonProposedPayload.kind}",
        args=args,
        result_ref=str(pid),
        payload_cls=PersonProposedPayload,
        rationale="person proposed via dashboard API",
    )
    return pid, result


async def confirm_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    confirmed_by: UUID,
) -> WriteResult:
    """Confirm a proposed Person via emit_person_confirmed."""
    payload = PersonConfirmedPayload(
        person_id=person_id,
        confirmed_by=confirmed_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="person_confirmed",
        ref_id=person_id,
        reason=f"confirm person {person_id}",
        proposed_by=str(confirmed_by),
        tool=f"emit_{PersonConfirmedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=PersonConfirmedPayload,
        rationale="person confirmed via dashboard API",
    )


async def archive_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    archived_by: UUID,
    reason: str,
) -> WriteResult:
    """Archive a Person via emit_person_archived."""
    payload = PersonArchivedPayload(
        person_id=person_id,
        archived_by=archived_by,
        reason=reason,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="person_archived",
        ref_id=person_id,
        reason=f"archive person {person_id}: {reason}",
        proposed_by=str(archived_by),
        tool=f"emit_{PersonArchivedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=PersonArchivedPayload,
        rationale="person archived via dashboard API",
    )


async def propose_position(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    position: str,
    confidence: float,
    signals: tuple[str, ...] = (),
    proposed_by: str = "worm",
) -> WriteResult:
    """Worm-inferred position proposal — Wave B.5 G.4 PEVR cycle.

    Backs ``PositionInferenceReactivity`` (and any admin-facing API that
    wants to fast-path a position guess for review). The companion
    confirm-step is ``emit_position_assigned`` (admin override path).

    Per Doctrine Addendum 2 §E this is the propose-step kind for
    position inference; the projection fold updates
    ``state["persons"][pid]["position"]`` once resolve(keep) lands.
    """
    payload = PositionProposedPayload(
        person_id=person_id,
        position=position,
        confidence=confidence,
        signals=signals,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="position_proposed",
        ref_id=person_id,
        reason=(
            f"propose position {position!r} for person {person_id} "
            f"(confidence={confidence:.2f})"
        ),
        proposed_by=proposed_by,
        tool=f"emit_{PositionProposedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=PositionProposedPayload,
        rationale="position proposed via signal scoring",
    )


async def confirm_position_proposal(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    position: str,
    confirmed_by: UUID,
) -> WriteResult:
    """Admin confirmation of a worm-proposed position — Wave H Phase 2 Task 2C.

    Backs the ``/people/proposals`` queue surface. Pairs with
    ``propose_position`` (Wave B.5 G.4): the worm emits an
    ``emit_position_proposed`` envelope when its chat-signal scoring
    crosses threshold; the admin queue surfaces the proposal for review;
    a confirm or reject click writes the corresponding admin-review
    entry. The fold of ``emit_position_confirmed`` is a no-op (the
    optimistic ``position`` write landed at propose time); the entry
    serves as the audit anchor and the projection's
    ``position_review_status`` source.
    """
    payload = PositionConfirmedPayload(
        person_id=person_id,
        position=position,
        confirmed_by=confirmed_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="position_confirmed",
        ref_id=person_id,
        reason=(
            f"confirm position {position!r} for person {person_id}"
        ),
        proposed_by=str(confirmed_by),
        tool=f"emit_{PositionConfirmedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=PositionConfirmedPayload,
        rationale="position proposal confirmed via dashboard API",
    )


async def reject_position_proposal(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    position: str,
    rejected_by: UUID,
    reason: str | None = None,
) -> WriteResult:
    """Admin rejection of a worm-proposed position — Wave H Phase 2 Task 2C.

    Companion to ``confirm_position_proposal``. After PEVR resolve(keep),
    the projection clears the optimistic ``position`` field on the Person
    row when the current value matches ``position`` (latest-wins guard),
    freeing the Reactivity's dedup gate so a richer-signal proposal can
    follow once more chatter accumulates. ``reason`` is optional and
    surfaced to the trace UI for explainability.
    """
    payload = PositionRejectedPayload(
        person_id=person_id,
        position=position,
        rejected_by=rejected_by,
        reason=reason,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="position_rejected",
        ref_id=person_id,
        reason=(
            f"reject position {position!r} for person {person_id}"
            + (f": {reason}" if reason else "")
        ),
        proposed_by=str(rejected_by),
        tool=f"emit_{PositionRejectedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=PositionRejectedPayload,
        rationale="position proposal rejected via dashboard API",
    )


async def propose_resource_role(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    resource_id: UUID,
    role: str,
    confidence: float,
    signals: tuple[str, ...] = (),
    proposed_by: UUID,
) -> WriteResult:
    """Worm-inferred resource-role proposal — Wave B.5 G.5 PEVR cycle.

    Backs ``ResourceOwnershipReactivity``: when chatter + data-product
    consumption signals cross threshold for a (person, resource) pair the
    Reactivity emits a ``emit_resource_role_proposed`` envelope through
    this surface. The companion confirm-step is
    ``emit_resource_role_assigned`` (admin override path).

    Per Doctrine Addendum 2 §E this is the propose-step kind for resource
    ownership inference; the projection fold writes a row into
    ``state["roles"]`` with ``facet='resource'`` once resolve(keep)
    lands. ``proposed_by`` is a UUID (the worm Person id, or the admin's
    id if a human triggered the proposal) — tighter than the free-form
    ``str`` used by ``propose_person`` because the resource-role propose
    step always has a resolvable identity behind it.
    """
    payload = ResourceRoleProposedPayload(
        person_id=person_id,
        resource_id=resource_id,
        role=role,
        confidence=confidence,
        signals=signals,
        proposed_by=proposed_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="resource_role_proposed",
        ref_id=resource_id,
        reason=(
            f"propose resource role {role!r} on resource {resource_id} "
            f"for person {person_id} (confidence={confidence:.2f})"
        ),
        proposed_by=str(proposed_by),
        tool=f"emit_{ResourceRoleProposedPayload.kind}",
        args=args,
        result_ref=str(resource_id),
        payload_cls=ResourceRoleProposedPayload,
        rationale="resource role proposed via chatter signal aggregation",
    )


async def bulk_confirm_persons(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_ids: list[UUID],
    confirmed_by: UUID,
) -> dict[str, Any]:
    """Confirm a batch of proposed Persons in a single API request.

    W2.A6 of ``docs/superpowers/plans/2026-04-28-production-hardening.md``.

    Architectural shape mirrors ``merge_persons``: the orchestrator runs
    one *independent* PEVR cycle per Person via ``confirm_person``, so
    the audit trail records each confirmation as its own four-entry
    ledger fold (``propose → execute → verify → resolve``). Bulk
    semantics live at the API boundary, not in the ledger payloads —
    each row is independently replayable.

    Atomicity contract: this function is "all-or-nothing on the wire."
    If any single ``confirm_person`` raises (validation drift, hash-chain
    failure), the orchestrator re-raises immediately and the caller
    sees the partial-batch error. The dashboard surface treats the
    transaction as atomic by re-fetching the roster on success and
    surfacing the failure message on any error.

    Each ``confirm_person`` call writes 4 ledger entries; for N input
    person_ids the batch produces 4N entries total. Returns
    ``{confirmed_count, person_ids, entry_ids}``.

    Raises ``ValueError`` if ``person_ids`` is empty (a no-op batch is a
    client bug, not a silent success). Duplicate ids are accepted at the
    API layer but de-duplicated here so we don't write the same
    confirmation twice.
    """
    if not person_ids:
        raise ValueError("person_ids must not be empty")

    # Preserve order while de-duplicating — iteration order is the
    # confirmation order, which surfaces in the entry_ids tuple.
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for pid in person_ids:
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)

    entry_ids: list[str] = []
    confirmed: list[str] = []
    for pid in ordered:
        result = await confirm_person(
            ledger,
            company_id,
            person_id=pid,
            confirmed_by=confirmed_by,
        )
        entry_ids.extend(str(eid) for eid in result.entry_ids)
        confirmed.append(str(pid))

    return {
        "confirmed_count": len(confirmed),
        "person_ids": confirmed,
        "entry_ids": entry_ids,
    }


# ---------------------------------------------------------------------------
# Identity link / unlink
# ---------------------------------------------------------------------------


async def link_identity(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
    linked_by: UUID,
) -> WriteResult:
    """Attach a {platform, platform_user_id} to an existing Person."""
    payload = IdentityLinkedPayload(
        person_id=person_id,
        platform=platform,
        platform_user_id=platform_user_id,
        linked_by=linked_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="identity_linked",
        ref_id=person_id,
        reason=f"link {platform}/{platform_user_id} to person {person_id}",
        proposed_by=str(linked_by),
        tool=f"emit_{IdentityLinkedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=IdentityLinkedPayload,
        rationale="identity linked via dashboard API",
    )


async def unlink_identity(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
    unlinked_by: UUID,
) -> WriteResult:
    """Detach a {platform, platform_user_id} from a Person."""
    payload = IdentityUnlinkedPayload(
        person_id=person_id,
        platform=platform,
        platform_user_id=platform_user_id,
        unlinked_by=unlinked_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="identity_unlinked",
        ref_id=person_id,
        reason=f"unlink {platform}/{platform_user_id} from person {person_id}",
        proposed_by=str(unlinked_by),
        tool=f"emit_{IdentityUnlinkedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=IdentityUnlinkedPayload,
        rationale="identity unlinked via dashboard API",
    )


# ---------------------------------------------------------------------------
# Role grants — three facets (tenancy / domain / resource) + tenancy revoke
# ---------------------------------------------------------------------------


async def grant_tenancy_role(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    role: str,
    granted_by: UUID,
) -> WriteResult:
    """Grant a tenancy-facet role (installer / admin / member / observer)."""
    payload = RoleAssignedPayload(
        person_id=person_id,
        role=role,
        granted_by=granted_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="role_assigned",
        ref_id=person_id,
        reason=f"grant tenancy.{role} to person {person_id}",
        proposed_by=str(granted_by),
        tool=f"emit_{RoleAssignedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=RoleAssignedPayload,
        rationale="tenancy role granted via dashboard API",
    )


async def grant_domain_role(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    domain_id: UUID,
    role: str,
    granted_by: UUID,
) -> WriteResult:
    """Grant a domain-facet role (owner / contributor) scoped to a domain."""
    payload = DomainRoleAssignedPayload(
        person_id=person_id,
        domain_id=domain_id,
        role=role,
        granted_by=granted_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="domain_role_assigned",
        ref_id=person_id,
        reason=f"grant domain.{role} on {domain_id} to person {person_id}",
        proposed_by=str(granted_by),
        tool=f"emit_{DomainRoleAssignedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=DomainRoleAssignedPayload,
        rationale="domain role granted via dashboard API",
    )


async def grant_resource_role(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    resource_id: UUID,
    resource_type: str,
    role: str,
    granted_by: UUID,
) -> WriteResult:
    """Grant a resource-facet role (maintainer / contributor) scoped to a resource."""
    payload = ResourceRoleAssignedPayload(
        person_id=person_id,
        resource_id=resource_id,
        resource_type=resource_type,
        role=role,
        granted_by=granted_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="resource_role_assigned",
        ref_id=person_id,
        reason=(
            f"grant resource.{role} on {resource_type}/{resource_id} "
            f"to person {person_id}"
        ),
        proposed_by=str(granted_by),
        tool=f"emit_{ResourceRoleAssignedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=ResourceRoleAssignedPayload,
        rationale="resource role granted via dashboard API",
    )


async def revoke_tenancy_role(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
    role: str,
    revoked_by: UUID,
) -> WriteResult:
    """Revoke a tenancy-facet role grant for (person_id, role)."""
    payload = RoleRevokedPayload(
        person_id=person_id,
        role=role,
        revoked_by=revoked_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="role_revoked",
        ref_id=person_id,
        reason=f"revoke tenancy.{role} from person {person_id}",
        proposed_by=str(revoked_by),
        tool=f"emit_{RoleRevokedPayload.kind}",
        args=args,
        result_ref=str(person_id),
        payload_cls=RoleRevokedPayload,
        rationale="tenancy role revoked via dashboard API",
    )


# ---------------------------------------------------------------------------
# Identity merge / split — A6
# ---------------------------------------------------------------------------


async def _current_identities_for_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    person_id: UUID,
) -> list[tuple[str, str]]:
    """Fold the ledger to the current identity set for ``person_id``.

    Walks the company's ledger entries in seq order and folds the canonical
    identity-affecting execute payloads:

      * ``emit_person_proposed`` — adds ``(platform, platform_user_id)`` if
        the row's ``person_id`` matches.
      * ``emit_identity_linked`` — adds ``(platform, platform_user_id)``.
      * ``emit_identity_unlinked`` — removes ``(platform, platform_user_id)``.

    Order matters: a sequence of link → unlink → link MUST resolve to
    "linked" (the identity is currently attached). The fold uses a dict
    keyed by ``(platform, platform_user_id)`` and toggles membership;
    re-linking after unlink correctly restores the identity.

    Returns the identity tuples in stable order matching the order the
    most recent ``link`` (or ``proposed``) entry landed for each tuple.
    """
    rows = await ledger.fetch(company_id)
    # Use a dict to preserve insertion order while allowing unlink/relink
    # cycles. value=None means "currently unlinked"; presence of the key
    # means we've seen it but the *value* tracks the current attachment.
    state: dict[tuple[str, str], bool] = {}
    pid_str = str(person_id)
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if args.get("person_id") != pid_str:
            # The fold is scoped to one person — skip entries for others.
            continue
        if tool == "emit_person_proposed":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid:
                state[(platform, puid)] = True
        elif tool == "emit_identity_linked":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid:
                # Re-linking after unlink correctly toggles back to True.
                state[(platform, puid)] = True
        elif tool == "emit_identity_unlinked":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid and (platform, puid) in state:
                state[(platform, puid)] = False
    return [k for k, attached in state.items() if attached]


async def merge_persons(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    keeper_id: UUID,
    mergee_id: UUID,
    merged_by: UUID,
) -> dict[str, Any]:
    """Merge ``mergee_id`` into ``keeper_id``.

    Architectural note: this is a *sequence* of independent PEVR cycles,
    not one batched cycle. Each ``unlink_identity`` / ``link_identity`` /
    ``archive_person`` call is its own atomic 4-entry write. If a write
    in the middle fails, the partial merge is visible in the audit log
    and the admin can retry the remainder. This is intentional — see
    A6 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``.

    1. Fold the ledger to the mergee's current identities.
    2. For each identity:
         - Skip if the keeper already holds the same ``(platform,
           platform_user_id)`` (no double-link). Still write the unlink
           on the mergee side so the audit trail is complete.
         - Otherwise: ``unlink_identity`` from mergee, then
           ``link_identity`` to keeper.
    3. Archive the mergee with reason ``f"merged_into:{keeper_id}"``.

    Returns ``{keeper_id, mergee_id, identities_moved, entry_ids}``.
    Raises ``ValueError`` if ``keeper_id == mergee_id``.
    """
    if keeper_id == mergee_id:
        raise ValueError("keeper_id and mergee_id must differ")

    mergee_identities = await _current_identities_for_person(
        ledger, company_id, person_id=mergee_id,
    )
    keeper_identities = set(
        await _current_identities_for_person(
            ledger, company_id, person_id=keeper_id,
        )
    )

    entry_ids: list[str] = []
    moved = 0
    for platform, platform_user_id in mergee_identities:
        unlink_result = await unlink_identity(
            ledger,
            company_id,
            person_id=mergee_id,
            platform=platform,
            platform_user_id=platform_user_id,
            unlinked_by=merged_by,
        )
        entry_ids.extend(str(eid) for eid in unlink_result.entry_ids)

        if (platform, platform_user_id) in keeper_identities:
            # Keeper already has it — skip the link to avoid double-link.
            # The unlink on the mergee side stands so the audit trail
            # records the duplicate identity moving off mergee.
            continue

        link_result = await link_identity(
            ledger,
            company_id,
            person_id=keeper_id,
            platform=platform,
            platform_user_id=platform_user_id,
            linked_by=merged_by,
        )
        entry_ids.extend(str(eid) for eid in link_result.entry_ids)
        keeper_identities.add((platform, platform_user_id))
        moved += 1

    archive_result = await archive_person(
        ledger,
        company_id,
        person_id=mergee_id,
        archived_by=merged_by,
        reason=f"merged_into:{keeper_id}",
    )
    entry_ids.extend(str(eid) for eid in archive_result.entry_ids)

    return {
        "keeper_id": str(keeper_id),
        "mergee_id": str(mergee_id),
        "identities_moved": moved,
        "entry_ids": entry_ids,
    }


async def split_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    source_person_id: UUID,
    new_person_name: str,
    new_person_email: str | None,
    new_person_position: str | None,
    identities_to_move: list[tuple[str, str]] | list[dict[str, str]],
    split_by: UUID,
) -> dict[str, Any]:
    """Split ``source_person_id`` by extracting ``identities_to_move`` into a new Person.

    Each item in ``identities_to_move`` is either ``(platform, platform_user_id)``
    or ``{"platform": ..., "platform_user_id": ...}``.

    1. Generate ``new_person_id``.
    2. Use the FIRST identity as the seed for ``propose_person`` (the
       canonical payload requires platform + platform_user_id) — that
       step links the seed identity to the new Person automatically.
    3. Unlink the seed identity from the source.
    4. For each remaining identity: unlink from source, link to new.

    Returns ``{source_person_id, new_person_id, identities_moved,
    entry_ids}``. Raises ``ValueError`` if ``identities_to_move`` is empty.
    """
    if not identities_to_move:
        raise ValueError("identities_to_move must not be empty")

    # Normalise to list[tuple[str, str]].
    normalised: list[tuple[str, str]] = []
    for item in identities_to_move:
        if isinstance(item, dict):
            platform = item.get("platform")
            puid = item.get("platform_user_id")
            if not platform or not puid:
                raise ValueError(
                    "every identity must carry platform and platform_user_id",
                )
            normalised.append((str(platform), str(puid)))
        else:
            platform, puid = item
            normalised.append((str(platform), str(puid)))

    seed_platform, seed_puid = normalised[0]
    new_person_id = uuid4()
    entry_ids: list[str] = []

    # Step 1+2: propose the new Person seeded with the first identity.
    pid, propose_result = await propose_person(
        ledger,
        company_id,
        person_id=new_person_id,
        tenant_id=company_id,
        name=new_person_name,
        email=new_person_email,
        platform=seed_platform,
        platform_user_id=seed_puid,
        position=new_person_position,
        proposed_by=f"split:{split_by}",
    )
    entry_ids.extend(str(eid) for eid in propose_result.entry_ids)

    # Step 3: unlink the seed from the source. The propose step above
    # already linked the seed to the new Person.
    seed_unlink = await unlink_identity(
        ledger,
        company_id,
        person_id=source_person_id,
        platform=seed_platform,
        platform_user_id=seed_puid,
        unlinked_by=split_by,
    )
    entry_ids.extend(str(eid) for eid in seed_unlink.entry_ids)

    # Step 4: move the rest.
    for platform, puid in normalised[1:]:
        unlink_result = await unlink_identity(
            ledger,
            company_id,
            person_id=source_person_id,
            platform=platform,
            platform_user_id=puid,
            unlinked_by=split_by,
        )
        entry_ids.extend(str(eid) for eid in unlink_result.entry_ids)
        link_result = await link_identity(
            ledger,
            company_id,
            person_id=new_person_id,
            platform=platform,
            platform_user_id=puid,
            linked_by=split_by,
        )
        entry_ids.extend(str(eid) for eid in link_result.entry_ids)

    return {
        "source_person_id": str(source_person_id),
        "new_person_id": str(pid),
        "identities_moved": len(normalised),
        "entry_ids": entry_ids,
    }


async def complete_install(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID | None = None,
    platform: str,
    installer_email: str,
    installer_name: str,
    installer_avatar_url: str | None = None,
    platform_user_id: str,
    oauth_grant_ref: str,
    scopes: list[str],
    bot_user_id: str,
) -> dict[str, Any]:
    """Orchestrate the post-OAuth install: create installer Person, grant
    tenancy.installer + tenancy.admin, write emit_install_completed.

    Each step is a full PEVR cycle. The orchestrator:

      1. Generates ``install_id`` and ``installer_person_id`` UUIDs.
      2. Calls ``propose_person`` (writes ``emit_person_proposed``).
      3. Calls ``confirm_person`` (writes ``emit_person_confirmed``); the
         installer self-confirms by convention (no admin exists yet).
      4. Calls ``grant_tenancy_role`` for ``installer`` (self-grant).
      5. Calls ``grant_tenancy_role`` for ``admin``.
      6. Writes ``emit_install_completed``.

    Returns ``{install_id, installer_person_id, entry_ids}``. The
    ``oauth_grant_ref`` MUST already be ``kms://...`` or ``vault://...``;
    the underlying ``InstallCompletedPayload`` validator rejects any other
    prefix so cleartext bearer tokens never reach the ledger.
    """
    if not installer_email:
        raise ValueError("installer_email is required for complete_install")
    if not installer_name:
        raise ValueError("installer_name is required for complete_install")
    if not platform_user_id:
        raise ValueError("platform_user_id is required for complete_install")
    if not oauth_grant_ref:
        raise ValueError("oauth_grant_ref is required for complete_install")
    if not bot_user_id:
        raise ValueError("bot_user_id is required for complete_install")

    install_id = uuid4()
    installer_person_id = uuid4()
    tid = tenant_id or company_id

    entry_ids: list[str] = []

    # Step 1+2: propose installer Person.
    _, propose_result = await propose_person(
        ledger,
        company_id,
        person_id=installer_person_id,
        tenant_id=tid,
        name=installer_name,
        email=installer_email,
        platform=platform,
        platform_user_id=platform_user_id,
        position=None,
        proposed_by="onboarding-installer-flow",
    )
    entry_ids.extend(str(eid) for eid in propose_result.entry_ids)

    # Step 3: installer self-confirms (no admin exists yet).
    confirm_result = await confirm_person(
        ledger,
        company_id,
        person_id=installer_person_id,
        confirmed_by=installer_person_id,
    )
    entry_ids.extend(str(eid) for eid in confirm_result.entry_ids)

    # Step 4: grant tenancy.installer (self-grant).
    installer_grant = await grant_tenancy_role(
        ledger,
        company_id,
        person_id=installer_person_id,
        role="installer",
        granted_by=installer_person_id,
    )
    entry_ids.extend(str(eid) for eid in installer_grant.entry_ids)

    # Step 5: grant tenancy.admin.
    admin_grant = await grant_tenancy_role(
        ledger,
        company_id,
        person_id=installer_person_id,
        role="admin",
        granted_by=installer_person_id,
    )
    entry_ids.extend(str(eid) for eid in admin_grant.entry_ids)

    # Step 6: write emit_install_completed. The Pydantic payload class
    # rejects any oauth_grant_ref that isn't kms:// or vault://, so we
    # let it raise — the surrounding handler maps to 4xx.
    payload = InstallCompletedPayload(
        install_id=install_id,
        tenant_id=tid,
        platform=platform,
        installer_person_id=installer_person_id,
        oauth_grant_ref=oauth_grant_ref,
        scopes=list(scopes),
        bot_user_id=bot_user_id,
    )
    args = payload.model_dump(mode="json")

    install_result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="install_completed",
        ref_id=install_id,
        reason=f"install completed for tenant {tid} on {platform}",
        proposed_by=str(installer_person_id),
        tool=f"emit_{InstallCompletedPayload.kind}",
        args=args,
        result_ref=str(install_id),
        payload_cls=InstallCompletedPayload,
        rationale="install completed via onboarding OAuth callback",
    )
    entry_ids.extend(str(eid) for eid in install_result.entry_ids)

    install_result_dict = {
        "install_id": str(install_id),
        "installer_person_id": str(installer_person_id),
        "entry_ids": entry_ids,
    }

    # Step 7: provision the default local lake. Every tenant gets a
    # LocalLakeConnector auto-provisioned at install — bronze + silver +
    # gold visible from minute zero, before any external source connects.
    # See docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md
    # §17 (REVISED 2026-04-27 banner: minimal-friction onboarding).
    lake_result = await provision_local_lake(
        ledger,
        company_id,
        tenant_id=tid,
        installer_person_id=installer_person_id,
    )
    install_result_dict["entry_ids"].extend(lake_result["entry_ids"])
    install_result_dict["local_lake_source_id"] = lake_result["source_id"]

    return install_result_dict


# ---------------------------------------------------------------------------
# Local lake provisioning (Block I of the production-dashboard PRD §17)
# ---------------------------------------------------------------------------


async def provision_local_lake(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID,
    installer_person_id: UUID,
    include_default_csv_fixture: bool = False,
) -> dict[str, Any]:
    """Provision the default local lake — bronze + silver + gold from minute zero.

    Every tenant gets a ``LocalLakeConnector`` (see
    :mod:`wormbase_connectors.local_lake`) auto-provisioned at install.
    The lake plays all three medallion layers backed by the tenant's
    own ledger projections + a tenant-scoped local filesystem; no
    external source is needed for the worm to be useful.

    The orchestrator writes the canonical 4-stage source-lifecycle
    sequence (proposed → confirmed → connected → profiled) as four PEVR
    cycles via the existing ``SourceBuilder`` primitive, totalling 16
    ledger entries. The installer is recorded as both proposer and
    confirmer because they are the only Person on the tenant at install
    time.

    When ``include_default_csv_fixture`` is true, the cursed-CSV
    fixture (``fixtures/cursed_finance_export.csv``) is also cascaded
    into the bronze tier — bronze + silver + gold + KPI proposal
    entries land against an additional source. This wires Demo-Day
    PRD §7 P4 into the install arc Beat 2-3 promise. The default is
    False to keep the lake-shell entry count stable for existing
    callers; the install-arc orchestrator (sister scope) opts in
    explicitly. If the fixture file is missing on disk while opted
    in, the call silently skips the cascade and leaves the lake
    shell-only — the install path stays usable in production deploys
    that don't ship demo seeds.

    Args:
        ledger: the ledger handle.
        company_id: the tenant's ledger company id.
        tenant_id: the dashboard's tenant uuid (same value as
            ``company_id`` in the canonical mapping).
        installer_person_id: the tenant's installer; recorded as
            ``proposed_by`` / ``confirmed_by`` / ``maintainer`` for
            the lake source row.
        include_default_csv_fixture: when True (default), also cascade
            the cursed-CSV fixture through bronze→silver→gold so the
            install arc has visible content from the first beat.

    Returns ``{source_id, entry_ids}`` — the source uuid (the lake
    shell's source id) and the entry ids written. When the cursed CSV
    cascade ran, ``cursed_csv_source_id`` and the cascade's summary
    are also included.
    """
    # Local imports keep the write_actions surface free of connector +
    # source-builder cycles. The connector is pure-Python so import is
    # cheap; the source-builder pulls in the canonical PEVR primitive.
    from wormbase_connectors.local_lake import LocalLakeConnector
    from wormbase_connectors.types import SecretBundle

    from wormbase_core.source_builder import (
        SourceBuilder,
        SourceProposal,
    )

    # Discover + profile the canonical resource catalog so the
    # source_profiled entry carries an honest schema_hash + column_count.
    connector = LocalLakeConnector()
    handle = await connector.authenticate(
        SecretBundle(payload={"tenant_id": str(tenant_id)}),
    )
    proposals = await connector.discover(handle)
    # Aggregate schema hash across the seven resources — the lake source
    # row is one entry, but it covers seven medallion tables. We hash
    # the ordered (resource_id, schema_hash) pairs into a single digest
    # the source-profiled entry can carry.
    import hashlib as _hashlib

    column_total = 0
    pair_lines: list[str] = []
    for prop in proposals:
        prof = await connector.profile(handle, prop.resource_id)
        column_total += prof.column_count or 0
        pair_lines.append(f"{prop.resource_id}:{prof.schema_hash}")
    aggregate_schema_hash = _hashlib.sha256(
        "\n".join(pair_lines).encode()
    ).hexdigest()[:16]

    builder = SourceBuilder(ledger)
    proposal = SourceProposal(
        proposed_uri=f"local-lake://{tenant_id}",
        proposed_type="database",
        proposed_domain="general",
        proposed_classification="internal",
        proposed_owner_person_id=installer_person_id,
        added_by_person_id=installer_person_id,
        added_via_flow="provisioned_at_install",
        added_in_response_to=None,
        company_id=company_id,
    )

    # Stage 1: propose.
    cid = await builder.propose(proposal)
    cid_str = str(cid)
    source_id = builder.get_source_id(cid_str)

    # Stage 2: auto-confirm. The installer authored the install action;
    # by completing install they have implicitly confirmed the default
    # lake. domain_id is set to company_id (tenancy-scoped) since no
    # custom domain has been picked yet.
    await builder.confirm(
        cid_str,
        confirmed_by_person_id=installer_person_id,
        domain_id=company_id,
        classification="internal",
    )

    # Stage 3: connected. The connection_ref is the lake's stable
    # tenant-scoped uri — the dashboard / cli inspectors resolve it back
    # to the LocalLakeConnector via the registry.
    await builder.connect(cid_str, connection_ref=f"local-lake://{tenant_id}")

    # Stage 4: profiled. row_count is 0 at install time (the lake is
    # fresh); column_count is the sum across the seven resources;
    # schema_hash is the aggregate digest computed above. profile_ref
    # is the same tenant-scoped uri so the dashboard can drill in.
    await builder.profile(
        cid_str,
        row_count=0,
        column_count=column_total,
        schema_hash=aggregate_schema_hash,
        profile_ref=f"local-lake://{tenant_id}",
    )

    # Reconstruct the entry ids from the ledger fold for the caller's
    # entry_ids list. We fetch the last 16 entries (4 PEVR × 4 entries)
    # for this company; the orchestrator runs as a single in-memory
    # SourceBuilder session so the slice is canonical.
    rows = await ledger.fetch(company_id)
    entry_ids = [str(r["entry_id"]) for r in rows[-16:]]
    rows_after_lake_shell = len(rows)

    result: dict[str, Any] = {
        "source_id": str(source_id) if source_id is not None else "",
        "entry_ids": entry_ids,
    }

    # Optionally cascade the cursed-CSV fixture into the lake's bronze
    # tier. Failure to find the fixture is not an error — production
    # deploys may not ship the demo seed. Failure to import the
    # cascade module is not an error either — keeps the install path
    # tolerant of partial checkouts.
    if include_default_csv_fixture:
        try:
            from wormbase_core.onboarding.default_local_source import (
                cursed_csv_path,
                run_default_local_cascade,
            )

            cursed_csv_path()  # raises FileNotFoundError if missing
        except (FileNotFoundError, ImportError):
            return result

        cursed_summary = await run_default_local_cascade(
            ledger,  # type: ignore[arg-type]
            company_id,
        )
        rows_after_cascade = await ledger.fetch(company_id)
        cascade_entries = [
            str(r["entry_id"])
            for r in rows_after_cascade[rows_after_lake_shell:]
        ]
        result["entry_ids"].extend(cascade_entries)
        result["cursed_csv_source_id"] = cursed_summary["source_id"]
        result["cursed_csv_summary"] = cursed_summary

    return result


# ---------------------------------------------------------------------------
# Setup mode + progress (Block G of the production-dashboard PRD §17)
# ---------------------------------------------------------------------------


async def set_setup_mode(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID | None = None,
    mode: str,
    chosen_by_person_id: UUID,
) -> WriteResult:
    """Set the tenant's setup mode (wizard | bot) via emit_setup_mode_chosen.

    Tenant-level — the projection stamps every install row for the tenant.
    Admins can switch later via /settings (G6); the projection always
    reflects the latest choice.
    """
    tid = tenant_id or company_id
    payload = SetupModeChosenPayload(
        tenant_id=tid,
        mode=mode,  # type: ignore[arg-type]
        chosen_by_person_id=chosen_by_person_id,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="setup_mode_chosen",
        ref_id=tid,
        reason=f"setup_mode chosen: {mode} by person {chosen_by_person_id}",
        proposed_by=str(chosen_by_person_id),
        tool=f"emit_{SetupModeChosenPayload.kind}",
        args=args,
        result_ref=str(tid),
        payload_cls=SetupModeChosenPayload,
        rationale=f"setup mode set to {mode} via dashboard API",
    )


async def complete_setup(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID | None = None,
    completed_at: datetime | None = None,
) -> WriteResult:
    """Mark the tenant's setup as complete via emit_setup_completed.

    Written by the wizard's last form submit (T3 Done) or by the bot
    loop's terminal YAML step. ``completed_at`` defaults to now() in UTC
    so callers can omit it.
    """
    tid = tenant_id or company_id
    ts = completed_at or datetime.now(UTC)
    payload = SetupCompletedPayload(
        tenant_id=tid,
        completed_at=ts,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="setup_completed",
        ref_id=tid,
        reason="setup completed",
        proposed_by="setup-orchestrator",
        tool=f"emit_{SetupCompletedPayload.kind}",
        args=args,
        result_ref=str(tid),
        payload_cls=SetupCompletedPayload,
        rationale="setup completed via dashboard API or bot loop",
    )


async def advance_setup_step(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID | None = None,
    step_id: str,
    advanced_by_person_id: UUID | None = None,
) -> WriteResult:
    """Advance the bot-path setup cursor via emit_setup_step_advanced.

    Written by ``SetupConversationLoop`` (G5) after parsing each
    installer DM reply. ``advanced_by_person_id`` is None when the worm
    advances on its own (timeout fallback).
    """
    tid = tenant_id or company_id
    payload = SetupStepAdvancedPayload(
        tenant_id=tid,
        step_id=step_id,
        advanced_by_person_id=advanced_by_person_id,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="setup_step_advanced",
        ref_id=tid,
        reason=f"setup step advanced to {step_id}",
        proposed_by=str(advanced_by_person_id or "worm"),
        tool=f"emit_{SetupStepAdvancedPayload.kind}",
        args=args,
        result_ref=str(tid),
        payload_cls=SetupStepAdvancedPayload,
        rationale=f"bot setup advanced to step {step_id}",
    )


# ---------------------------------------------------------------------------
# MCP integration (Phase 0 spike — 2026-04-27 mcp-integration spec §10.1)
# ---------------------------------------------------------------------------


async def record_mcp_call(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    mcp_call_id: UUID | None = None,
    tenant_id: UUID | None = None,
    caller_person_id: UUID | None = None,
    tool_name: str,
    args_hash: str,
    client_ua: str | None = None,
    started_at: datetime,
    outcome: str,
    latency_ms: int,
) -> tuple[UUID, WriteResult]:
    """Record one external MCP tool invocation as a full PEVR cycle.

    Mirrors ``complete_install`` shape: build + validate the canonical
    Pydantic payload up front, then drive the four-stage propose/execute/
    verify/resolve cycle via ``_pevr``. The verify step re-instantiates
    the payload class so any drift between the worm-core MCP server and
    the canonical payload class fails the verify check (and the
    surrounding write_primitive transaction rolls back).

    Returns ``(mcp_call_id, WriteResult)`` so the MCP server can include
    the call id in its response (for client-side cross-referencing
    against ``query_audit_trail`` / ``projection_mcp_calls``).

    Quadrant: ``active_deterministic`` — the call already happened
    (synchronous round-trip with the external MCP client); we are
    auditing it after the fact.
    """
    cid = mcp_call_id or uuid4()
    tid = tenant_id or company_id

    payload = MCPCallReceivedPayload(
        mcp_call_id=cid,
        tenant_id=tid,
        caller_person_id=caller_person_id,
        tool_name=tool_name,
        args_hash=args_hash,
        client_ua=client_ua,
        started_at=started_at,
        outcome=outcome,  # type: ignore[arg-type]
        latency_ms=latency_ms,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="mcp_call_received",
        ref_id=cid,
        reason=(
            f"mcp tool {tool_name!r} invoked "
            f"(outcome={outcome}, latency_ms={latency_ms})"
        ),
        proposed_by=(
            str(caller_person_id) if caller_person_id is not None
            else "mcp-anonymous"
        ),
        tool=f"emit_{MCPCallReceivedPayload.kind}",
        args=args,
        result_ref=str(cid),
        payload_cls=MCPCallReceivedPayload,
        rationale=f"mcp call audited via record_mcp_call ({outcome})",
    )
    return cid, result


# ---------------------------------------------------------------------------
# KPI / decision / process orchestrators (W2.A7)
#
# Three small admin-driven write orchestrators backing the dashboard's
# /kpis, /decisions, and /processes primary actions. Same _pevr template
# as the Person + Setup orchestrators above; verify rebuilds the payload
# so any drift between the API surface and the canonical Pydantic class
# fails the cycle.
# ---------------------------------------------------------------------------


async def propose_kpi_node(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    kpi_id: UUID | None = None,
    label: str,
    formula: str,
    unit: str = "count",
    source_ids: list[UUID] | None = None,
    owner_position: str | None = None,
    proposed_by: str = "dashboard-admin",
    proposed_at: datetime | None = None,
) -> tuple[UUID, WriteResult]:
    """Propose a KPI tree node via emit_kpi_proposed (W2.A7).

    The dashboard's /kpis tab calls this through the route handler
    ``/api/v1/kpis/propose`` whenever an admin clicks "Propose first KPI"
    or "Propose KPI" on the populated state. The KPI lands as a proposal
    bridge entry; the gold-cascade reader picks it up and threads it into
    the ``emit_kpi_node`` tree on the next refresh.

    ``kpi_id`` is generated if not supplied; ``proposed_at`` defaults to
    now() in UTC. Returns ``(kpi_id, WriteResult)`` so the caller can
    surface the new id back to the dashboard.
    """
    kid = kpi_id or uuid4()
    ts = proposed_at or datetime.now(UTC)

    payload = KpiProposedPayload(
        kpi_id=kid,
        label=label,
        formula=formula,
        source_ids=list(source_ids or []),
        unit=unit,
        owner_position=owner_position,
        proposed_at=ts,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="kpi_proposed",
        ref_id=kid,
        reason=f"propose KPI {label!r} via dashboard",
        proposed_by=proposed_by,
        tool=f"emit_{KpiProposedPayload.kind}",
        args=args,
        result_ref=str(kid),
        payload_cls=KpiProposedPayload,
        rationale="KPI proposed via dashboard admin action",
    )
    return kid, result


async def record_decision(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    decision_id: UUID | None = None,
    decision_text: str,
    channel_id: str,
    decided_by_persons: list[UUID] | None = None,
    evidence_message_ids: list[str] | None = None,
    confidence: float = 0.95,
    decision_at: datetime | None = None,
    proposed_by: str = "dashboard-admin",
) -> tuple[UUID, WriteResult]:
    """Record a decision via emit_decision_recorded (W2.A7).

    Decisions normally auto-extract from chat via ``process_extractor``
    — this orchestrator backs the dashboard's manual "Record decision"
    affordance from /decisions, used when an admin wants to canonicalise
    a decision the worm hasn't yet caught.

    ``confidence`` defaults to 0.95 because admin-recorded decisions are
    explicitly attested rather than heuristic.
    """
    did = decision_id or uuid4()
    ts = decision_at or datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    payload = DecisionRecordedPayload(
        decision_id=did,
        decision_text=decision_text,
        decision_at=ts,
        channel_id=channel_id,
        decided_by_persons=list(decided_by_persons or []),
        evidence_message_ids=list(evidence_message_ids or []),
        confidence=confidence,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=did,
        reason=f"record decision {decision_text[:48]!r} via dashboard",
        proposed_by=proposed_by,
        tool=f"emit_{DecisionRecordedPayload.kind}",
        args=args,
        result_ref=str(did),
        payload_cls=DecisionRecordedPayload,
        rationale="decision recorded via dashboard admin action",
    )
    return did, result


async def propose_process_map(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    process_id: UUID | None = None,
    process_name: str,
    steps: list[dict[str, Any]],
    domain: str = "general",
    confidence: float = 0.95,
    proposed_by: str = "dashboard-admin",
) -> tuple[UUID, WriteResult]:
    """Propose a process map via emit_process_map_proposed (W2.A7).

    Process maps normally auto-build from chat via ``process_extractor``
    — this orchestrator backs the dashboard's manual ``ProcessMapEditor``
    affordance from /processes, used when an admin wants to author a
    canonical process by hand.

    Each step is a ``{order, actor, action, source_message_id}`` dict
    matching the ``ProcessMapProposedPayload.steps`` shape; admin-authored
    steps may have an empty ``source_message_id``.
    """
    pid = process_id or uuid4()

    payload = ProcessMapProposedPayload(
        process_id=pid,
        process_name=process_name,
        steps=steps,
        domain=domain,
        confidence=confidence,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="process_map_proposed",
        ref_id=pid,
        reason=f"propose process map {process_name!r} via dashboard",
        proposed_by=proposed_by,
        tool=f"emit_{ProcessMapProposedPayload.kind}",
        args=args,
        result_ref=str(pid),
        payload_cls=ProcessMapProposedPayload,
        rationale="process map proposed via dashboard admin action",
    )
    return pid, result


# ---------------------------------------------------------------------------
# Tenant signup (Phase 1 Task 1B.B — multi-tenancy v2 plan)
#
# Pair of writers driving the canonical signup chain. Both Slack OAuth and
# email magic-link flows write the same chain (initiated -> ... ->
# completed). The canonical Pydantic payloads (registered with the kind
# registry) live in wormbase_ledger.entries.
# ---------------------------------------------------------------------------


async def initiate_tenant_signup(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID,
    slug: str,
    display_name: str,
    signup_source: str,
    signup_email: str | None,
    pending_token_hash: str,
) -> WriteResult:
    """Write tenant_signup_initiated.

    Used by:
      - Slack OAuth callback for unknown workspaces (1B.C).
      - Magic-link request endpoint (1B.D).
      - ``wormbase demo seed --demo-tenants`` (1B.G; pairs with completed
        immediately, so projection_tenants jumps from absent to active in
        a single seed batch).
    """
    payload = TenantSignupInitiatedPayload(
        tenant_id=tenant_id,
        slug=slug,
        display_name=display_name,
        signup_source=signup_source,
        signup_email=signup_email,
        pending_token_hash=pending_token_hash,
    )
    args = payload.model_dump(mode="json")
    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="tenant_signup_initiated",
        ref_id=tenant_id,
        reason=f"signup initiated for tenant {slug} via {signup_source}",
        proposed_by="signup-flow",
        tool=f"emit_{TenantSignupInitiatedPayload.kind}",
        args=args,
        result_ref=str(tenant_id),
        payload_cls=TenantSignupInitiatedPayload,
        rationale="canonical signup chain start",
    )


async def complete_tenant_signup(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    tenant_id: UUID,
    signup_source: str,
    assigned_tenant_slug: str,
    signup_email: str | None,
) -> WriteResult:
    """Write tenant_signup_completed.

    Pairs with ``initiate_tenant_signup``. For Slack OAuth: emitted right
    after the install_completed cycle inside ``complete_install``. For
    magic-link: emitted by the confirm endpoint when an evaluator is
    bound to a demo tenant (the assigned_tenant_slug then differs from
    any pending Initiated entry's slug — initiated carries the
    evaluator's email-derived placeholder, completed carries the actual
    demo slug picked by the round-robin policy).
    """
    payload = TenantSignupCompletedPayload(
        tenant_id=tenant_id,
        signup_source=signup_source,
        assigned_tenant_slug=assigned_tenant_slug,
        signup_email=signup_email,
    )
    args = payload.model_dump(mode="json")
    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="tenant_signup_completed",
        ref_id=tenant_id,
        reason=(
            f"signup completed for {assigned_tenant_slug} "
            f"via {signup_source}"
        ),
        proposed_by="signup-flow",
        tool=f"emit_{TenantSignupCompletedPayload.kind}",
        args=args,
        result_ref=str(tenant_id),
        payload_cls=TenantSignupCompletedPayload,
        rationale="canonical signup chain end",
    )


# ---------------------------------------------------------------------------
# v1.1 production-hardening write primitives — 4 endpoints batched.
#
# All four orchestrators back the dashboard server actions whose Wave 3 /
# Wave 3.2 stubs returned an "endpoint v1.1" error when ``WORM_CORE_API_URL``
# could not resolve to a real route. With these four primitives in place
# (and the HTTP routes wired in ``http_api.py``) the stub branches go cold
# and the form-driven flows land real entries.
#
# Pattern:
#   * register_agent       — emits ``agent_registered`` + N ``agent_grant``
#                            (one per domain_read_id, plus one ``model.access``
#                            grant when a budget is supplied).
#   * import_dbt_catalog   — fetches a manifest (https / file://), parses
#                            via ``parse_dbt_manifest``, builds an
#                            upstream_mirror Source, emits
#                            ``external_catalog_imported`` +
#                            ``external_lineage_imported`` per edge, and
#                            wires catalog-mirror Reactivities via
#                            ``wire_catalog_for_source`` (Wave 1 Task 5
#                            cleanup 1a — per-source registration).
#   * import_snowflake_catalog
#                          — same shape as import_dbt_catalog but uses
#                            ``SnowflakeNativeCatalogSource.discover_catalog``;
#                            the Snowflake password / OAuth token comes
#                            via ``CredentialBroker.hold_data_account``
#                            (NEVER in the request body — see CLAUDE.md
#                            security posture).
#   * promote_semantic_gap — looks up a ``semantic_gap_proposed`` ledger
#                            entry by id, validates the entry kind, and
#                            emits ``external_metric_imported`` with
#                            ``caused_by`` linking back to the gap entry.
# ---------------------------------------------------------------------------


# Default model_kind for the optional ``model.access`` grant created when
# an admin supplies a budget at agent-registration time. The admin can
# adjust the model assignment later via the grants surface.
_DEFAULT_MODEL_GRANT_TARGET = "kimi"


async def register_agent(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    agent_id: UUID | None = None,
    external_provider: str,
    display_name: str,
    domain_read_ids: list[UUID] | None = None,
    model_access_budget_usd: str | None = None,
    registered_by: UUID,
) -> tuple[UUID, list[WriteResult]]:
    """Register an external/internal agent + initial set of grants.

    Emits one ``agent_registered`` PEVR cycle followed by:

    * one ``agent_grant`` (``domain.read``, status=active) per
      ``domain_read_ids`` entry, AND
    * one ``agent_grant`` (``model.access``, status=active) carrying
      ``budget_remaining_usd`` when ``model_access_budget_usd`` is
      supplied.

    Returns ``(agent_id, [WriteResult, ...])`` so callers can surface
    the new agent UUID back to the dashboard's redirect target
    (``/people/agents/[id]``). The WriteResults list is the registration
    cycle followed by one per grant in registration order.

    ``external_provider`` is validated against
    ``AgentRegisteredPayload.external_provider`` Literal at the verify
    step — the surrounding write_primitive transaction rolls back on
    drift.
    """
    aid = agent_id or uuid4()
    grants = list(domain_read_ids or [])

    # 1. Emit agent_registered.
    registered_payload = AgentRegisteredPayload(
        agent_id=str(aid),
        external_provider=external_provider,  # type: ignore[arg-type]
        display_name=display_name,
        registered_by=str(registered_by),
    )
    registered_args = registered_payload.model_dump(mode="json")
    results: list[WriteResult] = []
    results.append(
        await _pevr(
            ledger=ledger,
            company_id=company_id,
            target_kind="agent_registered",
            ref_id=aid,
            reason=(
                f"register agent {display_name!r} "
                f"(provider={external_provider})"
            ),
            proposed_by=str(registered_by),
            tool=f"emit_{AgentRegisteredPayload.kind}",
            args=registered_args,
            result_ref=str(aid),
            payload_cls=AgentRegisteredPayload,
            rationale="agent registered via dashboard admin action",
        )
    )

    # 2. One domain.read grant per requested domain id.
    for did in grants:
        grant_payload = AgentGrantPayload(
            agent_id=str(aid),
            grant_kind="domain.read",
            grant_target=str(did),
            status="active",
            granted_by=str(registered_by),
            budget_remaining_usd=None,
        )
        grant_args = grant_payload.model_dump(mode="json")
        results.append(
            await _pevr(
                ledger=ledger,
                company_id=company_id,
                target_kind="agent_grant",
                ref_id=aid,
                reason=f"grant domain.read on {did} to agent {aid}",
                proposed_by=str(registered_by),
                tool=f"emit_{AgentGrantPayload.kind}",
                args=grant_args,
                result_ref=str(aid),
                payload_cls=AgentGrantPayload,
                rationale="domain.read grant from registration flow",
            )
        )

    # 3. Optional model.access grant when a budget was supplied.
    if model_access_budget_usd is not None:
        budget_str = str(model_access_budget_usd).strip()
        if budget_str:
            model_grant_payload = AgentGrantPayload(
                agent_id=str(aid),
                grant_kind="model.access",
                grant_target=_DEFAULT_MODEL_GRANT_TARGET,
                status="active",
                granted_by=str(registered_by),
                budget_remaining_usd=budget_str,
            )
            model_grant_args = model_grant_payload.model_dump(mode="json")
            results.append(
                await _pevr(
                    ledger=ledger,
                    company_id=company_id,
                    target_kind="agent_grant",
                    ref_id=aid,
                    reason=(
                        f"grant model.access (budget={budget_str} USD) "
                        f"to agent {aid}"
                    ),
                    proposed_by=str(registered_by),
                    tool=f"emit_{AgentGrantPayload.kind}",
                    args=model_grant_args,
                    result_ref=str(aid),
                    payload_cls=AgentGrantPayload,
                    rationale=(
                        "model.access grant from registration flow"
                    ),
                )
            )

    return aid, results


# ---------------------------------------------------------------------------
# Agent revocation — v1.4 follow-up (Path 5).
#
# Revoking an Agent is implemented by writing one ``agent_grant`` (status=
# ``revoked``) PEVR cycle for each currently-active grant the agent holds.
# Per doctrine Addendum 3, agent state is *derived* from the most-recent
# grant rows folded on ``(agent_id, grant_kind, grant_target)`` — when
# every active grant is replaced with a revoked row, the agent has no
# capabilities and the LedgerAgentGrantReader returns an empty sequence
# (which is the gate-chain's natural "no access" state).
#
# We deliberately do NOT introduce a separate ``agent_registered_revoked``
# or ``agent_revoked`` entry kind. Two reasons:
#
#   * Addendum 3 — single-kind-with-status is the canonical pattern for
#     agent grants. Mirroring the same pattern here keeps KIND_REGISTRY
#     additive-only (currently 103; this change keeps it at 103).
#   * "Agent has active capabilities" is equivalent to "agent has at least
#     one active grant"; cascading revoke over the grants is the
#     load-bearing semantic. Anything else (e.g. "soft-disable the agent
#     while keeping grants alive") would be a different feature.
#
# Edit-agent (changing display_name / description) is intentionally
# deferred — see Path 5 prompt notes. The detail-page Edit chip remains a
# stub; revoke is the security-critical action and ships first.
# ---------------------------------------------------------------------------


async def revoke_agent(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    agent_id: str,
    revoked_by: UUID,
    reason: str = "admin_revoked",
) -> list[WriteResult]:
    """Revoke every active grant held by ``agent_id``.

    Walks the company's ledger entries to find the agent's currently-
    active grants (folded on ``(agent_id, grant_kind, grant_target)`` —
    most-recent state wins). For each active grant, writes one
    ``agent_grant`` PEVR cycle with ``status="revoked"``. The
    LedgerAgentGrantReader / projection-builder folds will naturally see
    these as the latest state and drop the rows from the active set.

    Returns the list of WriteResults in revocation order — one per grant
    that was active at the time of the scan. An agent with no active
    grants returns ``[]`` (idempotent: re-running revoke on an
    already-revoked agent is a no-op).

    ``reason`` is recorded on the proposal/resolve rationale so the audit
    trail captures *why* the revoke happened. The grant payload itself
    does not carry a reason field (status-as-state is the canonical
    pattern; rationale lives on the resolve entry).
    """
    if not agent_id:
        raise ValueError("agent_id must be non-empty")

    # Scan for active grants — fold newest-first per
    # (agent_id, grant_kind, grant_target) and keep only status=active.
    # This is the same fold LedgerAgentGrantReader.list_active_grants
    # performs; we inline it here to avoid a cross-package import from
    # write_actions (which intentionally has a narrow dependency surface).
    entries = await ledger.fetch(company_id)
    seen_triples: set[tuple[str, str, str]] = set()
    active_grants: list[tuple[str, str, str | None]] = []

    for entry in reversed(entries):
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if payload.get("tool") != "emit_agent_grant":
            continue
        args = payload.get("args") or {}
        row_agent = str(args.get("agent_id") or "")
        if row_agent != agent_id:
            continue
        grant_kind = args.get("grant_kind")
        grant_target = args.get("grant_target")
        if grant_kind is None or grant_target is None:
            continue
        triple = (row_agent, str(grant_kind), str(grant_target))
        if triple in seen_triples:
            continue
        seen_triples.add(triple)

        if args.get("status") == "active":
            budget = args.get("budget_remaining_usd")
            active_grants.append((str(grant_kind), str(grant_target), budget))

    results: list[WriteResult] = []
    for grant_kind, grant_target, budget in active_grants:
        revoke_payload = AgentGrantPayload(
            agent_id=agent_id,
            grant_kind=grant_kind,  # type: ignore[arg-type]
            grant_target=grant_target,
            status="revoked",
            granted_by=str(revoked_by),
            budget_remaining_usd=budget,
        )
        revoke_args = revoke_payload.model_dump(mode="json")
        # ref_id binds to the agent itself (not a per-grant uuid) so the
        # full revoke fan-out is greppable by agent_id in the ledger.
        # We use a deterministic UUID5-derived ref so multiple revoke
        # PEVR cycles on the same agent share a referent; the actual
        # disambiguator is the (grant_kind, grant_target) on the args.
        try:
            ref_uuid = UUID(agent_id)
        except (ValueError, TypeError):
            # Agent ids are minted as UUIDs by register_agent, but
            # tolerate non-UUID test ids by hashing — keeps the
            # function callable from minimal-fixture unit tests.
            from uuid import uuid5, NAMESPACE_URL

            ref_uuid = uuid5(NAMESPACE_URL, f"wormbase:agent:{agent_id}")
        results.append(
            await _pevr(
                ledger=ledger,
                company_id=company_id,
                target_kind="agent_grant",
                ref_id=ref_uuid,
                reason=(
                    f"revoke {grant_kind} grant on {grant_target} "
                    f"for agent {agent_id} ({reason})"
                ),
                proposed_by=str(revoked_by),
                tool=f"emit_{AgentGrantPayload.kind}",
                args=revoke_args,
                result_ref=agent_id,
                payload_cls=AgentGrantPayload,
                rationale=(
                    f"agent revoked by admin {revoked_by}: {reason}"
                ),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Agent metadata update — final wave item #5 (2026-05-13).
#
# Wires the agent detail page's Edit modal. Emits one
# ``agent_metadata_updated`` PEVR cycle per call. The agent's identity
# (agent_id, person_id, external_provider) stays immutable — only the
# human-readable surface (display_name, description) mutates.
#
# Status-consolidation observed: there is no ``agent_metadata_reverted``
# or similar — emit a new ``agent_metadata_updated`` to undo a prior
# update. The fold on the dashboard side takes the most-recent non-None
# value per field.
#
# Why a new kind (and not revoke + re-register): re-register breaks
# agent_id continuity, which forks the audit trail and orphans grants,
# subscriptions, and query history. Mutable-metadata + immutable-identity
# is the canonical Phase 2 split. KIND_REGISTRY 103 → 104; well under
# the 120-kind Wave F Addendum 1 ceiling.
# ---------------------------------------------------------------------------


async def update_agent_metadata(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    agent_id: str,
    updated_by_person_id: UUID,
    display_name: str | None = None,
    description: str | None = None,
    reason: str | None = None,
) -> WriteResult:
    """Emit one ``agent_metadata_updated`` PEVR cycle for ``agent_id``.

    At least one of ``display_name`` / ``description`` must be non-None —
    the HTTP endpoint validates this and returns 422; the dashboard's
    form validator catches the same condition client-side. We assert
    here as a belt+braces invariant; passing both as None is caller
    error, not a legitimate empty-update.

    ``updated_by_person_id`` is the admin Person who authorized the
    edit. Admin role enforcement lives on the dashboard server action
    (defense in depth — the HTTP layer trusts the bearer token across
    all admin actions, the dashboard is the role boundary).

    Returns the single ``WriteResult`` for the metadata-updated cycle.
    The agent's audit panel folds the entry into its trail naturally
    via ``getAgentAuditEntries`` (already covers ``emit_agent_*``
    tools — including this new one).
    """
    if not agent_id:
        raise ValueError("agent_id must be non-empty")
    if display_name is None and description is None:
        raise ValueError(
            "at least one of display_name or description must be set "
            "(both None is a no-op — caller should not invoke)"
        )

    payload = AgentMetadataUpdatedPayload(
        agent_id=agent_id,
        display_name=display_name,
        description=description,
        updated_by_person_id=str(updated_by_person_id),
        reason=reason,
    )
    args = payload.model_dump(mode="json")

    # ref_id binds to the agent_id (UUID5-fallback for non-UUID test ids)
    # so the metadata-update history is greppable by agent.
    try:
        ref_uuid = UUID(agent_id)
    except (ValueError, TypeError):
        from uuid import NAMESPACE_URL, uuid5

        ref_uuid = uuid5(NAMESPACE_URL, f"wormbase:agent:{agent_id}")

    changed_fields = []
    if display_name is not None:
        changed_fields.append("display_name")
    if description is not None:
        changed_fields.append("description")
    fields_summary = "+".join(changed_fields)

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="agent_metadata_updated",
        ref_id=ref_uuid,
        reason=(
            f"update agent {agent_id} metadata ({fields_summary})"
            f"{f' — {reason}' if reason else ''}"
        ),
        proposed_by=str(updated_by_person_id),
        tool=f"emit_{AgentMetadataUpdatedPayload.kind}",
        args=args,
        result_ref=agent_id,
        payload_cls=AgentMetadataUpdatedPayload,
        rationale=(
            f"agent metadata updated by admin {updated_by_person_id}"
            f"{f': {reason}' if reason else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# Agent metadata revert — post-rest path #4 (2026-05-13).
#
# Reverts an agent's display_name + description to their prior values by
# emitting a NEW ``agent_metadata_updated`` PEVR cycle (forward-only
# doctrine). No new ledger kind; no mutation of prior entries.
#
# Lookup logic:
#   1. Read all ``agent_metadata_updated`` executes for this agent, newest
#      first. The most-recent ("head") is the one being reverted.
#   2. If a prior ``agent_metadata_updated`` exists, fold its display_name
#      and description forward over the ``agent_registered`` baseline —
#      the worm-core fold takes the most-recent non-None value per field,
#      so we walk back from the head (exclusive) collecting non-None.
#   3. If no prior update exists, revert to the ``agent_registered``
#      baseline (display_name from registration, description=None).
#
# The emitted entry sets display_name and description to the resolved
# prior values explicitly (both non-None). The fold on the dashboard
# side picks up the new entry as the head, restoring the prior state.
# ---------------------------------------------------------------------------


def _fold_metadata_at_or_before(
    entries: list[dict[str, Any]],
    agent_id: str,
    *,
    exclude_seq: int | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Resolve the (display_name, description, agent_registered_row) for an agent.

    Walks the ledger in chronological order, applying each
    ``agent_metadata_updated`` execute row as a per-field fold (most-recent
    non-None value wins, mirroring ``getAgentMetadata`` on the dashboard).

    ``exclude_seq``, when set, skips the entry at that seq — used by the
    revert path to fold "everything before the head we're reverting".

    Returns ``(display_name, description, agent_registered_row)`` where
    ``agent_registered_row`` is the raw register-execute entry (carrying
    the registration baseline), or ``None`` if no register entry was
    found.
    """
    display_name: str | None = None
    description: str | None = None
    registered_row: dict[str, Any] | None = None

    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        row_agent = str(args.get("agent_id") or "")
        if row_agent != agent_id:
            continue
        if tool == "emit_agent_registered":
            registered_row = entry
            # Registration sets the baseline display_name; description
            # is unset at registration time.
            display_name = args.get("display_name")
            description = None
        elif tool == "emit_agent_metadata_updated":
            if exclude_seq is not None and entry.get("seq") == exclude_seq:
                continue
            if args.get("display_name") is not None:
                display_name = args.get("display_name")
            if args.get("description") is not None:
                description = args.get("description")

    return display_name, description, registered_row


async def revert_agent_metadata(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    agent_id: str,
    updated_by_person_id: UUID,
    reason: str | None = None,
) -> WriteResult:
    """Revert an agent's metadata to its prior state.

    Reads the most-recent ``agent_metadata_updated`` for this agent (the
    "head"), then folds every prior entry for this agent to resolve the
    pre-head display_name + description. Emits a new
    ``agent_metadata_updated`` whose fields set those resolved values
    explicitly — the fold sees the new entry as the head and restores
    the prior state.

    Raises ``ValueError`` when:
      * ``agent_id`` is empty
      * no ``agent_metadata_updated`` exists for this agent (nothing to
        revert; caller should surface a friendly 400)

    Returns the single ``WriteResult`` for the new compensating cycle.
    The new entry's reason auto-prefixes ``"revert from seq {N}"`` so
    the audit trail makes the compensating nature obvious; any
    caller-supplied ``reason`` is appended.
    """
    if not agent_id:
        raise ValueError("agent_id must be non-empty")

    entries = await ledger.fetch(company_id)

    # Locate the most-recent agent_metadata_updated for this agent. We
    # walk reversed entries to find it, then use its seq to exclude it
    # from the pre-head fold.
    head_row: dict[str, Any] | None = None
    for entry in reversed(entries):
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if payload.get("tool") != "emit_agent_metadata_updated":
            continue
        args = payload.get("args") or {}
        if str(args.get("agent_id") or "") != agent_id:
            continue
        head_row = entry
        break

    if head_row is None:
        raise ValueError(
            f"agent {agent_id} has no prior agent_metadata_updated entries; "
            "nothing to revert"
        )

    head_seq = head_row.get("seq")
    prior_display_name, prior_description, registered_row = (
        _fold_metadata_at_or_before(
            entries, agent_id, exclude_seq=head_seq,
        )
    )

    if registered_row is None:
        # Defensive: an agent_metadata_updated exists but no
        # agent_registered does. This should be impossible under normal
        # write paths; surface a clear ValueError.
        raise ValueError(
            f"agent {agent_id} has metadata updates but no agent_registered "
            "baseline; cannot resolve revert target"
        )

    # We always emit non-None values for both fields on revert. This
    # is required because the fold treats None as "unchanged" — to
    # restore a prior description=None state we would need to leave it
    # unchanged on the new entry, which would NOT revert if the head
    # had set a description. So both fields are set explicitly.
    #
    # Edge: if prior_description is None (no description was ever set),
    # we still need to "clear" the head's description. Set to empty
    # string — same convention as the Edit modal supports clearing.
    resolved_display_name = prior_display_name or "Agent"  # safety net
    resolved_description = prior_description if prior_description is not None else ""

    short_seq = f"seq {head_seq}" if head_seq is not None else "prior head"
    auto_reason = f"revert from {short_seq}"
    full_reason = (
        auto_reason
        if reason is None or not reason.strip()
        else f"{auto_reason} — {reason}"
    )

    return await update_agent_metadata(
        ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=updated_by_person_id,
        display_name=resolved_display_name,
        description=resolved_description,
        reason=full_reason,
    )


# ---------------------------------------------------------------------------
# Catalog imports — dbt manifest + Snowflake INFORMATION_SCHEMA.
#
# Both flows share the same shape: fetch / discover a snapshot, write
# ``external_catalog_imported`` + per-edge ``external_lineage_imported``
# + per-metric ``external_metric_imported``, then construct a tiny
# upstream_mirror Source record and wire catalog-mirror Reactivities so
# subsequent drift checks fire automatically.
# ---------------------------------------------------------------------------


class _UpstreamMirrorSource:
    """Minimal MaintainableSource-shaped record for catalog-mirror wiring.

    The W3 Task 7 ``source_mode == "upstream_mirror"`` Sources only need
    the four attributes ``wire_catalog_for_source`` reads:
    ``id`` / ``domain_id`` / ``catalog_source`` / ``secrets``. We do NOT
    register these into the lake-maintainer ``SourceRegistry`` — the
    catalog-mirror Reactivities (initial import + drift) are all that
    runs at v1.1; lake-maintainer's four maintenance Reactivities don't
    apply to upstream_mirror sources at this stage.
    """

    def __init__(
        self,
        *,
        source_id: UUID,
        domain_id: UUID,
        catalog_source: Any,
        secrets: dict[str, str] | None = None,
    ) -> None:
        self.id = source_id
        self.domain_id = domain_id
        self.catalog_source = catalog_source
        self.secrets = dict(secrets or {})
        self.source_mode = "upstream_mirror"


async def _fetch_dbt_manifest(manifest_uri: str) -> Any:
    """Resolve ``manifest_uri`` to a local Path containing the manifest JSON.

    Supports:
      * ``file://...`` — direct file path
      * absolute / relative filesystem paths (no scheme)
      * ``http://...`` / ``https://...`` — fetched via httpx, written to
        a tempfile so ``parse_dbt_manifest`` can read it as a Path
    """
    import tempfile
    from pathlib import Path
    from urllib.parse import urlparse

    parsed = urlparse(manifest_uri)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("", "file"):
        local = parsed.path if scheme == "file" else manifest_uri
        path = Path(local)
        if not path.exists():
            raise FileNotFoundError(
                f"dbt manifest not found at {path}",
            )
        return path

    if scheme not in ("http", "https"):
        raise ValueError(
            f"unsupported manifest_uri scheme {scheme!r}; "
            "expected file://, http://, https:// or a local path"
        )

    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(manifest_uri)
        response.raise_for_status()
        body = response.content

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, prefix="dbt-manifest-",
    ) as tmp:
        tmp.write(body)
        tmp.flush()
        tmp_path = tmp.name
    return Path(tmp_path)


async def _emit_external_catalog_pevr(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    source_id: UUID,
    domain_id: UUID,
    source_kind: str,
    snapshot: Any,
    proposed_by: str,
) -> list[WriteResult]:
    """Write ``external_catalog_imported`` + lineage + metrics for one snapshot.

    Returns the WriteResult list in registration order: import primary,
    then one per lineage edge, then one per metric. Mirrors
    ``CatalogImportReactivity.fire`` so an admin-driven import yields the
    same ledger byte-shape as a Reactivity-driven import.
    """
    results: list[WriteResult] = []

    primary_payload = ExternalCatalogImportedPayload(
        source_kind=source_kind,
        source_id=str(source_id),
        domain_id=str(domain_id),
        snapshot_hash=snapshot.snapshot_hash,
        table_count=len(snapshot.tables),
        edge_count=len(snapshot.lineage.edges),
        metric_count=len(snapshot.metrics),
        import_mode="initial",
    )
    primary_args = primary_payload.model_dump(mode="json")
    results.append(
        await _pevr(
            ledger=ledger,
            company_id=company_id,
            target_kind="external_catalog_imported",
            ref_id=source_id,
            reason=(
                f"import {source_kind} catalog "
                f"({len(snapshot.tables)} tables, "
                f"{len(snapshot.lineage.edges)} edges)"
            ),
            proposed_by=proposed_by,
            tool=f"emit_{ExternalCatalogImportedPayload.kind}",
            args=primary_args,
            result_ref=str(source_id),
            payload_cls=ExternalCatalogImportedPayload,
            rationale=f"initial {source_kind} catalog mirror",
        )
    )

    # Wave 2 Sub-wave B: per-table catalog_table_imported emission.
    # For catalog-mirror snapshots (dbt/snowflake/etc.), ``snapshot.tables``
    # already carries the per-column metadata via ``TableMeta.columns``.
    # We emit one PEVR per discovered table, preserving the honest-empty-
    # upstream posture: tables whose ``columns`` is empty (e.g. permissions-
    # denied) emit with ``columns=()`` rather than being skipped.
    for table in snapshot.tables:
        table_columns: tuple[CatalogColumnSpec, ...] = tuple(
            CatalogColumnSpec(name=col.name, type=col.type)
            for col in getattr(table, "columns", ())
            if getattr(col, "name", "")
        )
        results.append(
            await emit_catalog_table_imported(
                ledger=ledger,
                company_id=company_id,
                source_id=source_id,
                snapshot_hash=snapshot.snapshot_hash,
                table_id=table.external_id,
                columns=table_columns,
                proposed_by=proposed_by,
            )
        )

    if snapshot.lineage.edges:
        # The catalog-mirror Reactivity emits ONE lineage entry carrying
        # the flat edge list. We mirror that shape exactly so projection
        # folds (``projection_external_lineage``) stay byte-equivalent.
        lineage_payload = ExternalLineageImportedPayload(
            source_id=str(source_id),
            edges=tuple(
                (e.upstream, e.downstream)
                for e in snapshot.lineage.edges
            ),
        )
        lineage_args = lineage_payload.model_dump(mode="json")
        results.append(
            await _pevr(
                ledger=ledger,
                company_id=company_id,
                target_kind="external_lineage_imported",
                ref_id=source_id,
                reason=(
                    f"import {len(snapshot.lineage.edges)} lineage "
                    f"edge(s) from {source_kind} catalog"
                ),
                proposed_by=proposed_by,
                tool=f"emit_{ExternalLineageImportedPayload.kind}",
                args=lineage_args,
                result_ref=str(source_id),
                payload_cls=ExternalLineageImportedPayload,
                rationale=f"{source_kind} lineage mirrored",
            )
        )

    for metric in snapshot.metrics:
        metric_payload = ExternalMetricImportedPayload(
            source_id=str(source_id),
            name=metric.name,
            expression=metric.expression,
            time_grain=getattr(metric, "time_grain", None),
            dimensions=tuple(getattr(metric, "dimensions", ()) or ()),
            description=getattr(metric, "description", None),
        )
        metric_args = metric_payload.model_dump(mode="json")
        results.append(
            await _pevr(
                ledger=ledger,
                company_id=company_id,
                target_kind="external_metric_imported",
                ref_id=source_id,
                reason=(
                    f"import metric {metric.name!r} from "
                    f"{source_kind} catalog"
                ),
                proposed_by=proposed_by,
                tool=f"emit_{ExternalMetricImportedPayload.kind}",
                args=metric_args,
                result_ref=str(source_id),
                payload_cls=ExternalMetricImportedPayload,
                rationale=f"{source_kind} metric mirrored",
            )
        )

    return results


async def emit_catalog_table_imported(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    source_id: str | UUID,
    snapshot_hash: str,
    table_id: str,
    columns: list[CatalogColumnSpec] | tuple[CatalogColumnSpec, ...] = (),
    proposed_by: str = "worm_core",
) -> WriteResult:
    """Emit one ``catalog_table_imported`` PEVR cycle.

    Mirrors the per-table substrate landed in Sub-wave A: one PEVR per
    discovered table per snapshot. The composite identity for the
    projection fold is ``(source_id, snapshot_hash, table_id)``, so
    re-emitting the same row collapses onto the same projection entry
    (replay-stable).

    ``columns`` may be empty (honest empty-upstream posture for
    connectors that lack column-type introspection — the
    :class:`CatalogTableImportedPayload` validator accepts empty tuples
    as a valid state per Sub-wave A).

    Wave 2 Sub-wave B (connector emission) calls this helper once per
    discovered table per snapshot, alongside the summary
    ``external_catalog_imported`` entry. The same call site shape
    applies to upstream_mirror sources (dbt / snowflake) once their
    extractor lands — csv_local is the first wired connector kind.
    """
    sid = str(source_id)
    columns_tuple = tuple(columns)
    payload = CatalogTableImportedPayload(
        source_id=sid,
        snapshot_hash=snapshot_hash,
        table_id=table_id,
        columns=columns_tuple,
    )
    args = payload.model_dump(mode="json")
    # Stable, per-row ref so the entry ledger row is deterministic and
    # replay-friendly. Same row → same ref_id → same hash chain.
    result_ref = f"{sid}|{snapshot_hash}|{table_id}"
    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="catalog_table_imported",
        # ref_id carries the composite key in a single token so a
        # ledger consumer can join propose→execute on the table row.
        # _pevr coerces ref_id via str() before writing — passing a
        # composite str key is the same shape used by L2's
        # ``make_drift_id``-style natural-key proposes.
        ref_id=result_ref,  # type: ignore[arg-type]
        reason=(
            f"catalog mirror: per-table column metadata for "
            f"table_id={table_id!r} in snapshot {snapshot_hash[:8]!r}"
        ),
        proposed_by=proposed_by,
        tool=f"emit_{CatalogTableImportedPayload.kind}",
        args=args,
        result_ref=result_ref,
        payload_cls=CatalogTableImportedPayload,
        rationale=(
            f"per-table catalog row recorded "
            f"({len(columns_tuple)} columns)"
        ),
    )


async def emit_catalog_table_imported_for_resource(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    source_id: str | UUID,
    snapshot_hash: str,
    table_id: str,
    connector_kind: str,
    connector: Any = None,
    handle: Any = None,
    resource_id: str | None = None,
    proposed_by: str = "worm_core",
) -> WriteResult:
    """Emit one ``catalog_table_imported`` PEVR via the extractor registry.

    Convenience wrapper around :func:`emit_catalog_table_imported` that
    consults the per-connector-kind extractor registry (see
    :mod:`wormbase_core.catalog_column_extractors`) to resolve the
    column list before writing.

    Connector-driven flows (csv_local + future postgres / stripe / etc.)
    call this after a successful profile so the per-table catalog row
    lands alongside the source-lifecycle entries. Connector kinds
    without a registered extractor fall through to ``columns=()`` —
    the honest-empty-upstream posture (the entry still lands so the
    reader fold returns a CatalogTable for it).

    ``resource_id`` defaults to ``table_id`` when omitted; for csv_local
    the two are identical (both are the absolute file path).
    """
    # Lazy import — keeps the registry module out of write_actions's
    # import-time graph for callers that never touch this helper.
    from wormbase_core.catalog_column_extractors import extract_columns

    rid = resource_id if resource_id is not None else table_id
    columns = extract_columns(
        connector=connector,
        handle=handle,
        resource_id=rid,
        connector_kind=connector_kind,
    )
    return await emit_catalog_table_imported(
        ledger=ledger,
        company_id=company_id,
        source_id=source_id,
        snapshot_hash=snapshot_hash,
        table_id=table_id,
        columns=columns,
        proposed_by=proposed_by,
    )


async def import_dbt_catalog(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    source_id: UUID | None = None,
    manifest_uri: str,
    domain_id: UUID,
    imported_by: UUID,
    reactivity_registry: Any | None = None,
) -> tuple[UUID, list[WriteResult]]:
    """Import an existing dbt project's manifest as an upstream_mirror Source.

    Steps:

    1. Resolve ``manifest_uri`` to a local Path (``file://``, ``https://``
       or a bare filesystem path).
    2. Parse the manifest via ``parse_dbt_manifest`` — raises
       ``ManifestVersionUnsupportedError`` on unsupported schema versions.
    3. Mint a new ``source_id`` and write ``external_catalog_imported``
       + per-edge ``external_lineage_imported`` + per-metric
       ``external_metric_imported`` ledger cycles.
    4. Register the per-source catalog-mirror Reactivities via
       ``wire_catalog_for_source`` (Wave 1 Task 5 cleanup 1a) when a
       ``reactivity_registry`` is supplied. The wire is a no-op when the
       registry is None — unit-test code paths that don't care about
       drift detection can skip it.

    Returns ``(source_id, [WriteResult, ...])``. The WriteResult list is
    in write order (import primary first, then lineage, then metrics).
    """
    from wormbase_catalog_mirror import wire_catalog_for_source
    from wormbase_catalog_mirror.implementations.dbt_manifest import (
        DbtManifestCatalogSource,
        parse_dbt_manifest,
    )

    sid = source_id or uuid4()
    manifest_path = await _fetch_dbt_manifest(manifest_uri)
    snapshot = parse_dbt_manifest(manifest_path)

    results = await _emit_external_catalog_pevr(
        ledger=ledger,
        company_id=company_id,
        source_id=sid,
        domain_id=domain_id,
        source_kind="dbt",
        snapshot=snapshot,
        proposed_by=str(imported_by),
    )

    if reactivity_registry is not None:
        catalog_source = DbtManifestCatalogSource(manifest_path=manifest_path)
        source = _UpstreamMirrorSource(
            source_id=sid,
            domain_id=domain_id,
            catalog_source=catalog_source,
            secrets={},
        )
        await wire_catalog_for_source(
            source=source,
            ledger=ledger,
            reactivity_registry=reactivity_registry,
        )

    return sid, results


async def import_snowflake_catalog(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    source_id: UUID | None = None,
    account: str,
    user: str,
    warehouse: str,
    database: str,
    schema_name: str,
    role: str | None = None,
    domain_id: UUID,
    imported_by: UUID,
    credential_broker: Any | None = None,
    install_id: str | None = None,
    catalog_source: Any | None = None,
    reactivity_registry: Any | None = None,
) -> tuple[UUID, list[WriteResult]]:
    """Import an existing Snowflake account's catalog as an upstream_mirror Source.

    Credential capture: the Snowflake password / OAuth token is captured
    OUT-OF-BAND via ``CredentialBroker.hold_data_account(install_id,
    upstream_kind="snowflake")`` — NEVER passed in the request body
    (see CLAUDE.md security posture). When a ``credential_broker`` is
    supplied, the secret payload is merged into the auth secrets dict
    passed to ``SnowflakeNativeCatalogSource.authenticate``.

    The ``catalog_source`` kwarg lets unit tests inject a stub
    CatalogSource without standing up a real Snowflake account; when
    omitted, a real ``SnowflakeNativeCatalogSource`` is constructed.

    Steps mirror ``import_dbt_catalog``: authenticate → discover_catalog
    → write the canonical PEVR chain → wire catalog-mirror Reactivities.

    Returns ``(source_id, [WriteResult, ...])``.
    """
    from wormbase_catalog_mirror import wire_catalog_for_source

    sid = source_id or uuid4()

    if catalog_source is None:
        from wormbase_catalog_mirror.implementations.snowflake_native import (
            SnowflakeNativeCatalogSource,
        )
        catalog_source = SnowflakeNativeCatalogSource()

    # Connection shape comes from the request body; the password/token
    # comes from the broker (when wired). Tests that pass a stub
    # ``catalog_source`` may not need any secrets at all.
    secrets: dict[str, str] = {
        "account": account,
        "user": user,
        "warehouse": warehouse,
        "database": database,
        "schema": schema_name,
    }
    if role:
        secrets["role"] = role

    if credential_broker is not None and install_id:
        try:
            handle = await credential_broker.hold_data_account(
                install_id, upstream_kind="snowflake",
            )
            payload = getattr(handle, "payload", None) or {}
            # Merge broker-held secrets (password / token / role override).
            for k, v in payload.items():
                if v is not None:
                    secrets[str(k)] = str(v)
        except Exception as exc:
            raise ValueError(
                f"snowflake credential broker lookup failed: {exc}",
            ) from exc

    auth_handle = await catalog_source.authenticate(secrets)
    snapshot = await catalog_source.discover_catalog(auth_handle)

    results = await _emit_external_catalog_pevr(
        ledger=ledger,
        company_id=company_id,
        source_id=sid,
        domain_id=domain_id,
        source_kind=getattr(catalog_source, "kind", "snowflake"),
        snapshot=snapshot,
        proposed_by=str(imported_by),
    )

    if reactivity_registry is not None:
        source = _UpstreamMirrorSource(
            source_id=sid,
            domain_id=domain_id,
            catalog_source=catalog_source,
            secrets=secrets,
        )
        await wire_catalog_for_source(
            source=source,
            ledger=ledger,
            reactivity_registry=reactivity_registry,
        )

    return sid, results


# ---------------------------------------------------------------------------
# Promote semantic gap — Wave 3 Task 5 → v1.1.
#
# Looks up a ``semantic_gap_proposed`` ledger entry by id, validates the
# kind, then emits an ``external_metric_imported`` cycle whose top-level
# propose record carries ``caused_by`` pointing to the gap entry — the
# canonical chaining shape per doctrine Addendum 3 §B (semantic_gap →
# external_metric_imported).
# ---------------------------------------------------------------------------


async def _find_ledger_entry(
    ledger: LedgerLike,
    company_id: UUID,
    entry_id: str,
) -> dict[str, Any] | None:
    """Locate one ledger entry by ``entry_id`` for ``company_id``.

    Prefers the canonical ``ledger.get_entry(company_id, entry_id)``
    direct-lookup surface (O(1) on the DB-backed path; indexed primary
    key + tenant scoping). Falls back to iterating ``ledger.fetch``
    when the underlying ledger doesn't implement ``get_entry`` — this
    keeps the ``LedgerLike = Ledger | InMemoryLedger | Any`` contract
    backwards-compatible for any test double that pre-dates v1.2.
    """
    target = str(entry_id)
    get_entry = getattr(ledger, "get_entry", None)
    if get_entry is not None:
        try:
            entry_uuid = UUID(target)
        except (ValueError, AttributeError):
            entry_uuid = None
        if entry_uuid is not None:
            try:
                entry = await get_entry(company_id, entry_uuid)
            except (NotImplementedError, AttributeError):
                entry = None
            else:
                return entry

    entries = await ledger.fetch(company_id)
    for entry in entries:
        eid = entry.get("entry_id")
        if eid is None:
            continue
        if str(eid) == target:
            return entry
    return None


def _entry_is_semantic_gap(entry: dict[str, Any]) -> bool:
    """True iff the entry carries a ``semantic_gap_proposed`` execute payload.

    Lookup pattern matches the canonical ledger shape: the propose
    cycle's ``execute`` row carries ``tool = "emit_semantic_gap_proposed"``.
    We accept either the execute or the propose row of the cycle, since
    the entry-id passed by the dashboard may reference either.
    """
    payload = entry.get("payload") or {}
    if entry.get("kind") == "execute":
        return (
            payload.get("tool")
            == f"emit_{SemanticGapProposedPayload.kind}"
        )
    if entry.get("kind") == "propose":
        return payload.get("target_kind") == SemanticGapProposedPayload.kind
    return False


async def promote_semantic_gap(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    metric_id: UUID | None = None,
    semantic_gap_entry_id: str,
    metric_name: str,
    metric_expression: str,
    domain_id: UUID,
    promoted_by: UUID,
) -> tuple[UUID, WriteResult]:
    """Promote a ``semantic_gap_proposed`` entry to an ``external_metric_imported``.

    Returns ``(metric_id, WriteResult)`` so the dashboard can route the
    admin to the newly-registered metric. The ``caused_by`` field on the
    propose payload links the new metric to the originating gap entry id
    for audit-trail traversal — both views in the dashboard
    (``/lake/metrics-proposed`` admin queue + ``/lake/catalog`` metrics
    list) consume the link via projection joins.

    Raises ``ValueError`` when:
      * the gap entry id is unknown, or
      * the referenced entry is NOT a ``semantic_gap_proposed`` cycle row.

    Both surface as HTTP 400 to the dashboard via the surrounding
    handler.
    """
    gap_entry = await _find_ledger_entry(
        ledger, company_id, semantic_gap_entry_id,
    )
    if gap_entry is None:
        raise ValueError(
            f"semantic_gap entry {semantic_gap_entry_id!r} not found "
            f"for company_id={company_id}",
        )
    if not _entry_is_semantic_gap(gap_entry):
        raise ValueError(
            f"entry {semantic_gap_entry_id!r} is not a "
            f"semantic_gap_proposed cycle row (kind={gap_entry.get('kind')}, "
            f"target={(gap_entry.get('payload') or {}).get('target_kind')})",
        )

    mid = metric_id or uuid4()
    payload = ExternalMetricImportedPayload(
        # Synthetic source — the promoted metric did not originate from
        # an upstream catalog source. v1.2 canonicalization: the three
        # promote-only fields (``domain_id`` / ``promoted_from_gap_id``
        # / ``promoted_by``) are now first-class payload fields per
        # doctrine Rule 2 (additive, defaults ``None``) rather than
        # stuffed into ``args`` after ``model_dump``.
        source_id="_promoted_from_gap",
        name=metric_name,
        expression=metric_expression,
        time_grain=None,
        dimensions=(),
        description=None,
        domain_id=str(domain_id),
        promoted_from_gap_id=semantic_gap_entry_id,
        promoted_by=str(promoted_by),
    )
    base_args = payload.model_dump(mode="json")
    args = base_args

    # Mirror ``_pevr`` exactly but inject ``caused_by`` into the propose
    # payload — the canonical Addendum 3 chaining surface. ``_pevr``
    # doesn't accept ``caused_by`` as a kwarg today, so we open-code the
    # call here for this one orchestrator.
    def _verify(_exec_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            ExternalMetricImportedPayload(**base_args)
            return {
                "checks": [
                    {"name": "promote_semantic_gap_payload_valid", "ok": True},
                ],
                "passed": True,
            }
        except Exception as exc:
            return {
                "checks": [
                    {
                        "name": "promote_semantic_gap_payload_valid",
                        "ok": False,
                        "error": str(exc),
                    },
                ],
                "passed": False,
            }

    write_result = await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_metric_imported",
            "ref_id": str(mid),
            "reason": (
                f"promote semantic gap {semantic_gap_entry_id} "
                f"to metric {metric_name!r}"
            ),
            "proposed_by": str(promoted_by),
            "caused_by": semantic_gap_entry_id,
        },
        execute_fn=lambda: {
            "tool": f"emit_{ExternalMetricImportedPayload.kind}",
            "args": args,
            "result_ref": str(mid),
        },
        verify_fn=_verify,
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": (
                "semantic_gap_proposed promoted to external_metric_imported"
            ),
        },
        quadrant="active_deterministic",
    )
    return mid, write_result


__all__ = [
    "advance_setup_step",
    "archive_person",
    "bulk_confirm_persons",
    "complete_install",
    "complete_setup",
    "complete_tenant_signup",
    "confirm_column_classification",
    "confirm_entity_stitch",
    "confirm_person",
    "confirm_position_proposal",
    "confirm_schema_impact",
    "confirm_semantic_type",
    "grant_domain_role",
    "grant_resource_role",
    "grant_tenancy_role",
    "import_dbt_catalog",
    "import_snowflake_catalog",
    "initiate_tenant_signup",
    "link_identity",
    "merge_persons",
    "promote_semantic_gap",
    "propose_kpi_node",
    "propose_person",
    "propose_position",
    "propose_process_map",
    "propose_resource_role",
    "provision_local_lake",
    "record_decision",
    "confirm_lineage_edge",
    "confirm_quality_check",
    "record_mcp_call",
    "register_agent",
    "reject_column_classification",
    "reject_entity_stitch",
    "reject_lineage_edge",
    "reject_position_proposal",
    "reject_quality_check",
    "reject_schema_impact",
    "reject_semantic_type",
    "revert_agent_metadata",
    "revoke_agent",
    "update_agent_metadata",
    "revoke_tenancy_role",
    "set_setup_mode",
    "split_person",
    "unlink_identity",
]


# ---------------------------------------------------------------------------
# L3 Sub-wave C — lineage-edge admin write actions (2026-05-29).
#
# Two write actions backing the dashboard's lineage-edge confirm + reject
# admin surface. Each emits a forward-only PEVR cycle (no mutation of
# prior entries); the projection_lineage_edges fold collapses the new
# entry onto the existing edge row.
#
# Both helpers use a uuid5 derivation over the (company_id, edge_id)
# pair so the ref_id stays deterministic + replay-stable. The edge_id
# itself is a SHA-256-derived hex string from
# :func:`wormbase_agent_gateway.lineage.make_edge_id`.
# ---------------------------------------------------------------------------


def _edge_ref_uuid(company_id: UUID, edge_id: str) -> UUID:
    """Deterministic ref_id for lineage-edge PEVR cycles.

    Derives a uuid5 over ``(company_id, edge_id)`` so the same logical
    edge always yields the same ref_id — preserves replay stability
    across machines.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL, f"wormbase:lineage:{company_id}:{edge_id}",
    )


async def confirm_lineage_edge(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    edge_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``lineage_edge_confirmed`` for an admin-confirmed candidate edge.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_lineage_edges fold maps the new entry to ``state =
    "confirmed"`` on the (company_id, edge_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder.
    """
    payload = LineageEdgeConfirmedPayload(
        edge_id=edge_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="lineage_edge_confirmed",
        ref_id=_edge_ref_uuid(company_id, edge_id),
        reason=(
            f"confirm lineage edge {edge_id} via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{LineageEdgeConfirmedPayload.kind}",
        args=args,
        result_ref=edge_id,
        payload_cls=LineageEdgeConfirmedPayload,
        rationale=(
            f"lineage edge confirmed by admin {confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_lineage_edge(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    edge_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``lineage_edge_rejected`` for an admin-rejected candidate edge.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_lineage_edges fold maps the new entry to ``state =
    "rejected"`` on the (company_id, edge_id) row.

    ``reason`` is the strict enum on
    :class:`LineageEdgeRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back).
    """
    payload = LineageEdgeRejectedPayload(
        edge_id=edge_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="lineage_edge_rejected",
        ref_id=_edge_ref_uuid(company_id, edge_id),
        reason=(
            f"reject lineage edge {edge_id} (reason={reason}) "
            f"via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{LineageEdgeRejectedPayload.kind}",
        args=args,
        result_ref=edge_id,
        payload_cls=LineageEdgeRejectedPayload,
        rationale=(
            f"lineage edge rejected by admin {rejected_by_person_id} "
            f"(reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L7 Sub-wave C — quality-check admin write actions (2026-05-30).
#
# Two write actions backing the dashboard's quality-check confirm + reject
# admin surface. Each emits a forward-only PEVR cycle (no mutation of
# prior entries); the projection_quality_checks fold collapses the new
# entry onto the existing check row.
#
# Both helpers use a uuid5 derivation over the (company_id, check_id)
# pair so the ref_id stays deterministic + replay-stable. The check_id
# itself is a SHA-256-derived hex string from
# :func:`wormbase_agent_gateway.quality.protocol.make_check_id`.
# ---------------------------------------------------------------------------


def _check_ref_uuid(company_id: UUID, check_id: str) -> UUID:
    """Deterministic ref_id for quality-check PEVR cycles.

    Derives a uuid5 over ``(company_id, check_id)`` so the same logical
    check always yields the same ref_id — preserves replay stability
    across machines. Mirrors :func:`_edge_ref_uuid` (L3) shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL, f"wormbase:quality:{company_id}:{check_id}",
    )


async def confirm_quality_check(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    check_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``quality_check_confirmed`` for an admin-confirmed candidate check.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_quality_checks fold maps the new entry to ``state =
    "confirmed"`` on the (company_id, check_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3
    :func:`confirm_lineage_edge` shape.
    """
    payload = QualityCheckConfirmedPayload(
        check_id=check_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="quality_check_confirmed",
        ref_id=_check_ref_uuid(company_id, check_id),
        reason=(
            f"confirm quality check {check_id} via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{QualityCheckConfirmedPayload.kind}",
        args=args,
        result_ref=check_id,
        payload_cls=QualityCheckConfirmedPayload,
        rationale=(
            f"quality check confirmed by admin {confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_quality_check(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    check_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``quality_check_rejected`` for an admin-rejected candidate check.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_quality_checks fold maps the new entry to ``state =
    "rejected"`` on the (company_id, check_id) row.

    ``reason`` is the strict enum on
    :class:`QualityCheckRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back). The valid
    enum is {false_positive, low_value, wrong_threshold, out_of_scope,
    other}; HTTP layer enforces the same set at the boundary.
    """
    payload = QualityCheckRejectedPayload(
        check_id=check_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="quality_check_rejected",
        ref_id=_check_ref_uuid(company_id, check_id),
        reason=(
            f"reject quality check {check_id} (reason={reason}) "
            f"via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{QualityCheckRejectedPayload.kind}",
        args=args,
        result_ref=check_id,
        payload_cls=QualityCheckRejectedPayload,
        rationale=(
            f"quality check rejected by admin {rejected_by_person_id} "
            f"(reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L4 Sub-wave C — schema-impact admin write actions (2026-06-02).
#
# Two write actions backing the dashboard's schema-impact confirm + reject
# admin surface. Each emits a forward-only PEVR cycle (no mutation of
# prior entries); the projection_schema_impacts fold (v023) collapses
# the new entry onto the existing impact row.
#
# Both helpers use a uuid5 derivation over the (company_id, impact_id)
# pair so the ref_id stays deterministic + replay-stable. The impact_id
# itself is a SHA-256-derived hex string from
# :func:`wormbase_agent_gateway.schema_impact.make_impact_id`.
# ---------------------------------------------------------------------------


def _impact_ref_uuid(company_id: UUID, impact_id: str) -> UUID:
    """Deterministic ref_id for schema-impact PEVR cycles.

    Derives a uuid5 over ``(company_id, impact_id)`` so the same logical
    impact always yields the same ref_id — preserves replay stability
    across machines. Mirrors :func:`_edge_ref_uuid` (L3) and
    :func:`_check_ref_uuid` (L7) shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL, f"wormbase:schema_impact:{company_id}:{impact_id}",
    )


async def confirm_schema_impact(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    impact_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``schema_impact_confirmed`` for an admin-confirmed candidate impact.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_schema_impacts fold maps the new entry to ``state =
    "confirmed"`` on the (company_id, impact_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3
    :func:`confirm_lineage_edge` + L7
    :func:`confirm_quality_check` shape.
    """
    payload = SchemaImpactConfirmedPayload(
        impact_id=impact_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="schema_impact_confirmed",
        ref_id=_impact_ref_uuid(company_id, impact_id),
        reason=(
            f"confirm schema impact {impact_id} via dashboard admin "
            f"action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{SchemaImpactConfirmedPayload.kind}",
        args=args,
        result_ref=impact_id,
        payload_cls=SchemaImpactConfirmedPayload,
        rationale=(
            f"schema impact confirmed by admin {confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_schema_impact(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    impact_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``schema_impact_rejected`` for an admin-rejected candidate impact.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_schema_impacts fold maps the new entry to ``state =
    "rejected"`` on the (company_id, impact_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`SchemaImpactRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back). The valid
    enum is {false_positive, already_handled, low_value, out_of_scope,
    other}; HTTP layer enforces the same set at the boundary.
    """
    payload = SchemaImpactRejectedPayload(
        impact_id=impact_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="schema_impact_rejected",
        ref_id=_impact_ref_uuid(company_id, impact_id),
        reason=(
            f"reject schema impact {impact_id} (reason={reason}) "
            f"via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{SchemaImpactRejectedPayload.kind}",
        args=args,
        result_ref=impact_id,
        payload_cls=SchemaImpactRejectedPayload,
        rationale=(
            f"schema impact rejected by admin {rejected_by_person_id} "
            f"(reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L5 Sub-wave C — semantic-type admin write actions (2026-06-05).
#
# Two write actions backing the dashboard's semantic-type confirm + reject
# admin surface. Each emits a forward-only PEVR cycle (no mutation of
# prior entries); the projection_semantic_types fold (v024) collapses
# the new entry onto the existing semantic-type row.
#
# Both helpers use a uuid5 derivation over the (company_id, type_id)
# pair so the ref_id stays deterministic + replay-stable. The type_id
# itself is a SHA-256-derived hex string from
# :func:`wormbase_agent_gateway.semantic_type.make_type_id`.
# ---------------------------------------------------------------------------


def _type_ref_uuid(company_id: UUID, type_id: str) -> UUID:
    """Deterministic ref_id for semantic-type PEVR cycles.

    Derives a uuid5 over ``(company_id, type_id)`` so the same logical
    semantic-type proposal always yields the same ref_id — preserves
    replay stability across machines. Mirrors :func:`_edge_ref_uuid`
    (L3), :func:`_check_ref_uuid` (L7), and :func:`_impact_ref_uuid`
    (L4) shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL, f"wormbase:semantic_type:{company_id}:{type_id}",
    )


async def confirm_semantic_type(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    type_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``semantic_type_confirmed`` for an admin-confirmed candidate type.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_semantic_types fold maps the new entry to ``state =
    "confirmed"`` on the (company_id, type_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3 :func:`confirm_lineage_edge`
    + L7 :func:`confirm_quality_check` + L4
    :func:`confirm_schema_impact` shape.
    """
    payload = SemanticTypeConfirmedPayload(
        type_id=type_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="semantic_type_confirmed",
        ref_id=_type_ref_uuid(company_id, type_id),
        reason=(
            f"confirm semantic type {type_id} via dashboard admin "
            f"action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{SemanticTypeConfirmedPayload.kind}",
        args=args,
        result_ref=type_id,
        payload_cls=SemanticTypeConfirmedPayload,
        rationale=(
            f"semantic type confirmed by admin {confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_semantic_type(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    type_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``semantic_type_rejected`` for an admin-rejected candidate type.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_semantic_types fold maps the new entry to ``state =
    "rejected"`` on the (company_id, type_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`SemanticTypeRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back). The valid
    enum is {false_positive, low_value, wrong_type, out_of_scope,
    other}; HTTP layer enforces the same set at the boundary. The L5-
    specific 5th value is ``wrong_type`` (replaces L4's
    ``already_handled`` and L7's ``wrong_threshold``).
    """
    payload = SemanticTypeRejectedPayload(
        type_id=type_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="semantic_type_rejected",
        ref_id=_type_ref_uuid(company_id, type_id),
        reason=(
            f"reject semantic type {type_id} (reason={reason}) "
            f"via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{SemanticTypeRejectedPayload.kind}",
        args=args,
        result_ref=type_id,
        payload_cls=SemanticTypeRejectedPayload,
        rationale=(
            f"semantic type rejected by admin {rejected_by_person_id} "
            f"(reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L6 Sub-wave C — column-classification admin write actions (2026-06-06).
#
# Two write actions backing the dashboard's column-classification confirm +
# reject admin surface. Each emits a forward-only PEVR cycle (no mutation
# of prior entries); the projection_column_classifications fold (v025)
# collapses the new entry onto the existing classification row.
#
# Both helpers use a uuid5 derivation over the (company_id,
# classification_id) pair so the ref_id stays deterministic + replay-
# stable. The classification_id itself is a SHA-256-derived hex string
# from :func:`wormbase_agent_gateway.column_classification.make_classification_id`.
# ---------------------------------------------------------------------------


def _classification_ref_uuid(
    company_id: UUID, classification_id: str,
) -> UUID:
    """Deterministic ref_id for column-classification PEVR cycles.

    Derives a uuid5 over ``(company_id, classification_id)`` so the same
    logical column-classification proposal always yields the same
    ref_id — preserves replay stability across machines. Mirrors
    :func:`_edge_ref_uuid` (L3), :func:`_check_ref_uuid` (L7),
    :func:`_impact_ref_uuid` (L4), and :func:`_type_ref_uuid` (L5)
    shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL,
        f"wormbase:column_classification:{company_id}:{classification_id}",
    )


async def confirm_column_classification(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    classification_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``column_classification_confirmed`` for an admin-confirmed proposal.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_column_classifications fold maps the new entry to
    ``state = "confirmed"`` on the (company_id, classification_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3 :func:`confirm_lineage_edge`
    + L7 :func:`confirm_quality_check` + L4
    :func:`confirm_schema_impact` + L5 :func:`confirm_semantic_type`
    shape.
    """
    payload = ColumnClassificationConfirmedPayload(
        classification_id=classification_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="column_classification_confirmed",
        ref_id=_classification_ref_uuid(company_id, classification_id),
        reason=(
            f"confirm column classification {classification_id} via "
            f"dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{ColumnClassificationConfirmedPayload.kind}",
        args=args,
        result_ref=classification_id,
        payload_cls=ColumnClassificationConfirmedPayload,
        rationale=(
            f"column classification confirmed by admin "
            f"{confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_column_classification(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    classification_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``column_classification_rejected`` for an admin-rejected proposal.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_column_classifications fold maps the new entry to
    ``state = "rejected"`` on the (company_id, classification_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`ColumnClassificationRejectedPayload` — payload validation
    surfaces invalid values as a verify failure (PEVR rolls back). The
    valid enum is {false_positive, low_value, wrong_level,
    out_of_scope, other}; HTTP layer enforces the same set at the
    boundary. The L6-specific 5th value is ``wrong_level`` (distinct
    from L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``).
    """
    payload = ColumnClassificationRejectedPayload(
        classification_id=classification_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="column_classification_rejected",
        ref_id=_classification_ref_uuid(company_id, classification_id),
        reason=(
            f"reject column classification {classification_id} "
            f"(reason={reason}) via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{ColumnClassificationRejectedPayload.kind}",
        args=args,
        result_ref=classification_id,
        payload_cls=ColumnClassificationRejectedPayload,
        rationale=(
            f"column classification rejected by admin "
            f"{rejected_by_person_id} (reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L8 Sub-wave C (2026-06-07) — entity-stitch admin actions.
#
# ``confirm_entity_stitch`` + ``reject_entity_stitch`` mirror the
# L3/L7/L4/L5/L6 confirm/reject PEVR helpers. The
# projection_entity_stitches fold (v026) flips the state column on
# the (company_id, stitch_id) row when a new entry lands.
#
# Both helpers use a uuid5 derivation over the (company_id, stitch_id)
# pair so the ref_id stays deterministic + replay-stable. The
# stitch_id itself is a SHA-256-derived hex string from
# :func:`wormbase_agent_gateway.entity_stitch.make_stitch_id`.
# ---------------------------------------------------------------------------


def _stitch_ref_uuid(
    company_id: UUID, stitch_id: str,
) -> UUID:
    """Deterministic ref_id for entity-stitch PEVR cycles.

    Derives a uuid5 over ``(company_id, stitch_id)`` so the same
    logical entity-stitch proposal always yields the same ref_id —
    preserves replay stability across machines. Mirrors
    :func:`_edge_ref_uuid` (L3), :func:`_check_ref_uuid` (L7),
    :func:`_impact_ref_uuid` (L4), :func:`_type_ref_uuid` (L5), and
    :func:`_classification_ref_uuid` (L6) shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL,
        f"wormbase:entity_stitch:{company_id}:{stitch_id}",
    )


async def confirm_entity_stitch(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    stitch_id: str,
    confirmed_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``entity_stitch_confirmed`` for an admin-confirmed proposal.

    Forward-only: re-confirmation after rejection emits a NEW entry.
    The projection_entity_stitches fold maps the new entry to
    ``state = "confirmed"`` on the (company_id, stitch_id) row.

    ``confirmed_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3 :func:`confirm_lineage_edge`
    + L7 :func:`confirm_quality_check` + L4 :func:`confirm_schema_impact`
    + L5 :func:`confirm_semantic_type` + L6
    :func:`confirm_column_classification` shape.
    """
    payload = EntityStitchConfirmedPayload(
        stitch_id=stitch_id,
        confirmed_by_person_id=confirmed_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="entity_stitch_confirmed",
        ref_id=_stitch_ref_uuid(company_id, stitch_id),
        reason=(
            f"confirm entity stitch {stitch_id} via "
            f"dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{EntityStitchConfirmedPayload.kind}",
        args=args,
        result_ref=stitch_id,
        payload_cls=EntityStitchConfirmedPayload,
        rationale=(
            f"entity stitch confirmed by admin "
            f"{confirmed_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_entity_stitch(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    stitch_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``entity_stitch_rejected`` for an admin-rejected proposal.

    Forward-only: re-rejection after re-confirmation emits a NEW entry.
    The projection_entity_stitches fold maps the new entry to
    ``state = "rejected"`` on the (company_id, stitch_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`EntityStitchRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back). The valid
    enum is {false_positive, low_value, wrong_pairing, out_of_scope,
    other}; HTTP layer enforces the same set at the boundary. The
    L8-specific 5th value is ``wrong_pairing`` (distinct from L6's
    ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled`` and
    L7's ``wrong_threshold``).
    """
    payload = EntityStitchRejectedPayload(
        stitch_id=stitch_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="entity_stitch_rejected",
        ref_id=_stitch_ref_uuid(company_id, stitch_id),
        reason=(
            f"reject entity stitch {stitch_id} "
            f"(reason={reason}) via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{EntityStitchRejectedPayload.kind}",
        args=args,
        result_ref=stitch_id,
        payload_cls=EntityStitchRejectedPayload,
        rationale=(
            f"entity stitch rejected by admin "
            f"{rejected_by_person_id} (reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L1 Sub-wave C (2026-06-08) — source-candidate admin actions.
#
# ``promote_source_candidate`` + ``reject_source_candidate`` mirror the
# L3/L7/L4/L5/L6/L8 confirm/reject PEVR helpers. The
# projection_source_candidates fold (v027) flips the state column on
# the (company_id, candidate_id) row when a new entry lands.
#
# Both helpers use a uuid5 derivation over the (company_id, candidate_id)
# pair so the ref_id stays deterministic + replay-stable. The
# candidate_id itself is a SHA-256-derived hex string from
# :func:`wormbase_ledger.make_candidate_id`.
#
# **Promote dual-write architecture**: Unlike the L3-L8 confirm helpers,
# the L1 promote endpoint dual-writes within a single admin action:
#
#   1. ``source_candidate_promoted`` — the audit entry capturing the
#      admin's decision; this helper writes it.
#   2. ``source_proposed`` — the downstream source-pipeline entry that
#      kicks off the existing 4-stage source-builder flow (proposed →
#      confirmed → connected → profiled). The HTTP handler triggers
#      this via the existing ``SourceBuilder.propose(...)`` flow and
#      threads the resulting source-pipeline correlation id back into
#      this helper's ``downstream_source_proposed_id`` arg so the
#      ``source_candidate_promoted`` payload links the two ledger
#      entries.
#
# The two writes are sequential (not transactional) in Wave 1; per spec
# §8 Phase 2 candidates: a future wave decouples via a
# ``SourceCandidatePromoted → SourceProposed`` Reactivity (mirrors the
# agent-gateway's ``OutcomeToTemplatePromotion``).
# ---------------------------------------------------------------------------


def _source_candidate_ref_uuid(
    company_id: UUID, candidate_id: str,
) -> UUID:
    """Deterministic ref_id for source-candidate PEVR cycles.

    Derives a uuid5 over ``(company_id, candidate_id)`` so the same
    logical source-candidate promotion/rejection always yields the
    same ref_id — preserves replay stability across machines. Mirrors
    :func:`_edge_ref_uuid` (L3), :func:`_check_ref_uuid` (L7),
    :func:`_impact_ref_uuid` (L4), :func:`_type_ref_uuid` (L5),
    :func:`_classification_ref_uuid` (L6), and
    :func:`_stitch_ref_uuid` (L8) shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL,
        f"wormbase:source_candidate:{company_id}:{candidate_id}",
    )


async def promote_source_candidate(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    candidate_id: str,
    promoted_by_person_id: str,
    downstream_source_proposed_id: str | None = None,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``source_candidate_promoted`` for an admin-promoted candidate.

    Forward-only: re-promotion after rejection emits a NEW entry. The
    projection_source_candidates fold maps the new entry to
    ``state = "promoted"`` on the (company_id, candidate_id) row.

    ``promoted_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3 :func:`confirm_lineage_edge`
    + L7 :func:`confirm_quality_check` + L4
    :func:`confirm_schema_impact` + L5 :func:`confirm_semantic_type`
    + L6 :func:`confirm_column_classification` + L8
    :func:`confirm_entity_stitch` shape.

    ``downstream_source_proposed_id`` links this promotion entry to
    the downstream source-pipeline ``source_proposed`` entry the HTTP
    handler emits via :class:`SourceBuilder`. When None, the link is
    not recorded (e.g. the dual-write path is disabled or the
    downstream propose failed); the audit entry still lands. The
    HTTP handler is responsible for the dual-write orchestration —
    this helper writes only the L1 audit entry per the
    forward-only / additive-only schema-evolution doctrine.
    """
    payload = SourceCandidatePromotedPayload(
        candidate_id=candidate_id,
        promoted_by_person_id=promoted_by_person_id,
        downstream_source_proposed_id=downstream_source_proposed_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="source_candidate_promoted",
        ref_id=_source_candidate_ref_uuid(company_id, candidate_id),
        reason=(
            f"promote source candidate {candidate_id} via "
            f"dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(promoted_by_person_id),
        tool=f"emit_{SourceCandidatePromotedPayload.kind}",
        args=args,
        result_ref=candidate_id,
        payload_cls=SourceCandidatePromotedPayload,
        rationale=(
            f"source candidate promoted by admin "
            f"{promoted_by_person_id}"
            f"{f' (downstream={downstream_source_proposed_id})' if downstream_source_proposed_id else ''}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_source_candidate(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    candidate_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``source_candidate_rejected`` for an admin-rejected candidate.

    Forward-only: re-rejection after re-promotion emits a NEW entry.
    The projection_source_candidates fold maps the new entry to
    ``state = "rejected"`` on the (company_id, candidate_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`SourceCandidateRejectedPayload` — payload validation
    surfaces invalid values as a verify failure (PEVR rolls back).
    The valid enum is {duplicate, false_positive, low_value,
    out_of_scope, other}; HTTP layer enforces the same set at the
    boundary. The L1-specific 5th value is ``duplicate`` (distinct
    from L8's ``wrong_pairing``, L6's ``wrong_level``, L5's
    ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``) — reflects that the most common reject
    reason at triage is "we already have this source / something
    equivalent."
    """
    payload = SourceCandidateRejectedPayload(
        candidate_id=candidate_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="source_candidate_rejected",
        ref_id=_source_candidate_ref_uuid(company_id, candidate_id),
        reason=(
            f"reject source candidate {candidate_id} "
            f"(reason={reason}) via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{SourceCandidateRejectedPayload.kind}",
        args=args,
        result_ref=candidate_id,
        payload_cls=SourceCandidateRejectedPayload,
        rationale=(
            f"source candidate rejected by admin "
            f"{rejected_by_person_id} (reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# L2 Sub-wave C (2026-06-09) — catalog-drift admin actions.
#
# ``acknowledge_catalog_drift`` + ``reject_catalog_drift`` mirror the
# L1/L3/L7/L4/L5/L6/L8 confirm-or-promote-and-reject PEVR helpers
# but with one important divergence: L2 uses ``acknowledge`` rather
# than ``confirm`` or ``promote``. Per the L2 ledger doctrine (see
# ``CatalogDriftAcknowledgedPayload`` docstring), acknowledgment is a
# **no-op record** — no downstream pipeline trigger, no cross-axis
# effect. The catalog-mirror's W5a Reactivity already observed the
# drift via ``external_catalog_drift_detected``; L2's job is just to
# record the human-in-the-loop disposition.
#
# The projection_catalog_drifts fold (v028) flips the state column
# on the (company_id, drift_id) row when a new entry lands:
#
#   * catalog_drift_proposed   → state = "proposed"
#   * catalog_drift_acknowledged → state = "acknowledged"
#   * catalog_drift_rejected     → state = "rejected"
#
# Both helpers use a uuid5 derivation over (company_id, drift_id)
# so the ref_id stays deterministic + replay-stable. The drift_id
# itself is a SHA-256-derived hex string from
# :func:`wormbase_ledger.make_drift_id`.
# ---------------------------------------------------------------------------


def _catalog_drift_ref_uuid(
    company_id: UUID, drift_id: str,
) -> UUID:
    """Deterministic ref_id for catalog-drift PEVR cycles.

    Derives a uuid5 over ``(company_id, drift_id)`` so the same
    logical catalog-drift acknowledgment / rejection always yields
    the same ref_id — preserves replay stability across machines.
    Mirrors :func:`_source_candidate_ref_uuid` (L1),
    :func:`_stitch_ref_uuid` (L8), and the L3-L7 shape.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL,
        f"wormbase:catalog_drift:{company_id}:{drift_id}",
    )


async def acknowledge_catalog_drift(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    drift_id: str,
    acknowledged_by_person_id: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``catalog_drift_acknowledged`` for an admin-acknowledged drift.

    Forward-only: re-acknowledgment after rejection emits a NEW entry.
    The projection_catalog_drifts fold maps the new entry to
    ``state = "acknowledged"`` on the (company_id, drift_id) row.

    ``acknowledged_by_person_id`` is threaded by the admin surface from
    the dashboard ``getCurrentPerson`` lookup — never the bare admin
    token or a placeholder. Mirrors the L3 :func:`confirm_lineage_edge`
    + L7 :func:`confirm_quality_check` + L4
    :func:`confirm_schema_impact` + L5 :func:`confirm_semantic_type`
    + L6 :func:`confirm_column_classification` + L8
    :func:`confirm_entity_stitch` + L1 :func:`promote_source_candidate`
    shape.

    Unlike L1's promote (which dual-writes a downstream source_proposed)
    and L3-L8's confirm (which feeds peer-axis chains), L2's
    acknowledgment is a no-op record — no downstream pipeline trigger,
    no cross-axis effect. The catalog-mirror's W5a Reactivity already
    observed the drift; L2 just records the human disposition.
    """
    payload = CatalogDriftAcknowledgedPayload(
        drift_id=drift_id,
        acknowledged_by_person_id=acknowledged_by_person_id,
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="catalog_drift_acknowledged",
        ref_id=_catalog_drift_ref_uuid(company_id, drift_id),
        reason=(
            f"acknowledge catalog drift {drift_id} via "
            f"dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(acknowledged_by_person_id),
        tool=f"emit_{CatalogDriftAcknowledgedPayload.kind}",
        args=args,
        result_ref=drift_id,
        payload_cls=CatalogDriftAcknowledgedPayload,
        rationale=(
            f"catalog drift acknowledged by admin "
            f"{acknowledged_by_person_id}"
            f"{f': {notes}' if notes else ''}"
        ),
    )


async def reject_catalog_drift(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    drift_id: str,
    rejected_by_person_id: str,
    reason: str,
    notes: str | None = None,
) -> WriteResult:
    """Emit ``catalog_drift_rejected`` for an admin-rejected drift.

    Forward-only: re-rejection after re-acknowledgment emits a NEW
    entry. The projection_catalog_drifts fold maps the new entry to
    ``state = "rejected"`` on the (company_id, drift_id) row.

    ``reason`` is the strict 5-value enum on
    :class:`CatalogDriftRejectedPayload` — payload validation surfaces
    invalid values as a verify failure (PEVR rolls back). The valid
    enum is {false_positive, inconsequential, expected_change,
    out_of_scope, other}; HTTP layer enforces the same set at the
    boundary. The L2-specific 5th value is ``expected_change``
    (distinct from L1's ``duplicate``, L8's ``wrong_pairing``, L6's
    ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled``
    and L7's ``wrong_threshold``) — reflects that the drift was real
    but a known intentional change (e.g. planned schema migration).
    """
    payload = CatalogDriftRejectedPayload(
        drift_id=drift_id,
        rejected_by_person_id=rejected_by_person_id,
        reason=reason,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="catalog_drift_rejected",
        ref_id=_catalog_drift_ref_uuid(company_id, drift_id),
        reason=(
            f"reject catalog drift {drift_id} "
            f"(reason={reason}) via dashboard admin action"
            f"{f' — {notes}' if notes else ''}"
        ),
        proposed_by=str(rejected_by_person_id),
        tool=f"emit_{CatalogDriftRejectedPayload.kind}",
        args=args,
        result_ref=drift_id,
        payload_cls=CatalogDriftRejectedPayload,
        rationale=(
            f"catalog drift rejected by admin "
            f"{rejected_by_person_id} (reason={reason})"
            f"{f': {notes}' if notes else ''}"
        ),
    )


# ---------------------------------------------------------------------------
# Onboarding Sub-wave C (2026-05-30) — domain pack + co-admin invite.
# ---------------------------------------------------------------------------


async def select_domain_pack(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    pack_id: str,
    selected_by_person_id: UUID,
    notes: str | None = None,
):
    """Pick + seed a domain pack — Onboarding Sub-wave C.

    Delegates to ``onboarding.pack_seeder.seed_pack`` which writes:

    1. ``domain_pack_selected`` parent PEVR cycle (the audit anchor)
    2. N × ``emit_domain_registered`` execute entries (one per pack
       domain)
    3. N × ``emit_policy_applied`` execute entries (one per pack
       policy)

    Idempotent: re-running on the same tenant short-circuits to the
    prior selection. Returns ``PackSeedReport`` with ``already_seeded``
    flag set when the no-op path fires.

    Args:
        ledger: any LedgerLike with the canonical write surface.
        company_id: tenant UUID (the X-Tenant-Slug header resolves to this).
        pack_id: one of {generic, saas, marketplace, fintech}; loader
            raises ``PackLoadError`` on unknown ids.
        selected_by_person_id: admin doing the pick (audit attribution).
        notes: optional free-text audit prose.

    Raises:
        PackLoadError: when ``pack_id`` does not exist on disk.
    """
    # Late-binding import to avoid a top-of-module circular between
    # write_actions and the onboarding package (which depends on
    # wormbase_ledger payloads, which write_actions imports).
    from .onboarding.pack_seeder import seed_pack

    return await seed_pack(
        ledger,
        company_id=company_id,
        pack_id=pack_id,
        selected_by_person_id=selected_by_person_id,
        notes=notes,
    )


async def invite_person(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    invited_by_person_id: UUID,
    invitee_email: str | None = None,
    invitee_platform_id: str | None = None,
    role_intent: str = "member",
    notes: str | None = None,
) -> WriteResult:
    """Emit a ``person_invited`` PEVR cycle — Onboarding Sub-wave C.

    At least one of ``invitee_email`` / ``invitee_platform_id`` MUST
    be supplied. The handler enforces this with HTTP 400; this helper
    raises ``ValueError`` for the same condition (defense in depth at
    the write-action boundary).

    The actual ``person_proposed`` → ``person_confirmed`` lifecycle
    fires when the invitee accepts the signed acceptance URL — this
    entry only records the invite intent + audit trail.
    """
    if not invitee_email and not invitee_platform_id:
        raise ValueError(
            "invite_person requires at least one of invitee_email or "
            "invitee_platform_id"
        )
    if role_intent not in {"admin", "member", "observer"}:
        raise ValueError(
            f"invalid role_intent {role_intent!r}; expected one of "
            f"['admin', 'member', 'observer']"
        )

    payload = PersonInvitedPayload(
        invitee_email=invitee_email,
        invitee_platform_id=invitee_platform_id,
        invited_by_person_id=invited_by_person_id,
        role_intent=role_intent,  # type: ignore[arg-type]
        notes=notes,
    )
    args = payload.model_dump(mode="json")

    invite_ref = uuid4()
    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="person_invited",
        ref_id=invite_ref,
        reason=(
            f"invite co-admin via {invitee_email or invitee_platform_id} "
            f"as role_intent={role_intent}"
        ),
        proposed_by=str(invited_by_person_id),
        tool=f"emit_{PersonInvitedPayload.kind}",
        args=args,
        result_ref=str(invite_ref),
        payload_cls=PersonInvitedPayload,
        rationale=(
            f"person invited by admin {invited_by_person_id} "
            f"as role_intent={role_intent}"
        ),
    )


# ---------------------------------------------------------------------------
# Onboarding Sub-wave D (2026-05-30) — confirmBusinessDef graduation.
# ---------------------------------------------------------------------------


class ConceptProposalNotFound(LookupError):
    """Raised when ``confirm_concept`` cannot resolve a term to a
    prior ``concept_proposed`` entry. Mapped to HTTP 404 at the
    handler boundary.
    """


async def _lookup_concept_id_by_term(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    term: str,
) -> UUID:
    """Resolve a business-definition ``term`` to its ``concept_id``.

    Reads back over the company's ledger and returns the most recent
    ``concept_proposed`` execute entry whose ``name`` (case-insensitive
    + whitespace-trimmed) matches ``term``.

    Raises:
        ConceptProposalNotFound: when no matching proposal exists.
    """
    rows = await ledger.fetch(company_id)
    needle = term.strip().casefold()
    latest_match: tuple[int, UUID] | None = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        if tool != f"emit_{ConceptProposedPayload.kind}":
            continue
        args = payload.get("args") or {}
        name = (args.get("name") or "").strip().casefold()
        if name != needle:
            continue
        concept_id_raw = args.get("concept_id")
        if not concept_id_raw:
            continue
        try:
            cid = UUID(str(concept_id_raw))
        except (ValueError, TypeError):
            continue
        seq = row.get("seq") or 0
        if latest_match is None or seq > latest_match[0]:
            latest_match = (seq, cid)
    if latest_match is None:
        raise ConceptProposalNotFound(
            f"no concept_proposed entry found for term {term!r} "
            f"in tenant {company_id}"
        )
    return latest_match[1]


async def confirm_concept(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    term: str,
    confirmed_by_person_id: UUID,
) -> tuple[UUID, WriteResult]:
    """Confirm a worm-proposed business definition — Sub-wave D graduation.

    Looks the ``concept_id`` up from the most recent
    ``concept_proposed`` execute entry matching ``term``, then emits a
    real ``concept_confirmed`` PEVR cycle. No new KIND_REGISTRY entry —
    this rides the existing kind (KIND_REGISTRY 111 stays unchanged).

    The lookup is case-insensitive and whitespace-trimmed against the
    proposal's ``name`` field. When the term has multiple proposals,
    the latest (by ledger ``seq``) wins.

    Returns ``(concept_id, WriteResult)``.

    Raises:
        ConceptProposalNotFound: mapped to HTTP 404 at the boundary.
        ValueError: empty term.
    """
    cleaned = (term or "").strip()
    if not cleaned:
        raise ValueError("term must be non-empty")

    concept_id = await _lookup_concept_id_by_term(
        ledger,
        company_id,
        term=cleaned,
    )

    payload = ConceptConfirmedPayload(
        concept_id=concept_id,
        confirmed_by_person=confirmed_by_person_id,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="concept_confirmed",
        ref_id=concept_id,
        reason=(
            f"confirm business definition {cleaned!r} "
            f"(concept_id={concept_id})"
        ),
        proposed_by=str(confirmed_by_person_id),
        tool=f"emit_{ConceptConfirmedPayload.kind}",
        args=args,
        result_ref=str(concept_id),
        payload_cls=ConceptConfirmedPayload,
        rationale=(
            f"business definition confirmed by admin "
            f"{confirmed_by_person_id} via Tier 2 onboarding"
        ),
    )
    return concept_id, result
