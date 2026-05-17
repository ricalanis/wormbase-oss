"""W5.A4 — Team-scope and Company-scope autoresearch loop tests.

Drives :class:`TeamAutoresearchLoop`, :class:`CompanyAutoresearchLoop`, and
the conflict-arbitration logic in the existing per-Person loop. Each loop
follows the canonical PEVR cycle (propose → run → resolve) but tags the
``audience`` field on the proposal so downstream consumers (the dashboard
``/research`` Mine/Team/Company tabs) can scope the view.

Conflict arbitration is **specificity-inverted**: ``Company > Team > Person``.
Higher scope wins because it carries org-level authority over the metric.
The test matrix covers:

* Team loop fires with ``audience="team:<id>"``.
* Company loop fires with ``audience="company"``.
* Person ``keep`` is overridden by Team ``keep`` on same metric within 7 days.
* Person ``keep`` is overridden by Company ``keep`` on same metric within 7 days.
* Team ``keep`` is overridden by Company ``keep`` on same metric within 7 days.
* Team and Company ``keep``s are *not* overridden by lower-scope outcomes.
* Per-scope budget caps (5/3/1 default; configurable via env).
* Backward-compat: pre-W5.A4 rows deserialise as ``audience: "person:<id>"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from wormbase_research_loop.loop import (
    AutoresearchLoop,
    CompanyAutoresearchLoop,
    TeamAutoresearchLoop,
    _EXPERIMENT_NAMESPACE,
    _check_higher_scope_conflict,
    _normalise_audience,
)
from wormbase_core.positions import position_candidates


# Stable UUIDs.
GROWTH_TEAM = UUID("00000000-0000-0000-0000-0000000000a1")
RETENTION_TEAM = UUID("00000000-0000-0000-0000-0000000000a2")

CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
DAVE = UUID("00000000-0000-0000-0000-0000000000c2")
EVE = UUID("00000000-0000-0000-0000-0000000000c3")
INSTALLER = UUID("00000000-0000-0000-0000-0000000000d0")

NOW = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)


# ----------------------------------------------------------------------
# Fixture seeders
# ----------------------------------------------------------------------


async def _register_person(
    ledger, company_id: UUID, person_id: UUID, name: str, position: str
) -> None:
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_registered",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_registered",
            "args": {
                "person_id": str(person_id),
                "name": name,
                "email": f"{name.lower()}@example.com",
                "role": "admin",
                "registered_at": NOW.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "position_assigned",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_position_assigned",
            "args": {
                "person_id": str(person_id),
                "position": position,
                "at": NOW.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _grant_domain_role(
    ledger, company_id: UUID, person_id: UUID, domain_id: UUID, role: str = "contributor"
) -> None:
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "domain_role_assigned",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_domain_role_assigned",
            "args": {
                "person_id": str(person_id),
                "domain_id": str(domain_id),
                "role": role,
                "granted_by": str(INSTALLER),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _emitted(ledger, company_id, tool: str) -> list[dict]:
    rows = await ledger.fetch(company_id)
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == tool
    ]


async def _seed_growth_team(ledger, company_id: UUID) -> None:
    """Carol(cfo)+Dave(cfo)+Eve(cfo) all in growth team."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _register_person(ledger, company_id, DAVE, "Dave", "cfo")
    await _register_person(ledger, company_id, EVE, "Eve", "cfo")
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, DAVE, GROWTH_TEAM)
    await _grant_domain_role(ledger, company_id, EVE, GROWTH_TEAM)


# ----------------------------------------------------------------------
# Team loop emits experiments tagged audience="team:<id>"
# ----------------------------------------------------------------------


async def test_team_loop_emits_experiment_with_team_audience(ledger, company_id):
    await _seed_growth_team(ledger, company_id)
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=GROWTH_TEAM,
    )
    n = await loop.run_once(now=NOW)
    assert n == 1

    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    runs = await _emitted(ledger, company_id, "emit_experiment_run")
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    assert len(proposed) == 1
    assert len(runs) == 1
    assert len(resolved) == 1
    args = proposed[0]["payload"]["args"]
    assert args["audience"] == f"team:{GROWTH_TEAM}"
    # Same experiment_id stitches the cycle together.
    eid = args["experiment_id"]
    assert runs[0]["payload"]["args"]["experiment_id"] == eid
    assert resolved[0]["payload"]["args"]["experiment_id"] == eid


