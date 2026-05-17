"""PolicyLoader + CompanyWarmup bootstrap.

PolicyLoader reads the ontology-seed `policy_templates.yaml` and writes
one `policy_applied` ledger entry per template, scoped to a company.
Idempotent: re-running on the same company is a no-op.

CompanyWarmup orchestrates the first-time bootstrap for a tenant:
  1) write `domain_registered` for each pre-seeded domain
  2) call PolicyLoader.load_templates
  3) compute initial RampState
  4) write `company_warmup_completed` summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ontology_seed import DomainTemplate, Loader, PolicyTemplate

from wormbase_governance.entities import Policy

# ---------------------------------------------------------------------------
# PolicyLoader
# ---------------------------------------------------------------------------


class PolicyLoader:
    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        ontology_loader: Loader | None = None,
    ) -> None:
        self._ledger = ledger
        self._loader = ontology_loader or Loader()

    async def load_templates(
        self, company_id: UUID, domain_pack: str = "saas"
    ) -> list[Policy]:
        templates = self._loader.load_policy_templates()
        # Fetch existing applied policy names for idempotency.
        existing_names: set[str] = set()
        rows = await self._ledger.fetch(company_id)
        for r in rows:
            if r["kind"] != "execute":
                continue
            payload = r["payload"]
            if payload.get("tool") == "emit_policy_applied":
                args = payload.get("args", {})
                if args.get("policy_name"):
                    existing_names.add(args["policy_name"])
        result: list[Policy] = []
        for t in templates:
            if not _applies_for_pack(t, domain_pack):
                continue
            if t.name in existing_names:
                continue
            policy_id = uuid4()
            await self._ledger.write(
                company_id=company_id,
                propose={
                    "target_kind": "policy_applied",
                    "ref_id": str(policy_id),
                    "reason": "warmup policy bootstrap",
                    "proposed_by": "policy_loader",
                },
                execute_fn=lambda t=t, policy_id=policy_id: {
                    "tool": "emit_policy_applied",
                    "args": {
                        "policy_id": str(policy_id),
                        "policy_name": t.name,
                        "applies_to": dict(t.applies_to),
                        "rule": t.rule,
                        "gate_impl": t.gate_impl,
                    },
                    "result_ref": t.id,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "policy_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "applied",
                    "rationale": "warmup template applied",
                },
                timestamp=datetime.now(UTC),
                quadrant="active_deterministic",
            )
            result.append(
                Policy(
                    id=policy_id,
                    name=t.name,
                    applies_to=dict(t.applies_to),
                    rule=t.rule,
                    gate_impl=t.gate_impl,
                    company_id=company_id,
                    active=True,
                )
            )
        return result


def _applies_for_pack(template: PolicyTemplate, pack: str) -> bool:
    target = template.applies_to.get("domain_pack", "*")
    return target in ("*", pack)


# ---------------------------------------------------------------------------
# CompanyWarmup
# ---------------------------------------------------------------------------


@dataclass
class WarmupReport:
    company_id: UUID
    domain_pack: str
    domains: list[str] = field(default_factory=list)
    policies: list[str] = field(default_factory=list)
    initial_ramp: dict[str, float] = field(default_factory=dict)
    already_warm: bool = False


class CompanyWarmup:
    """Bootstrap a fresh tenant: domains + policies + initial ramp snapshot."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        ontology_loader: Loader | None = None,
        clock: Any = None,
    ) -> None:
        self._ledger = ledger
        self._loader = ontology_loader or Loader()
        self._clock = clock
        self._policy_loader = PolicyLoader(ledger, self._loader)

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock.now()
        return datetime.now(UTC)

    async def warmup(
        self, company_id: UUID, domain_pack: str = "saas"
    ) -> WarmupReport:
        # Idempotency: prior `company_warmup_completed` -> short-circuit.
        rows = await self._ledger.fetch(company_id)
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"].get("args", {})
            if args.get("content", "").startswith("company_warmup_completed"):
                return WarmupReport(
                    company_id=company_id,
                    domain_pack=args.get("domain_pack", domain_pack),
                    domains=list(args.get("domains", [])),
                    policies=list(args.get("policies", [])),
                    initial_ramp=dict(args.get("initial_ramp", {})),
                    already_warm=True,
                )

        # Register pre-seeded domains.
        try:
            domain_templates = self._loader.load_domain_templates(domain_pack)
        except ValueError:
            domain_templates = []
        registered_domains: list[str] = []
        for d in domain_templates:
            await self._register_domain(company_id, d)
            registered_domains.append(d.id)

        # Apply policy templates.
        policies = await self._policy_loader.load_templates(company_id, domain_pack)
        applied_names = [p.name for p in policies]

        # Initial ramp snapshot — start at zeros (P3's RampState computer
        # will recompute later; this is just the first marker).
        initial_ramp = {
            "ontology": 0.0, "schema": 0.0, "business_definitions": 0.0,
            "kpi_relational": 0.0, "conversational": 0.0, "operational": 0.0,
        }

        # Record warmup completion.
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "company warmup",
                "proposed_by": "company_warmup",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": "company_warmup_completed",
                    "tags": [
                        "company_warmup_completed",
                        f"domain_pack:{domain_pack}",
                    ],
                    "domain_pack": domain_pack,
                    "domains": registered_domains,
                    "policies": applied_names,
                    "initial_ramp": initial_ramp,
                },
                "result_ref": "warmup",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "warmup_complete", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "tenant warmup recorded",
            },
            timestamp=self._now(),
            quadrant="active_deterministic",
        )

        return WarmupReport(
            company_id=company_id,
            domain_pack=domain_pack,
            domains=registered_domains,
            policies=applied_names,
            initial_ramp=initial_ramp,
            already_warm=False,
        )

    async def _register_domain(
        self, company_id: UUID, template: DomainTemplate
    ) -> None:
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "domain registration",
                "proposed_by": "company_warmup",
            },
            execute_fn=lambda t=template: {
                "tool": "emit_domain_registered",
                "args": {
                    "id": t.id,
                    "name": t.name,
                    "default_classification": t.default_classification,
                    "description": t.description,
                    "owner_person_id": None,
                },
                "result_ref": t.id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "domain_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "domain seeded",
            },
            timestamp=self._now(),
            quadrant="active_deterministic",
        )


__all__ = ["CompanyWarmup", "PolicyLoader", "WarmupReport"]
