"""W5.A3 — phenomenon-gap detector tests.

Four detector reactivities, each with ≥6 tests covering:

  1. Detection (positive case — predicate matches and fire emits the gap entry)
  2. No-fire when phenomenon already exists (negative — KPI / Domain /
     Process / Reactivity already present)
  3. Cooldown (24h novelty window — second fire suppressed)
  4. Confidence-threshold filtering (low-confidence statements don't fire)
  5. Per-tenant budget cap
  6. Predicate composability (the advanced predicate combines with EntryKind)

Tests run on InMemoryLedger so they exercise the full propose-execute-
verify-resolve write surface end-to-end without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    ReactivityContext,
    ReactivityRegistry,
)
from wormbase_reactivities.phenomenon_gaps import (
    DomainReferenceWithoutDomainReactivity,
    KpiReferenceWithoutKpiReactivity,
    ProcessReferenceWithoutProcessReactivity,
    RecurringActionWithoutReactivityReactivity,
)
from wormbase_reactivities.predicates_advanced import (
    DescribesProcessNotInLake,
    DescribesRecurringPattern,
    MentionsDomainNotInOntology,
    MentionsMetricNotInKpiTree,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    now: datetime | None = None,
) -> ReactivityRegistry:
    fixed = now or datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    return ReactivityRegistry(
        ledger=ledger,
        company_id=company_id,
        now=lambda: fixed,
    )


def _chat_received_entry(
    seq: int,
    *,
    text: str,
    sender_person: str = "p-1",
    domain: str | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "text": text,
        "sender_person": sender_person,
        "channel_id": "C-1",
    }
    if domain is not None:
        args["domain"] = domain
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


async def _seed_kpi(
    ledger: InMemoryLedger, company_id: UUID, *, label: str,
) -> None:
    """Drop a fake emit_kpi_proposed entry so the projection probe sees it."""
    ref_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "kpi_proposed",
            "ref_id": str(ref_id),
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_kpi_proposed",
            "args": {
                "kpi_id": str(uuid4()),
                "label": label,
                "formula": "x",
                "source_ids": [],
                "unit": "count",
                "owner_position": None,
                "proposed_at": "2026-04-28T12:00:00Z",
            },
            "result_ref": str(ref_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _seed_domain_reference(
    ledger: InMemoryLedger, company_id: UUID, *, label: str,
) -> None:
    """Drop a fake execute entry carrying ``args.domain = label`` so the
    domain probe sees it as part of the ontology."""
    ref_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "anything",
            "ref_id": str(ref_id),
            "reason": "seed domain",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_test",
            "args": {"domain": label, "domain_id": str(uuid4())},
            "result_ref": str(ref_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _seed_process(
    ledger: InMemoryLedger, company_id: UUID, *, name: str,
) -> None:
    ref_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "process_map_proposed",
            "ref_id": str(ref_id),
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_process_map_proposed",
            "args": {
                "process_id": str(uuid4()),
                "process_name": name,
                "steps": [],
                "domain": "general",
                "confidence": 0.95,
            },
            "result_ref": str(ref_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _seed_reactivity_proposed(
    ledger: InMemoryLedger, company_id: UUID, *, reactivity_id: str,
) -> None:
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "reactivity_proposed",
            "ref_id": reactivity_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_reactivity_proposed",
            "args": {
                "reactivity_id": reactivity_id,
                "name": "X",
                "description": "X",
                "scope": "company",
                "predicate_spec": {},
                "condition_spec": {},
                "action_spec": {},
                "proposed_by": "test",
            },
            "result_ref": reactivity_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _gap_entries(
    ledger: InMemoryLedger, company_id: UUID,
) -> list[dict[str, Any]]:
    rows = await ledger.fetch(company_id)
    out = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool") or ""
        if tool == "emit_phenomenon_gap_detected":
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# KpiReferenceWithoutKpiReactivity
# ---------------------------------------------------------------------------


class TestKpiReferenceWithoutKpi:
    async def test_detection_when_metric_missing(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = KpiReferenceWithoutKpiReactivity()
        registry.register(r)
        entry = _chat_received_entry(1, text="we should track NPS")
        fired = await registry.dispatch(entry)
        assert r.id in fired
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1
        args = gaps[0]["payload"]["args"]
        assert args["kind"] == "kpi"
        assert args["suggested_proposal"]["label"] == "nps"
        assert args["confidence"] >= 0.6
        assert args["referenced_in_seq"] == 1

    async def test_no_fire_when_kpi_already_exists(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        await _seed_kpi(ledger, company_id, label="nps")
        registry = _make_registry(ledger, company_id)
        r = KpiReferenceWithoutKpiReactivity()
        registry.register(r)
        entry = _chat_received_entry(99, text="we should track NPS")
        fired = await registry.dispatch(entry)
        assert r.id not in fired
        # Fixtures-only — no gap entry should exist.
        gaps = await _gap_entries(ledger, company_id)
        assert gaps == []

    async def test_cooldown_suppresses_repeat_within_24h(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = KpiReferenceWithoutKpiReactivity()
        registry.register(r)
        entry1 = _chat_received_entry(1, text="we should track NPS")
        entry2 = _chat_received_entry(2, text="track NPS for the team")
        fired1 = await registry.dispatch(entry1)
        fired2 = await registry.dispatch(entry2)
        assert r.id in fired1
        assert r.id not in fired2
        # Only one gap entry — the second was cooled off.
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1

    async def test_low_confidence_does_not_fire(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        # Bare mention without "track / measure / kpi" cue stays at 0.6
        # which is the default threshold; raise the threshold and confirm
        # the bare-mention case is now below it.
        r = KpiReferenceWithoutKpiReactivity(confidence_threshold=0.8)
        registry.register(r)
        entry = _chat_received_entry(1, text="our retention has been ok")
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_per_tenant_budget_cap(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        # Drop the budget to 1 by inserting a custom Reactivity instance.
        r = KpiReferenceWithoutKpiReactivity()
        # Pre-charge the budget axis to its cap; the next dispatch must be
        # blocked by DailyBudget BEFORE fire runs.
        registry.register(r)
        # Charge the per_tenant counter to the cap.
        from wormbase_reactivities.conditions import DailyBudget

        # Mutate the condition's per_tenant cap to 1 for this test.
        r.condition = DailyBudget(per_owner=None, per_domain=10, per_tenant=1)
        # First fire — succeeds.
        entry1 = _chat_received_entry(
            1, text="we should track NPS",
        )
        fired1 = await registry.dispatch(entry1)
        assert r.id in fired1
        # Second fire on a different metric — budget cap blocks it.
        entry2 = _chat_received_entry(
            2, text="we should monitor MRR closely",
        )
        fired2 = await registry.dispatch(entry2)
        assert r.id not in fired2

    async def test_predicate_composability(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        # The detector composes EntryKind("chat_received") & MentionsMetric.
        # A non-chat entry with "track NPS" text doesn't fire.
        r = KpiReferenceWithoutKpiReactivity()
        registry.register(r)
        entry = {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_person_proposed",
                "args": {"text": "we should track NPS"},
            },
        }
        fired = await registry.dispatch(entry)
        assert r.id not in fired


# ---------------------------------------------------------------------------
# DomainReferenceWithoutDomainReactivity
# ---------------------------------------------------------------------------


class TestDomainReferenceWithoutDomain:
    async def test_detection_when_domain_missing(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            1, text="The compliance team needs that report tomorrow.",
        )
        fired = await registry.dispatch(entry)
        assert r.id in fired
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1
        args = gaps[0]["payload"]["args"]
        assert args["kind"] == "domain"
        assert args["suggested_proposal"]["label"] == "compliance"
        assert args["referenced_in_seq"] == 1

    async def test_no_fire_when_domain_in_ontology(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        await _seed_domain_reference(ledger, company_id, label="compliance")
        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            99, text="the compliance team needs that report",
        )
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_cooldown_suppresses_repeat(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity()
        registry.register(r)
        entry1 = _chat_received_entry(
            1, text="the compliance team needs review.",
        )
        entry2 = _chat_received_entry(
            2, text="the compliance team is busy",
        )
        fired1 = await registry.dispatch(entry1)
        fired2 = await registry.dispatch(entry2)
        assert r.id in fired1
        assert r.id not in fired2

    async def test_low_confidence_does_not_fire(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity(confidence_threshold=0.95)
        registry.register(r)
        # Bare mention from vocab is 0.65; cue-phrase is 0.85 — both below
        # 0.95 threshold.
        entry = _chat_received_entry(1, text="the compliance team")
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_per_tenant_budget_cap(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        from wormbase_reactivities.conditions import DailyBudget

        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity()
        r.condition = DailyBudget(per_owner=None, per_domain=None, per_tenant=1)
        registry.register(r)
        e1 = _chat_received_entry(1, text="the compliance team is busy")
        e2 = _chat_received_entry(2, text="the marketing team is hiring")
        f1 = await registry.dispatch(e1)
        f2 = await registry.dispatch(e2)
        assert r.id in f1
        assert r.id not in f2

    async def test_predicate_composability(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = DomainReferenceWithoutDomainReactivity()
        registry.register(r)
        entry = {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_person_proposed",
                "args": {"text": "the compliance team needs review"},
            },
        }
        fired = await registry.dispatch(entry)
        assert r.id not in fired


# ---------------------------------------------------------------------------
# ProcessReferenceWithoutProcessReactivity
# ---------------------------------------------------------------------------


class TestProcessReferenceWithoutProcess:
    async def test_detection_when_process_missing(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = ProcessReferenceWithoutProcessReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            1, text="every Friday we run the data quality review.",
        )
        fired = await registry.dispatch(entry)
        assert r.id in fired
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1
        args = gaps[0]["payload"]["args"]
        assert args["kind"] == "process"
        # The extractor pulls the noun phrase after the verb.
        assert "data quality review" in args["suggested_proposal"][
            "process_name"
        ].lower()

    async def test_no_fire_when_process_already_exists(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        await _seed_process(
            ledger, company_id, name="data quality review",
        )
        registry = _make_registry(ledger, company_id)
        r = ProcessReferenceWithoutProcessReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            99, text="every Friday we run the data quality review",
        )
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_cooldown_suppresses_repeat(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = ProcessReferenceWithoutProcessReactivity()
        registry.register(r)
        # Identical text → identical novelty_key → second dispatch must
        # be suppressed by the 24h cooldown.
        e1 = _chat_received_entry(
            1, text="every Friday we run the data quality review.",
        )
        e2 = _chat_received_entry(
            2, text="every Friday we run the data quality review.",
        )
        f1 = await registry.dispatch(e1)
        f2 = await registry.dispatch(e2)
        assert r.id in f1
        assert r.id not in f2

    async def test_low_confidence_does_not_fire(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        # No cadence cue → no candidate at all → no fire regardless of threshold.
        r = ProcessReferenceWithoutProcessReactivity()
        registry.register(r)
        entry = _chat_received_entry(1, text="we run the data quality review")
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_per_tenant_budget_cap(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        from wormbase_reactivities.conditions import DailyBudget

        registry = _make_registry(ledger, company_id)
        r = ProcessReferenceWithoutProcessReactivity()
        r.condition = DailyBudget(per_owner=None, per_domain=None, per_tenant=1)
        registry.register(r)
        e1 = _chat_received_entry(
            1, text="every Friday we run the deploy review.",
        )
        e2 = _chat_received_entry(
            2, text="every Monday we hold the standup.",
        )
        f1 = await registry.dispatch(e1)
        f2 = await registry.dispatch(e2)
        assert r.id in f1
        assert r.id not in f2

    async def test_predicate_composability(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = ProcessReferenceWithoutProcessReactivity()
        registry.register(r)
        entry = {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_person_proposed",
                "args": {
                    "text": "every Friday we run the data quality review.",
                },
            },
        }
        fired = await registry.dispatch(entry)
        assert r.id not in fired


# ---------------------------------------------------------------------------
# RecurringActionWithoutReactivityReactivity (the meta-case)
# ---------------------------------------------------------------------------


class TestRecurringActionWithoutReactivity:
    async def test_detection_on_whenever_template(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            1, text="every time a deploy fails, ping the on-call engineer.",
        )
        fired = await registry.dispatch(entry)
        assert r.id in fired
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1
        args = gaps[0]["payload"]["args"]
        assert args["kind"] == "reactivity"
        suggested = args["suggested_proposal"]
        assert "natural_language" in suggested
        assert suggested["requires_admin_edit"] is True
        # The proposal also writes a separate emit_reactivity_proposed cycle
        # so /reactivities sees it as a pending proposal.
        rows = await ledger.fetch(company_id)
        proposed_tools = {
            (r.get("payload") or {}).get("tool")
            for r in rows
            if r.get("kind") == "execute"
        }
        assert "emit_reactivity_proposed" in proposed_tools

    async def test_no_fire_when_reactivity_already_proposed(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        # The detector slugs from "whenever <trigger>, <action>" — see
        # predicates_advanced._extract_recurring_pattern. Seed that exact
        # slug so the existence probe finds it.
        seeded_slug = "whenever-a-deploy-fails-ping-the-on-call-engineer"
        await _seed_reactivity_proposed(
            ledger, company_id, reactivity_id=seeded_slug,
        )
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            99, text="every time a deploy fails, ping the on-call engineer.",
        )
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_cooldown_suppresses_repeat(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        e1 = _chat_received_entry(
            1, text="every time a deploy fails, ping the on-call engineer.",
        )
        e2 = _chat_received_entry(
            2, text="every time a deploy fails, ping the on-call engineer!",
        )
        f1 = await registry.dispatch(e1)
        f2 = await registry.dispatch(e2)
        assert r.id in f1
        assert r.id not in f2

    async def test_low_confidence_does_not_fire(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        # No automation-shaped templates; just prose.
        entry = _chat_received_entry(
            1, text="The deploy failed yesterday, that was rough.",
        )
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_per_tenant_budget_cap(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        from wormbase_reactivities.conditions import DailyBudget

        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        r.condition = DailyBudget(per_owner=None, per_domain=None, per_tenant=1)
        registry.register(r)
        e1 = _chat_received_entry(
            1, text="every time a deploy fails, ping the on-call engineer.",
        )
        e2 = _chat_received_entry(
            2, text="whenever a customer churns, alert the cs lead.",
        )
        f1 = await registry.dispatch(e1)
        f2 = await registry.dispatch(e2)
        assert r.id in f1
        assert r.id not in f2

    async def test_predicate_composability(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        entry = {
            "kind": "execute",
            "seq": 1,
            "payload": {
                "tool": "emit_person_proposed",
                "args": {
                    "text": "every time a deploy fails, ping on-call.",
                },
            },
        }
        fired = await registry.dispatch(entry)
        assert r.id not in fired

    async def test_proposed_reactivity_carries_admin_edit_flag(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        """The meta-case proposal must require admin edit. Per the spec:
        the reactivity NEVER auto-activates, only proposes."""
        registry = _make_registry(ledger, company_id)
        r = RecurringActionWithoutReactivityReactivity()
        registry.register(r)
        entry = _chat_received_entry(
            1, text="every time a deploy fails, ping the on-call engineer.",
        )
        await registry.dispatch(entry)
        gaps = await _gap_entries(ledger, company_id)
        assert len(gaps) == 1
        suggested = gaps[0]["payload"]["args"]["suggested_proposal"]
        assert suggested.get("requires_admin_edit") is True
        assert suggested.get("scope") == "company"
        # Predicate / action specs carry the natural-language sketch.
        assert (
            suggested.get("predicate_spec", {}).get("natural_language")
            is not None
        )
        assert (
            suggested.get("action_spec", {}).get("natural_language")
            is not None
        )


# ---------------------------------------------------------------------------
# Cross-cutting tests: per-detector independence + advanced predicate API
# ---------------------------------------------------------------------------


class TestCrossCutting:
    async def test_detectors_independent_per_tenant(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        """Registering only one of the four works without the others."""
        registry = _make_registry(ledger, company_id)
        registry.register(KpiReferenceWithoutKpiReactivity())
        # Only KPI detector registered. Domain text doesn't fire it.
        entry = _chat_received_entry(
            1, text="the compliance team needs that report.",
        )
        fired = await registry.dispatch(entry)
        assert "kpi_reference_without_kpi" not in fired
        gaps = await _gap_entries(ledger, company_id)
        assert gaps == []

    async def test_metric_predicate_directly_short_circuits_on_empty_text(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        ctx = ReactivityContext(
            ledger=ledger, company_id=company_id, registry=registry,
            now=registry._now,  # noqa: SLF001
            extras={"reactivity_id": "kpi_reference_without_kpi"},
        )
        p = MentionsMetricNotInKpiTree()
        # No payload args → no match, but no crash.
        assert await p.match(
            {"kind": "execute", "seq": 1, "payload": {"tool": "x"}},
            ctx,
        ) is False

    async def test_domain_predicate_handles_empty_text(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        ctx = ReactivityContext(
            ledger=ledger, company_id=company_id, registry=registry,
            now=registry._now,  # noqa: SLF001
            extras={"reactivity_id": "domain_reference_without_domain"},
        )
        p = MentionsDomainNotInOntology()
        assert await p.match(
            {"kind": "execute", "seq": 1, "payload": {"tool": "x"}},
            ctx,
        ) is False

    async def test_process_predicate_handles_no_cadence(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        ctx = ReactivityContext(
            ledger=ledger, company_id=company_id, registry=registry,
            now=registry._now,  # noqa: SLF001
            extras={"reactivity_id": "process_reference_without_process"},
        )
        p = DescribesProcessNotInLake()
        # Process verb without cadence → no match.
        assert await p.match(
            _chat_received_entry(1, text="we hold the standup at 10."), ctx,
        ) is False

    async def test_recurring_pattern_predicate_no_template_no_match(
        self, ledger: InMemoryLedger, company_id: UUID,
    ) -> None:
        registry = _make_registry(ledger, company_id)
        ctx = ReactivityContext(
            ledger=ledger, company_id=company_id, registry=registry,
            now=registry._now,  # noqa: SLF001
            extras={"reactivity_id": "recurring_action_without_reactivity"},
        )
        p = DescribesRecurringPattern()
        assert await p.match(
            _chat_received_entry(
                1, text="we should think about deploys more carefully.",
            ),
            ctx,
        ) is False