async def test_team_loop_skips_when_no_members(ledger, company_id):
    """Team-Domain with no members short-circuits — no proposals fire."""
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=GROWTH_TEAM,
    )
    n = await loop.run_once(now=NOW)
    assert n == 0
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    assert proposed == []


# ----------------------------------------------------------------------
# Company loop emits experiments tagged audience="company"
# ----------------------------------------------------------------------


async def test_company_loop_emits_experiment_with_company_audience(ledger, company_id):
    # Carol as a CFO — Company loop will pick her position to drive candidates.
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    n = await loop.run_once(now=NOW)
    assert n == 1
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    assert len(proposed) == 1
    args = proposed[0]["payload"]["args"]
    assert args["audience"] == "company"


async def test_company_loop_prefers_founder_over_random_position(ledger, company_id):
    """When a founder is registered, the Company loop borrows their position."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _register_person(ledger, company_id, DAVE, "Dave", "founder")
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    await loop.run_once(now=NOW)
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    args = proposed[0]["payload"]["args"]
    assert args["position"] == "founder"


async def test_company_loop_skips_when_no_persons(ledger, company_id):
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    n = await loop.run_once(now=NOW)
    assert n == 0


# ----------------------------------------------------------------------
# Conflict arbitration: Company > Team > Person.
#
# We seed a "winning" higher-scope outcome by hand-writing the PEVR rows for
# a different experiment_id on the same headline_metric, then run the lower-
# scope loop and assert the resolve carries the
# ``superseded_by_higher_scope:<aud>`` rationale.
# ----------------------------------------------------------------------


async def _seed_higher_scope_keep(
    ledger,
    company_id: UUID,
    *,
    metric: str,
    audience: str,
    position: str = "cfo",
    person_id: UUID = CAROL,
) -> UUID:
    """Hand-write a keep on (metric, audience) so a lower-scope loop sees it."""
    exp_id = uuid5(_EXPERIMENT_NAMESPACE, f"seed:{metric}:{audience}")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_proposed",
            "ref_id": str(exp_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_proposed",
            "args": {
                "experiment_id": str(exp_id),
                "for_person_id": str(person_id),
                "position": position,
                "headline_metric": metric,
                "proposed_change": {"kind": "test", "target": metric},
                "expected_delta": 0.05,
                "proposed_at": NOW.isoformat(),
                "audience": audience,
            },
            "result_ref": str(exp_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=NOW,
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_resolved",
            "ref_id": str(exp_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_resolved",
            "args": {
                "experiment_id": str(exp_id),
                "outcome": "keep",
                "observed_delta": 0.045,
                "rationale": "seeded higher-scope keep",
                "resolved_at": NOW.isoformat(),
            },
            "result_ref": str(exp_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=NOW,
    )
    return exp_id


def _picked_metric_for(person_id: UUID, position_id: str, cycle: int) -> str:
    """Recompute which headline_metric the deterministic picker will land on.

    Tests use this so the seeded conflict is on the metric the loop will
    actually propose against — independent of the registry shuffle order.
    """
    import hashlib
    cands = position_candidates(position_id)
    seed = f"{person_id}:{cycle}"
    idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(cands)
    return cands[idx].headline_metric_id


async def test_person_keep_overridden_by_company_keep_on_same_metric(
    ledger, company_id,
):
    """Person experiment on cfo cycle 0 → seed Company keep on the same metric → discard."""
    metric = _picked_metric_for(CAROL, "cfo", 0)
    await _seed_higher_scope_keep(
        ledger, company_id, metric=metric, audience="company",
    )
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    person_resolves = [
        r for r in resolved if r["payload"]["args"]["rationale"] != "seeded higher-scope keep"
    ]
    assert len(person_resolves) == 1
    args = person_resolves[0]["payload"]["args"]
    assert args["outcome"] == "discard"
    assert args["rationale"].startswith("superseded_by_higher_scope:")
    assert "company" in args["rationale"]


async def test_person_keep_overridden_by_team_keep_on_same_metric(
    ledger, company_id,
):
    metric = _picked_metric_for(CAROL, "cfo", 0)
    await _seed_higher_scope_keep(
        ledger, company_id, metric=metric, audience=f"team:{GROWTH_TEAM}",
    )
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    person_resolves = [
        r for r in resolved if r["payload"]["args"]["rationale"] != "seeded higher-scope keep"
    ]
    assert len(person_resolves) == 1
    args = person_resolves[0]["payload"]["args"]
    assert args["outcome"] == "discard"
    assert "team" in args["rationale"]


async def test_team_keep_overridden_by_company_keep_on_same_metric(
    ledger, company_id,
):
    # Team loop borrows a member's position via deterministic round-robin;
    # seed all relevant cfo candidate metrics so the test isn't fragile to
    # which member is picked.
    for metric in ("revenue", "cac_payback", "net_burn"):
        await _seed_higher_scope_keep(
            ledger, company_id, metric=metric, audience="company",
        )
    await _seed_growth_team(ledger, company_id)
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=GROWTH_TEAM,
    )
    await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    team_resolves = [
        r for r in resolved
        if r["payload"]["args"]["rationale"] != "seeded higher-scope keep"
    ]
    assert len(team_resolves) == 1
    args = team_resolves[0]["payload"]["args"]
    assert args["outcome"] == "discard"
    assert "company" in args["rationale"]


async def test_company_keep_not_superseded_by_anything(ledger, company_id):
    """Company outcomes are the apex — no lower scope can override them."""
    metric = _picked_metric_for(CAROL, "cfo", 0)
    # Pre-seed a Person+Team keep on the metric. The Company loop must not
    # be force-discarded by either.
    await _seed_higher_scope_keep(
        ledger, company_id, metric=metric, audience=f"person:{CAROL}",
    )
    await _seed_higher_scope_keep(
        ledger, company_id, metric=metric, audience=f"team:{GROWTH_TEAM}",
    )
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    company_resolves = [
        r for r in resolved
        if r["payload"]["args"]["rationale"] != "seeded higher-scope keep"
    ]
    # The deterministic _resolve picks keep or discard by hash; what matters
    # is the rationale is NOT a superseded one.
    assert len(company_resolves) == 1
    args = company_resolves[0]["payload"]["args"]
    assert not args["rationale"].startswith("superseded_by_higher_scope:")


# ----------------------------------------------------------------------
# Per-scope budget caps (5/3/1 default; configurable via env)
# ----------------------------------------------------------------------


async def test_team_budget_cap_default_3_per_day(ledger, company_id):
    await _seed_growth_team(ledger, company_id)
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=GROWTH_TEAM,
    )
    # 4 cycles within the same 24h window — the 4th must be budget-blocked.
    fired = 0
    for _ in range(4):
        n = await loop.run_once(now=NOW)
        fired += n
    assert fired == 3


async def test_company_budget_cap_default_1_per_day(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    fired = 0
    for _ in range(3):
        n = await loop.run_once(now=NOW)
        fired += n
    assert fired == 1


async def test_team_budget_env_override(ledger, company_id, monkeypatch):
    """``WORM_CORE_AUTORESEARCH_BUDGET_TEAM`` raises the cap."""
    monkeypatch.setenv("WORM_CORE_AUTORESEARCH_BUDGET_TEAM", "5")
    await _seed_growth_team(ledger, company_id)
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=GROWTH_TEAM,
    )
    fired = 0
    for _ in range(6):
        n = await loop.run_once(now=NOW)
        fired += n
    assert fired == 5


async def test_company_budget_env_override(ledger, company_id, monkeypatch):
    monkeypatch.setenv("WORM_CORE_AUTORESEARCH_BUDGET_COMPANY", "2")
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
    )
    fired = 0
    for _ in range(4):
        n = await loop.run_once(now=NOW)
        fired += n
    assert fired == 2


# ----------------------------------------------------------------------
# Backward compatibility: pre-W5.A4 rows have no ``audience`` field.
# ----------------------------------------------------------------------


def test_normalise_audience_legacy_payload_falls_back_to_person():
    payload = {
        "tool": "emit_experiment_proposed",
        "args": {
            "experiment_id": "00000000-0000-0000-0000-000000000001",
            "for_person_id": str(CAROL),
            "position": "cfo",
            "headline_metric": "revenue",
            "proposed_change": {},
            "expected_delta": 0.0,
            "proposed_at": NOW.isoformat(),
            # No audience key.
        },
    }
    aud = _normalise_audience(payload)
    assert aud == f"person:{CAROL}"


def test_normalise_audience_explicit_marker_passes_through():
    payload = {
        "tool": "emit_experiment_proposed",
        "args": {
            "experiment_id": "00000000-0000-0000-0000-000000000002",
            "for_person_id": str(CAROL),
            "position": "cfo",
            "headline_metric": "revenue",
            "proposed_change": {},
            "expected_delta": 0.0,
            "proposed_at": NOW.isoformat(),
            "audience": f"team:{GROWTH_TEAM}",
        },
    }
    assert _normalise_audience(payload) == f"team:{GROWTH_TEAM}"


async def test_legacy_person_keep_supersedes_legacy_team_experiment(
    ledger, company_id,
):
    """A legacy (no-audience) ``keep`` on `revenue` is treated as Person-scope.

    A Team loop on the same metric must NOT be force-discarded by it (Person
    < Team in the hierarchy).
    """
    # Hand-write a legacy proposed (no audience field) + resolved keep.
    exp_id = UUID("00000000-0000-0000-0000-0000000000ee")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_proposed",
            "ref_id": str(exp_id),
            "reason": "legacy seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_proposed",
            "args": {
                "experiment_id": str(exp_id),
                "for_person_id": str(CAROL),
                "position": "cfo",
                "headline_metric": "revenue",
                "proposed_change": {"kind": "x", "target": "y"},
                "expected_delta": 0.05,
                "proposed_at": NOW.isoformat(),
                # No audience key — pre-W5.A4 wire form.
            },
            "result_ref": str(exp_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "legacy seed"},
        timestamp=NOW,
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_resolved",
            "ref_id": str(exp_id),
            "reason": "legacy seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_resolved",
            "args": {
                "experiment_id": str(exp_id),
                "outcome": "keep",
                "observed_delta": 0.045,
                "rationale": "legacy seeded keep",
                "resolved_at": NOW.isoformat(),
            },
            "result_ref": str(exp_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "legacy seed"},
        timestamp=NOW,
    )
    # Team loop must NOT be force-discarded by a Person-scope outcome.
    higher = await _check_higher_scope_conflict(
        ledger,
        company_id,
        metric="revenue",
        own_scope="team",
        now=NOW,
    )
    assert higher is None


async def test_higher_scope_lookback_window_7_days(ledger, company_id):
    """Outcomes older than 7 days are stale and do not gate lower scopes."""
    # Seed a Company keep at NOW.
    await _seed_higher_scope_keep(
        ledger, company_id, metric="revenue", audience="company",
    )
    # Query 8 days later — the conflict window has expired.
    later = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)  # 9 days after NOW
    higher = await _check_higher_scope_conflict(
        ledger,
        company_id,
        metric="revenue",
        own_scope="person",
        now=later,
    )
    assert higher is None


async def test_higher_scope_company_beats_team_in_same_window(ledger, company_id):
    """When BOTH a Team and Company keep exist, Company wins the arbitration."""
    await _seed_higher_scope_keep(
        ledger, company_id, metric="revenue", audience=f"team:{GROWTH_TEAM}",
    )
    await _seed_higher_scope_keep(
        ledger, company_id, metric="revenue", audience="company",
    )
    higher = await _check_higher_scope_conflict(
        ledger,
        company_id,
        metric="revenue",
        own_scope="person",
        now=NOW,
    )
    assert higher == "company"


async def test_higher_scope_unrelated_metric_does_not_gate(ledger, company_id):
    """A Company keep on `nps` does not gate a Person experiment on `revenue`."""
    await _seed_higher_scope_keep(
        ledger, company_id, metric="nps", audience="company",
    )
    higher = await _check_higher_scope_conflict(
        ledger,
        company_id,
        metric="revenue",
        own_scope="person",
        now=NOW,
    )
    assert higher is None
