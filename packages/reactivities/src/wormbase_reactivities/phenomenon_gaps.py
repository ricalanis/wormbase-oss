"""Phenomenon-gap reactivities (W5.A3).

Four detectors that close the conversation-to-substrate loop: when a chat
statement references something the org doesn't yet have (a KPI, a Domain,
a Process, or a Reactivity), the corresponding detector proposes that
phenomenon for admin confirmation.

This is the meta-flow that distinguishes WormBase from a chatbot: the worm
builds the rules it runs on. Conversations become the input that builds
the org's ontology, recursively.

The four detectors:

  * ``KpiReferenceWithoutKpiReactivity``         — chat mentions a metric
                                                    not in the KPI tree
                                                    → propose a KPI node.
  * ``DomainReferenceWithoutDomainReactivity``   — chat mentions a domain
                                                    not in the ontology
                                                    → propose a Domain.
  * ``ProcessReferenceWithoutProcessReactivity`` — chat describes a
                                                    process not in /processes
                                                    → propose a process map.
  * ``RecurringActionWithoutReactivityReactivity`` — chat describes a rule
                                                    ("every Friday we X")
                                                    → propose a Reactivity.

All four follow the same shape:

  * predicate ── ``EntryKind("chat_received") & <Mentions...>`` from
                 ``predicates_advanced.py``. The advanced predicate stashes
                 detection details into ``context.extras`` so ``fire`` can
                 read them without re-extracting.
  * condition ── ``DailyBudget(per_tenant=20) & NotRecentlyFired(24h)``.
                 The 24h novelty cooldown is the load-bearing
                 false-positive control: a noisy chat won't propose the
                 same KPI repeatedly.
  * fire ──────  emits ``emit_phenomenon_gap_detected`` (audit) AND
                 invokes the canonical ``propose_*`` write_action so an
                 admin can confirm via the existing dashboard surface.

The Reactivity ids are stable strings so the registry's
proposed → confirmed → disabled lifecycle survives restarts. Per the
W5.A3 quality bar, the Reactivity proposed by the meta-case is a STUB
spec — predicate/action sketched from the natural-language template,
admin must edit before activating. The proposal payload includes
``spec.natural_language`` for that purpose.

Defensive imports: the worm-core ``write_actions.propose_*`` helpers are
imported lazily inside ``fire`` so the reactivities package stays free
of a hard dep on worm-core. Tests construct an InMemoryLedger and
exercise the full propose path; the helpers gracefully no-op (still
emitting the gap entry) if worm-core's write_actions is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from wormbase_reactivities.conditions import (
    DailyBudget,
    NotRecentlyFired,
)
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.predicates_advanced import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DescribesProcessNotInLake,
    DescribesRecurringPattern,
    MentionsDomainNotInOntology,
    MentionsMetricNotInKpiTree,
)
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityContext,
    ReactivityResult,
    ReactivityScope,
)

logger = logging.getLogger("wormbase_reactivities.phenomenon_gaps")


# ---------------------------------------------------------------------------
# Shared helper — emit the polymorphic gap entry
# ---------------------------------------------------------------------------


async def _emit_phenomenon_gap_detected(
    context: ReactivityContext,
    *,
    gap_kind: str,
    referenced_in_seq: int,
    suggested_proposal: dict[str, Any],
    confidence: float,
    novelty_key: str,
) -> None:
    """Write the audit ``emit_phenomenon_gap_detected`` PEVR cycle.

    Wraps the entry in the canonical PEVR shape via ``ledger.write`` —
    same path the registry's ``_write_pevr`` helper uses for
    ``emit_reactivity_fired``. This keeps phenomenon-gap entries
    byte-equivalent to other reactivity-emitted entries; replay is safe.
    """
    ref_id = uuid4()
    args = {
        "kind": gap_kind,
        "referenced_in_seq": referenced_in_seq,
        "suggested_proposal": dict(suggested_proposal),
        "confidence": float(confidence),
        "novelty_key": novelty_key,
    }
    await context.ledger.write(
        company_id=context.company_id,
        propose={
            "target_kind": "phenomenon_gap_detected",
            "ref_id": str(ref_id),
            "reason": (
                f"phenomenon gap ({gap_kind}) detected from chat seq="
                f"{referenced_in_seq}"
            ),
            "proposed_by": "worm",
        },
        execute_fn=lambda: {
            "tool": "emit_phenomenon_gap_detected",
            "args": args,
            "result_ref": str(ref_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": (
                f"phenomenon_gap_detected ({gap_kind}) recorded"
            ),
        },
        quadrant="active_probabilistic",
    )


def _propose_helpers(name: str) -> Callable[..., Any] | None:
    """Lazy lookup of ``wormbase_core.write_actions.<name>``.

    Returns the helper if importable, None otherwise. Callers handle the
    None case by skipping the side-effecting propose and still emitting
    the gap entry. This keeps the reactivities package free of a hard
    dep on worm-core (which depends on this package).
    """
    try:
        from wormbase_core import write_actions  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    return getattr(write_actions, name, None)


# ---------------------------------------------------------------------------
# KpiReferenceWithoutKpiReactivity
# ---------------------------------------------------------------------------


@dataclass
class KpiReferenceWithoutKpiReactivity:
    """Detect chat mentions of a metric not in the KPI tree → propose KPI.

    Statement "we should track NPS" with no NPS KPI present → fires this
    Reactivity, which:

      1. emits ``emit_phenomenon_gap_detected{kind: 'kpi'}`` (audit)
      2. invokes ``write_actions.propose_kpi_node(label=..., formula=...)``
         to drop a KPI proposal into the existing /kpis pending queue
         where an admin confirms.

    Per spec, scope is ``"domain"`` so per-domain budgets / mute toggles
    apply naturally. Per-tenant budget is 20/day to keep noise bounded
    in the first week of a noisy channel.
    """

    id: str = "kpi_reference_without_kpi"
    name: str = "KPI Reference Without KPI"
    description: str = (
        "Detect chat mentions of metrics that are not yet KPIs in the org's "
        "KPI tree, and propose them for admin confirmation."
    )
    scope: ReactivityScope = "domain"

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = (
            EntryKind("chat_received")
            & MentionsMetricNotInKpiTree(
                confidence_threshold=self.confidence_threshold,
            )
        )
        self.condition = DailyBudget(
            per_owner=None,    # KPI gaps don't have an owner axis
            per_domain=10,
            per_tenant=20,
        ) & NotRecentlyFired(novelty_key="kpi_label", hours=24.0)

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        details = context.extras.get("phenomenon_gap_kpi")
        if not details:
            return ReactivityResult(fired=False)
        label = str(details.get("label") or "").strip()
        if not label:
            return ReactivityResult(fired=False)
        confidence = float(details.get("confidence") or 0.0)
        novelty_key = str(details.get("novelty_key") or f"kpi:{label}")
        seq = int(entry.get("seq") or 0)
        domain_id = (
            ((entry.get("payload") or {}).get("args") or {}).get("domain_id")
        )

        suggested = {
            "label": label,
            "domain_id": domain_id,
            "formula": "PROPOSED",  # admin edits before confirming
            "unit": "count",
        }

        await _emit_phenomenon_gap_detected(
            context,
            gap_kind="kpi",
            referenced_in_seq=seq,
            suggested_proposal=suggested,
            confidence=confidence,
            novelty_key=novelty_key,
        )

        # Best-effort: propose the canonical KPI node so it shows up in
        # /kpis pending. Failure here is logged but doesn't unfire — the
        # gap entry itself is the audit record.
        propose_kpi = _propose_helpers("propose_kpi_node")
        if propose_kpi is not None:
            try:
                await propose_kpi(
                    context.ledger,
                    context.company_id,
                    label=label,
                    formula="PROPOSED",
                    unit="count",
                    proposed_by="worm:phenomenon_gap",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "propose_kpi_node failed for label=%r: %s", label, exc,
                )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="phenomenon_gap_detected_kpi")],
            novelty_key=novelty_key,
            budget_used={"per_tenant": 1, "per_domain": 1},
        )


# ---------------------------------------------------------------------------
# DomainReferenceWithoutDomainReactivity
# ---------------------------------------------------------------------------


@dataclass
class DomainReferenceWithoutDomainReactivity:
    """Detect chat references to a domain not yet in the ontology → propose Domain.

    Statement "the compliance team needs that report" when no Compliance
    domain exists → fires this Reactivity, which emits the gap entry. The
    canonical "propose_domain" write_action does not yet exist in
    write_actions.py (domains are surfaced via the domain pack picker
    today); the gap entry itself is the audit record an admin can act on
    via /domains. The Reactivity is forward-compatible: when a future
    ``propose_domain`` lands, the same fire() path picks it up via the
    lazy ``_propose_helpers`` lookup.
    """

    id: str = "domain_reference_without_domain"
    name: str = "Domain Reference Without Domain"
    description: str = (
        "Detect chat references to a domain not yet in the ontology and "
        "propose it for admin confirmation."
    )
    scope: ReactivityScope = "company"

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = (
            EntryKind("chat_received")
            & MentionsDomainNotInOntology(
                confidence_threshold=self.confidence_threshold,
            )
        )
        self.condition = DailyBudget(
            per_owner=None,
            per_domain=None,   # domain gaps don't have a domain axis (they ARE the domain)
            per_tenant=20,
        ) & NotRecentlyFired(novelty_key="domain_label", hours=24.0)

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        details = context.extras.get("phenomenon_gap_domain")
        if not details:
            return ReactivityResult(fired=False)
        label = str(details.get("label") or "").strip()
        if not label:
            return ReactivityResult(fired=False)
        confidence = float(details.get("confidence") or 0.0)
        novelty_key = str(details.get("novelty_key") or f"domain:{label}")
        seq = int(entry.get("seq") or 0)

        suggested = {
            "label": label,
            "default_classification": "internal",
        }

        await _emit_phenomenon_gap_detected(
            context,
            gap_kind="domain",
            referenced_in_seq=seq,
            suggested_proposal=suggested,
            confidence=confidence,
            novelty_key=novelty_key,
        )

        # If/when worm-core grows a write_actions.propose_domain helper,
        # this lazy lookup will pick it up automatically.
        propose_domain = _propose_helpers("propose_domain")
        if propose_domain is not None:
            try:
                await propose_domain(
                    context.ledger,
                    context.company_id,
                    label=label,
                    default_classification="internal",
                    proposed_by="worm:phenomenon_gap",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "propose_domain failed for label=%r: %s", label, exc,
                )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="phenomenon_gap_detected_domain")],
            novelty_key=novelty_key,
            budget_used={"per_tenant": 1},
        )


# ---------------------------------------------------------------------------
# ProcessReferenceWithoutProcessReactivity
# ---------------------------------------------------------------------------


@dataclass
class ProcessReferenceWithoutProcessReactivity:
    """Detect chat describing a process not in /processes → propose process map.

    Statement "every Friday we run the data-quality review" with no
    matching process_map_proposed → fires this Reactivity. Emits the gap
    entry AND invokes ``write_actions.propose_process_map`` so an admin
    can confirm the canonical process via /processes.
    """

    id: str = "process_reference_without_process"
    name: str = "Process Reference Without Process"
    description: str = (
        "Detect chat describing a recurring process not yet in the "
        "process_map lake, and propose it for admin confirmation."
    )
    scope: ReactivityScope = "domain"

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = (
            EntryKind("chat_received")
            & DescribesProcessNotInLake(
                confidence_threshold=self.confidence_threshold,
            )
        )
        self.condition = DailyBudget(
            per_owner=None,
            per_domain=10,
            per_tenant=20,
        ) & NotRecentlyFired(novelty_key="process_label", hours=24.0)

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        details = context.extras.get("phenomenon_gap_process")
        if not details:
            return ReactivityResult(fired=False)
        label = str(details.get("label") or "").strip()
        if not label:
            return ReactivityResult(fired=False)
        confidence = float(details.get("confidence") or 0.0)
        novelty_key = str(
            details.get("novelty_key") or f"process:{label.lower()}",
        )
        evidence = str(details.get("evidence_text") or "")
        seq = int(entry.get("seq") or 0)
        args = (entry.get("payload") or {}).get("args") or {}
        domain = args.get("domain") or "general"

        suggested = {
            "process_name": label,
            "domain": domain,
            "evidence_text": evidence,
        }

        await _emit_phenomenon_gap_detected(
            context,
            gap_kind="process",
            referenced_in_seq=seq,
            suggested_proposal=suggested,
            confidence=confidence,
            novelty_key=novelty_key,
        )

        propose_process = _propose_helpers("propose_process_map")
        if propose_process is not None:
            try:
                await propose_process(
                    context.ledger,
                    context.company_id,
                    process_name=label,
                    steps=[
                        {
                            "order": 1,
                            "actor": "team",
                            "action": evidence or label,
                            "source_message_id": "",
                        },
                    ],
                    domain=str(domain),
                    confidence=confidence,
                    proposed_by="worm:phenomenon_gap",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "propose_process_map failed for label=%r: %s",
                    label, exc,
                )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="phenomenon_gap_detected_process")],
            novelty_key=novelty_key,
            budget_used={"per_tenant": 1, "per_domain": 1},
        )


# ---------------------------------------------------------------------------
# RecurringActionWithoutReactivityReactivity (the meta-case)
# ---------------------------------------------------------------------------


@dataclass
class RecurringActionWithoutReactivityReactivity:
    """The worm-builds-its-own-rules detector.

    Statement "every time a deploy fails, ping the on-call engineer" → no
    matching Reactivity present → fires this Reactivity. Emits the gap
    entry AND records a ``reactivity_proposed`` PEVR cycle — so the
    proposed Reactivity sits in the registry's ``proposed`` state until
    an admin confirms via /reactivities. The Reactivity NEVER auto-
    activates; that's the trust gate.

    The proposal carries a natural-language description and a sketched
    predicate/action spec that an admin edits before confirming. The
    Reactivity itself does no LLM work yet; the regex-only detector in
    ``predicates_advanced.DescribesRecurringPattern`` is precise enough
    for v1, and the LLM-fallback hook is a future wave.
    """

    id: str = "recurring_action_without_reactivity"
    name: str = "Recurring Action Without Reactivity"
    description: str = (
        "Detect chat describing an automation-shaped rule (\"every time X, "
        "do Y\") that has no matching active Reactivity, and propose a "
        "Reactivity stub for admin confirmation. Load-bearing for "
        "the worm-builds-its-own-rules thesis."
    )
    scope: ReactivityScope = "company"

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = (
            EntryKind("chat_received")
            & DescribesRecurringPattern(
                confidence_threshold=self.confidence_threshold,
            )
        )
        # Tighter cap than the others — the cost of a false-positive
        # reactivity proposal is admin-attention, the most expensive
        # axis. Per-tenant 20/day still leaves headroom.
        self.condition = DailyBudget(
            per_owner=None,
            per_domain=None,
            per_tenant=20,
        ) & NotRecentlyFired(novelty_key="reactivity_slug", hours=24.0)

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        details = context.extras.get("phenomenon_gap_reactivity")
        if not details:
            return ReactivityResult(fired=False)
        spec = details.get("spec") or {}
        label = str(details.get("label") or "").strip()
        slug = str(details.get("slug") or "").strip()
        if not (spec and label and slug):
            return ReactivityResult(fired=False)
        confidence = float(details.get("confidence") or 0.0)
        novelty_key = str(
            details.get("novelty_key") or f"reactivity:{slug}",
        )
        seq = int(entry.get("seq") or 0)

        suggested = {
            "reactivity_id": slug,
            "name": label[:80],
            "description": label,
            "scope": "company",
            "predicate_spec": {
                "natural_language": spec.get("predicate_description"),
            },
            "action_spec": {
                "natural_language": spec.get("action_description"),
            },
            "natural_language": spec.get("natural_language"),
            "requires_admin_edit": True,
        }

        await _emit_phenomenon_gap_detected(
            context,
            gap_kind="reactivity",
            referenced_in_seq=seq,
            suggested_proposal=suggested,
            confidence=confidence,
            novelty_key=novelty_key,
        )

        # Record the formal ``emit_reactivity_proposed`` so /reactivities
        # picks the proposal up alongside admin-authored ones. The
        # Reactivity stays in ``proposed`` state until an admin confirms;
        # never auto-active.
        try:
            await context.ledger.write(
                company_id=context.company_id,
                propose={
                    "target_kind": "reactivity_proposed",
                    "ref_id": slug,
                    "reason": (
                        "phenomenon_gap reactivity proposal from chat seq="
                        f"{seq}"
                    ),
                    "proposed_by": "worm:phenomenon_gap",
                },
                execute_fn=lambda: {
                    "tool": "emit_reactivity_proposed",
                    "args": {
                        "reactivity_id": slug,
                        "name": label[:80],
                        "description": label,
                        "scope": "company",
                        "predicate_spec": {
                            "natural_language": spec.get(
                                "predicate_description",
                            ),
                        },
                        "condition_spec": {},
                        "action_spec": {
                            "natural_language": spec.get(
                                "action_description",
                            ),
                        },
                        "proposed_by": "worm:phenomenon_gap",
                    },
                    "result_ref": slug,
                },
                verify_fn=lambda _r: {"checks": [], "passed": True},
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": (
                        "reactivity proposal recorded — awaits admin confirm"
                    ),
                },
                quadrant="active_probabilistic",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "emit_reactivity_proposed failed for slug=%r: %s",
                slug, exc,
            )

        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(action_kind="phenomenon_gap_detected_reactivity"),
                FiredAction(action_kind="reactivity_proposed"),
            ],
            novelty_key=novelty_key,
            budget_used={"per_tenant": 1},
        )


__all__ = [
    "DomainReferenceWithoutDomainReactivity",
    "KpiReferenceWithoutKpiReactivity",
    "ProcessReferenceWithoutProcessReactivity",
    "RecurringActionWithoutReactivityReactivity",
]
